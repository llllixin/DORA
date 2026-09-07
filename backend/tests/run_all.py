"""一键门禁（C5）：串联 engine_check + ingest_check + e2e_api_check。

前置：PostgreSQL 运行且 seed 过；后端 API 在 :8000。
运行：cd backend && python3 -m tests.run_all
"""
import os
import subprocess
import sys

STEPS = [
    ("engine_check", ["python3", "-m", "tests.engine_check"]),
    ("ingest_check", ["python3", "-m", "tests.ingest_check"]),
    ("reasoning_check", ["python3", "-m", "tests.reasoning_check"]),
    ("golden_check", ["python3", "-m", "tests.golden_check"]),
    ("e2e_api_check", ["python3", "-m", "tests.e2e_api_check"]),
    ("watch_check", ["python3", "-m", "tests.watch_check"]),
    ("action_check", ["python3", "-m", "tests.action_check"]),
]


def main() -> int:
    failed = False
    # 钉死门禁环境：模板语义基线 + 空 key。开发者本地 .env（如 DORA_REASONING_PROVIDER=llm+真 key）
    # 不得影响 run_all 的确定性断言；llm 行为由 reasoning_check 内显式构造（resolve_provider('llm')/无 key fallback/mock 数值稳定）覆盖。
    gate_env = {**os.environ, "DORA_REASONING_PROVIDER": "template", "DORA_LLM_API_KEY": ""}
    for name, cmd in STEPS:
        print(f"\n=== {name} ===")
        r = subprocess.run(cmd, capture_output=True, text=True, env=gate_env)
        print(r.stdout.strip() or (r.stderr.strip()[-1200:] if r.returncode else ""))
        if r.returncode != 0:
            failed = True
            print(r.stderr.strip()[-2000:] if r.stderr else "no stderr")
            print(f"--- {name} FAILED ---")
        else:
            print(f"--- {name} OK ---")
    print("\nrun_all:", "FAILED" if failed else "ALL GREEN")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
