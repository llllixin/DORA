"""一键门禁：原 9 段业务检查 + A01 本体/消费者检查。

前置：PostgreSQL 运行且 seed 过；后端 API 在 :8000（agent_check 走 HTTP）。
运行：cd backend && python3 -m tests.run_all
B1（knowledge-lifecycle）：各 check 用与 run_all 相同的解释器（sys.executable），
避免 PATH 首位是无关 python3（如本机 homebrew 无 sqlalchemy，P012）。
"""
import os
import subprocess
import sys

STEPS = [
    ("knowledge_ui_local_check", [sys.executable,"-m","unittest","tests.wiki_catalog_check","tests.knowledge_ui_gate_check"]),
    ("cross_module_boundary_repair_check", [sys.executable,"-m","unittest",*["tests."+name for name in ("repair_provenance_check","repair_capacity_check","repair_read_admission_check","repair_knowledge_check","repair_graph_check","repair_runtime_check","repair_gate_guard_check")]]),
    ("business_graph_check", [sys.executable,"-m","unittest",*["tests."+name for name in ("graph_contract_check","graph_source_check","graph_projection_check","graph_store_check","graph_query_check","graph_api_check","graph_lifecycle_check","graph_gate_guard_check")]]),
    ("evidence_history_check", [sys.executable,"-m","unittest",*["tests."+name for name in ("evidence_contract_check","evidence_store_check","evidence_api_check","evidence_watch_check","evidence_action_check","evidence_retention_check","evidence_gate_guard_check")]]),
    ("unified_query_check", [sys.executable, "-m", "unittest", *["tests."+name for name in ("query_contract_check","query_runtime_check","query_read_view_check","query_sources_check","query_metric_check","query_integration_check","query_hardening_check","query_claim_check","query_api_check","query_evaluation_check")]]),
    ("knowledge_index_check", [sys.executable, "-m", "tests.knowledge_index_check"]),
    ("knowledge_index_integration_check", [sys.executable, "-m", "tests.knowledge_index_integration_check"]),
    ("knowledge_index_evaluation_check", [sys.executable, "-m", "tests.knowledge_index_evaluation_check"]),
    ("business_version_check", [sys.executable, "-m", "tests.business_version_check"]),
    ("business_store_check", [sys.executable, "-m", "tests.business_store_check"]),
    ("business_api_check", [sys.executable, "-m", "tests.business_api_check"]),
    ("model_runtime_check", [sys.executable, "-m", "tests.model_runtime_check"]),
    ("model_runtime_integration_check", [sys.executable, "-m", "tests.model_runtime_integration_check"]),
    ("wiki_check", [sys.executable, "-m", "tests.wiki_check"]),
    ("wiki_candidate_check", [sys.executable, "-m", "tests.wiki_candidate_check"]),
    ("wiki_integration_check", [sys.executable, "-m", "tests.wiki_integration_check"]),
    ("ontology_check", [sys.executable, "-m", "tests.ontology_check"]),
    ("ontology_integration_check", [sys.executable, "-m", "tests.ontology_integration_check"]),
    ("engine_check", [sys.executable, "-m", "tests.engine_check"]),
    ("ingest_check", [sys.executable, "-m", "tests.ingest_check"]),
    ("reasoning_check", [sys.executable, "-m", "tests.reasoning_check"]),
    ("golden_check", [sys.executable, "-m", "tests.golden_check"]),
    ("e2e_api_check", [sys.executable, "-m", "tests.e2e_api_check"]),
    ("watch_check", [sys.executable, "-m", "tests.watch_check"]),
    ("action_check", [sys.executable, "-m", "tests.action_check"]),
    ("agent_check", [sys.executable, "-m", "tests.agent_check"]),
    ("rag_check", [sys.executable, "-m", "tests.rag_check"]),
]


def main() -> int:
    failed = False
    # 钉死门禁环境：模板语义基线 + 空 key。开发者本地 .env（如 DORA_REASONING_PROVIDER=llm+真 key）
    # 不得影响 run_all 的确定性断言；llm 行为由 reasoning_check 内显式构造（resolve_provider('llm')/无 key fallback/mock 数值稳定）覆盖。
    gate_env = {
        **os.environ, "DORA_REASONING_PROVIDER": "template", "DORA_LLM_API_KEY": "",
        "DORA_RAG_ANSWER_PROVIDER": "template", "DORA_RAG_EMBEDDING_PROVIDER": "hash",
        "DORA_RAG_OPENAI_API_KEY": "", "OPENAI_API_KEY": "", "DORA_MODEL_EXTERNAL_ENABLED": "false",
    }
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
