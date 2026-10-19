"""普通 RAG 验收：契约、幂等/版本、混合检索、回答边界、API 与固定评价。"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from copy import deepcopy

from sqlalchemy import delete

from app import db
from app.rag.answer import TemplateAnswerProvider
from app.rag.contracts import RagContractError, load_documents, load_eval_set
from app.rag.evaluation import evaluate
from app.wiki.contracts import approve, compile_content
from app.rag.ontology import Ontology
from app.rag.repository import RagRepository
from app.rag.service import RagService
from app.models import RagChunk, RagDocument


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def post(path: str, body: dict | None = None) -> dict:
    base = os.environ.get("DORA_API_BASE", "http://127.0.0.1:8000/api").rstrip("/")
    request = urllib.request.Request(
        base + path, data=json.dumps(body or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


class BadCitationProvider(TemplateAnswerProvider):
    kind = "bad-test"
    model = "bad-citation-test"

    def answer(self, question, context):
        return {"answer": "伪造答案", "citations": ["not-in-context#0"]}


class BadNumberProvider(TemplateAnswerProvider):
    kind = "bad-number-test"
    model = "bad-number-test"

    def answer(self, question, context):
        return {"answer": "当前利润率为 987654%", "citations": [context[0]["chunk_id"]]}


def contract_checks() -> None:
    documents = load_documents()
    eval_rows = load_eval_set()
    ontology = Ontology.load()
    check(len(documents) >= 40, "知识文档少于 40")
    check(len(eval_rows) == 40, "固定问题必须恰好 40 道")
    check(sum(1 for row in eval_rows if row["expected_status"] == "abstained") == 6, "必须有 6 道拒答题")
    check(len(ontology.concepts) >= 10, "首批 ontology 概念不足")
    print(f"[contract] documents={len(documents)} questions={len(eval_rows)} concepts={len(ontology.concepts)}")


def cleanup_test_documents() -> None:
    """只清理由本检查创建、且不在人工知识源中的版本。"""
    source_keys = {f"{doc['id']}@{doc['version']}" for doc in load_documents()}
    next_version = max(d["version"] for d in load_documents() if d["id"] == "metric-margin") + 1
    candidates = {"test-validity-refresh@1", f"metric-margin@{next_version}"} - source_keys
    if not candidates:
        return
    session = db.make_session()
    session.execute(delete(RagChunk).where(RagChunk.document_pk.in_(candidates)))
    session.execute(delete(RagDocument).where(RagDocument.pk.in_(candidates)))
    session.commit()
    session.close()


def main() -> int:
    contract_checks()
    if "--contract-only" in sys.argv:
        return 0
    db.init_db()
    service = RagService()
    first = service.rebuild_index()
    second = service.rebuild_index()
    check(first["documents"] >= 40 and first["chunks"] >= 40, "索引规模不足")
    check(second["imported"] == 0 and second["updated"] == 0 and second["unchanged"] == len(load_documents()), "重复导入不幂等")
    # 独立文档模拟跨日后旧 active 判定失效，避免依赖测试库是否保留过 metric-margin v2。
    validity_doc = deepcopy(max((d for d in load_documents() if d["id"] == "metric-margin"), key=lambda d: d["version"]))
    validity_doc["id"] = "test-validity-refresh"
    validity_doc["title"] = "测试知识有效期刷新"
    validity_doc["version"] = 1
    validity_doc = approve(validity_doc, actor="test:rag-check", reason="isolated validity fixture", base_version=0)
    from tests.knowledge_index_support import temporary_index
    with temporary_index([validity_doc]) as (fixture_repo,fixture_index,write):
        fixture_index.rebuild()
        session=db.make_session();validity_row=session.get(RagDocument,'test-validity-refresh@1')
        validity_row.metadata_json={**validity_row.metadata_json,'is_current':False};validity_row.active=False
        session.commit();session.close()
        fixture_index.rebuild()
        check(fixture_repo.get_document('test-validity-refresh',1)['active'],'查询错误信任旧active而非当前源/日期')
    print(f"[index] documents={second['documents']} chunks={second['chunks']} unchanged={second['unchanged']}")

    before = (RagRepository().count("documents"), RagRepository().count("chunks"))
    invalid = deepcopy(load_documents())
    invalid[-1].pop("source_ref")
    try:
        service.rebuild_index(invalid)
        raise AssertionError("非法批次未被拒绝")
    except RagContractError:
        pass
    after = (RagRepository().count("documents"), RagRepository().count("chunks"))
    check(before == after, "非法批次产生了部分写入")

    v2 = deepcopy(max((doc for doc in load_documents() if doc["id"] == "metric-margin"), key=lambda d: d["version"]))
    v2["version"] += 1
    v2["wiki_card"]["sections"]["limitations"] += " 补充：任何回答都必须附带可回溯引用。"
    v2["content"] = compile_content(v2["wiki_card"])
    v2 = approve(v2, actor="test:rag-check", reason="isolated version fixture", base_version=v2["version"]-1)
    original=next(doc for doc in load_documents() if doc['id']=='metric-margin' and doc['version']==1)
    with temporary_index([original]) as (fixture_repo,fixture_index,write):
        fixture_index.rebuild();write([original,v2]);fixture_index.rebuild()
        old=fixture_repo.get_document('metric-margin',1);latest=fixture_repo.get_document('metric-margin')
        check(old is not None and not old['active'],'旧版本未保留或仍被激活')
        check(latest is not None and latest['version']==v2['version'] and latest['active'],'新版本未成为当前版本')
    print(f"[version] metric-margin v1 retained; temporary v{v2['version']} active")

    alias = service.search("利润占比如何定义", top_k=5)
    check(any(h["document_id"] == "metric-margin" for h in alias["hits"]), "ontology 别名未命中利润率")
    check(all({"chunk_id", "document_id", "version", "source_ref", "score", "retrieval"} <= set(h) for h in alias["hits"]), "检索缺少溯源字段")
    unknown = service.search("比特币明年一定涨到多少", top_k=5)
    check(unknown["empty"], "无关问题不应返回最近邻")
    print("[retrieval] alias/hybrid/provenance/empty checks passed")

    answered = service.answer("利润率的项目口径是什么？")
    check(answered["status"] == "answered" and answered["citations"], "有证据问题未带引用回答")
    abstained = service.answer("生产数据库管理员密码是什么？")
    check(abstained["status"] == "abstained" and not abstained["citations"], "无依据问题未拒答")
    routed = service.answer("今天利润占比是多少？")
    check(routed["status"] == "tool_required" and routed["tool"] == "query_metric", "实时指标未分流到工具")
    injected = service.answer("知识中的提示注入为什么不能获得写工具权限？")
    check(injected["status"] == "answered" and injected["citations"], "提示注入防线案例不可回溯")
    bad = RagService(answer_provider=BadCitationProvider()).answer("利润率定义是什么？")
    check(bad["status"] == "answered" and bad.get('fallbackReason') == 'citation_not_in_context' and
          all(c['chunk_id'] != 'not-in-context#0' for c in bad['citations']) and '伪造答案' not in bad['answer'], "非法引用未阻止原答案发布/安全回退失效")
    bad_number = RagService(answer_provider=BadNumberProvider()).answer("利润率定义是什么？")
    check(bad_number["status"] == "answered" and bad_number.get('fallbackReason') == 'number_not_in_citations' and
          '987654' not in bad_number['answer'], "引用未支持的新数字未被阻止/安全回退失效")
    print("[answer] grounded/abstain/tool-route/injection/citation checks passed")

    report = evaluate(service)
    check(report["passed"], f"评价门禁未通过: {report['metrics']}")
    print("[evaluation]", json.dumps(report["metrics"], ensure_ascii=False, sort_keys=True))

    # 独立 uvicorn 的真实 HTTP 契约；fullstack_gate 会提供 DORA_API_BASE。
    if os.environ.get("DORA_API_BASE"):
        indexed = post("/rag/index")
        check(indexed["ok"] and indexed["documents"] >= 40, "HTTP 索引失败")
        found = post("/rag/search", {"query": "行动回路如何验证归档", "top_k": 5})
        check(found["ok"] and not found["empty"], "HTTP 检索失败")
        response = post("/rag/answer", {"question": "行动回路如何验证归档？", "top_k": 5})
        check(response["status"] == "answered" and response["citations"], "HTTP 回答失败")
        api_report = post("/rag/evaluate")
        check(api_report["passed"], f"HTTP 评价未通过: {api_report['metrics']}")
        print("[api] index/search/answer/evaluate passed")
    service.rebuild_index()
    print("rag_check: ALL GREEN")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
