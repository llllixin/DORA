"""V3-T1 reasoning 自检：抽象层 parity（模板 provider == 引擎默认语义）。

运行：cd backend && python3 -m tests.reasoning_check
前置：PostgreSQL 已 seed（本地 docker compose up -d 后 python -m app.seed）。
"""
import sys

from app.engine.engine import run_engine
from app.reasoning.cache import refresh
from app.reasoning.llm import LLMProvider, _merge_with_numeric_stability
from app.reasoning.provider import (
    ReasoningContext,
    ReasoningResult,
    TemplateProvider,
    resolve_provider,
)
from app.repository import Repository
from app.seed import run_seed


def main() -> int:
    run_seed()
    provider = resolve_provider()  # 默认应解析为 template
    assert isinstance(provider, TemplateProvider), "default provider must be TemplateProvider"
    assert provider.kind == "template"

    res = run_engine()
    snap = res["snapshot"]
    checked = 0
    for insight in res["insights"]:
        ctx = ReasoningContext(
            insight_id=insight["id"],
            insight_type=insight["type"],
            metric=insight["metric"],
            delta=insight["delta"],
            trigger=insight["trigger"],
            factors=insight["factors"],
            question=insight["question"],
            snapshot=snap,
        )
        out: ReasoningResult = provider.explain(ctx)
        assert out.provider == "template"
        assert out.semantics == insight["semantics"], f"parity break on {insight['id']}"
        checked += 1
    assert checked >= 8, "should check most insights"
    assert resolve_provider("template").kind == "template"

    try:
        resolve_provider("nope")
        raise AssertionError("unknown provider should raise")
    except ValueError:
        pass

    # T3：LLM provider 解析与无 key fallback / 数值稳定
    llm = resolve_provider("llm")
    assert isinstance(llm, LLMProvider) and llm.kind == "llm"
    repo2 = Repository()
    repo2.delete_all_reasoning()
    no_key_result = refresh(repo2, res["insights"], res["snapshot"], provider=llm)
    assert not no_key_result["updated"] and len(no_key_result["fallback"]) == len(res["insights"]), \
        "no key -> all fallback"
    repo2.delete_all_reasoning()
    base = {"causeA": {"name": "旧名", "value": "较期初 2.2%"}, "causeB": {"name": "旧定位", "value": "高 10.9%"},
            "next": ["a", "b", "c"]}
    llm_ok = {"causeA": {"name": "A 产品线采购成本", "value": "999%"}, "causeB": {"name": "供应商 B", "value": "任意"},
             "next": ["第一步", "第二步", "第三步"]}
    merged = _merge_with_numeric_stability(base, llm_ok)
    assert merged["causeA"]["value"] == "较期初 2.2%" and merged["causeB"]["value"] == "高 10.9%", \
        "LLM must not change numeric values"
    assert merged["causeA"]["name"] == "A 产品线采购成本" and merged["next"] == llm_ok["next"]
    llm_bad_next = {"next": "not-a-list"}
    merged2 = _merge_with_numeric_stability(base, llm_bad_next)
    assert merged2["next"] == base["next"], "invalid next must fall back to template"

    # T2：语义缓存合并与来源标注
    repo = Repository()
    repo.delete_all_reasoning()
    before = {i["id"]: i["semantics"] for i in res["insights"]}
    for i in res["insights"]:
        assert i["reasonSource"] == "template", "no-cache should mark reasonSource=template"
        assert "generatedAt" not in i
    refresh(repo, res["insights"], res["snapshot"])
    res2 = run_engine()
    for i in res2["insights"]:
        assert i["reasonSource"] == "template"  # 默认 provider 即 template
        assert "generatedAt" in i, "cache hit should carry generatedAt"
        assert i["semantics"] == before[i["id"]], f"cache must not change semantics for {i['id']}"
    repo.delete_all_reasoning()
    res3 = run_engine()
    for i in res3["insights"]:
        assert i["reasonSource"] == "template" and "generatedAt" not in i, "clear cache -> template again"

    print(f"reasoning_check OK (parity on {checked} insights; T2 cache merge OK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
