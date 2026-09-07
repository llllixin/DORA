"""真实 LLM 冒烟（可选，不进 run_all）：配置了 DORA_LLM_API_KEY 才执行。

用法（在 backend/ 目录）：
  python3 -m tests.llm_real_smoke            # 无 key → skip(0)；有 key → 单条 + 全量 refresh
前置：PostgreSQL 已 seed、backend/.env（或 shell）提供 DORA_LLM_API_KEY/BASE_URL/MODEL。
"""
import os
import sys
import time

import app  # noqa: F401  触发 .env 加载


def main() -> int:
    if not (os.environ.get("DORA_LLM_API_KEY") or ""):
        print("llm_real_smoke SKIP（未配置 DORA_LLM_API_KEY，真实网络不进门禁）")
        return 0
    from app.engine.engine import run_engine
    from app.reasoning.cache import refresh
    from app.reasoning.provider import ReasoningContext, resolve_provider
    from app.repository import Repository
    from app.seed import run_seed

    run_seed()
    repo = Repository()
    res = run_engine(repo)
    snap = res["snapshot"]
    provider = resolve_provider("llm")

    # 单条：p1
    p1 = next(i for i in res["insights"] if i["id"] == "p1")
    t0 = time.time()
    out = provider.explain(ReasoningContext(
        insight_id=p1["id"], insight_type=p1["type"], metric=p1["metric"],
        delta=p1["delta"], trigger=p1["trigger"], factors=p1["factors"],
        question=p1["question"], snapshot=snap))
    assert out.provider == "llm" and out.semantics, "single llm explain failed"
    print(f"single p1 OK ({round(time.time() - t0, 1)}s): {out.semantics['causeA']['name']} / next x{len(out.semantics['next'])}")

    # 全量：9/9 updated，数值锁（value 与模板基线一致）
    repo.delete_all_reasoning()
    base = {i["id"]: i["semantics"] for i in res["insights"]}
    t0 = time.time()
    result = refresh(repo, res["insights"], snap, provider=provider)
    print(f"refresh {len(result['updated'])} updated / {len(result['fallback'])} fallback ({round(time.time() - t0, 1)}s)")
    assert len(result["updated"]) == len(res["insights"]) and not result["fallback"], "llm real refresh must update all"
    for i in res["insights"]:
        row = repo.get_reasoning(i["id"])
        sem = row["semantics"]
        assert sem["causeA"]["value"] == base[i["id"]]["causeA"]["value"]
        assert sem["causeB"]["value"] == base[i["id"]]["causeB"]["value"]
    repo.delete_all_reasoning()
    run_seed()
    print("llm_real_smoke OK（真实 DeepSeek：单条 + 全量 9/9，数值锁通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
