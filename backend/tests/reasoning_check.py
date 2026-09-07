"""V3-T1 reasoning 自检：抽象层 parity（模板 provider == 引擎默认语义）。

运行：cd backend && python3 -m tests.reasoning_check
前置：PostgreSQL 已 seed（本地 docker compose up -d 后 python -m app.seed）。
"""
import sys

from app.engine.engine import run_engine
from app.reasoning.cache import refresh
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
        resolve_provider("llm")
        raise AssertionError("unknown provider should raise")
    except ValueError:
        pass

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
