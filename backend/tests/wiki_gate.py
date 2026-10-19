"""A02 isolated PostgreSQL + real HTTP gate. Requires explicit disposable DB URL.

DATABASE_URL=postgresql+psycopg://dora_a02:...@127.0.0.1:55450/dora_a02
DORA_API_BASE=http://127.0.0.1:8050/api python -m tests.ontology_gate
Only a local dora_a02 database is accepted; never falls back to backend/.env.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output/a02-verification"


def main():
    database = os.environ.get("DATABASE_URL", "")
    base = os.environ.get("DORA_API_BASE", "")
    db_url, api_url = urlsplit(database), urlsplit(base)
    if not (db_url.scheme == "postgresql+psycopg" and db_url.hostname == "127.0.0.1"
            and db_url.username == "dora_a02" and db_url.path == "/dora_a02" and db_url.port):
        raise RuntimeError("refusing non-disposable A02 database URL")
    if not (api_url.scheme == "http" and api_url.hostname == "127.0.0.1" and api_url.port and api_url.path == "/api"):
        raise RuntimeError("explicit loopback A02 API required")
    environment = {**os.environ, "DATABASE_URL": database, "DORA_API_BASE": base,
                   "DORA_REASONING_PROVIDER": "template", "DORA_LLM_API_KEY": "",
                   "DORA_RAG_ANSWER_PROVIDER": "template", "DORA_RAG_EMBEDDING_PROVIDER": "hash",
                   "DORA_RAG_OPENAI_API_KEY": "", "OPENAI_API_KEY": "",
                   "NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []

    def run(module):
        result = subprocess.run([sys.executable, "-m", module], cwd=ROOT / "backend", env=environment,
                                capture_output=True, text=True, timeout=180)
        (OUTPUT / (module.rsplit(".", 1)[-1] + ".log")).write_text(result.stdout + result.stderr)
        results.append({"module": module, "exitCode": result.returncode})
        print(module, "PASS" if result.returncode == 0 else "FAIL", flush=True)
        if result.returncode:
            print((result.stdout + result.stderr)[-5000:], flush=True)
            raise RuntimeError(f"gate failed: {module}")

    run("app.seed")
    server = None
    with (OUTPUT / "api.log").open("w") as log:
        try:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_url.port)],
                                      cwd=ROOT / "backend", env=environment, stdout=log, stderr=subprocess.STDOUT)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("A02 API failed to bind/start")
                try:
                    with opener.open(base + "/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("A02 API not ready")

            def post(path, value):
                request = urllib.request.Request(base + path, data=json.dumps(value).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with opener.open(request, timeout=10) as response:
                    return json.loads(response.read())

            live = post("/rag/answer", {"question": "最新华东订单量是多少"})
            assert live["status"] == "tool_required" and live["tool_args"] == {"metric_key": "east_orders", "dimension": "华东"}
            blocked = post("/rag/answer", {"question": "今天毛利率是多少"})
            assert blocked["status"] == "clarification_required" and blocked["citations"] == []
            for text, expected in [("关注华东订单量", True), ("关注华东销售额", False), ("关注大额订单占比", False)]:
                assert post("/watch/parse", {"text": text})["ok"] is expected
            with opener.open(base + "/rag/documents/metric-margin?version=1", timeout=10) as response:
                old = json.loads(response.read())
                assert old["document"]["version"] == 1
            # One old persisted intent remains byte-equivalent across new parsing.
            retention = subprocess.run([sys.executable, "-c", "from app.repository import Repository; from app.watch.parser import parse_watch_text; r=Repository(); t=r.create_watch_target('legacy-sales', {'metric_key':'east_orders','dimension':'华东','label':'华东销售额','condition':{'type':'below','ref':0}}, frequency='weekly'); before=r.get_watch_target(t['id']); assert not parse_watch_text('关注华东销售额')['ok']; assert r.get_watch_target(t['id'])==before; r.delete_watch_target(t['id']); print('legacy intent preserved')"], cwd=ROOT / "backend", env=environment, capture_output=True, text=True)
            assert retention.returncode == 0, retention.stderr
            results.append({"module": "A02-real-http-and-retention", "exitCode": 0})
            for module in ["tests.wiki_check", "tests.wiki_candidate_check", "tests.wiki_integration_check", "tests.wiki_pg_check", "tests.ontology_check", "tests.ontology_integration_check", "tests.boundary_check", "tests.action_atomic_check", "tests.run_all"]:
                run(module)
            print("A02 isolated PostgreSQL / HTTP gate passed", flush=True)
        finally:
            if server is not None:
                server.terminate()
                try:
                    server.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    server.kill(); server.wait()
            (OUTPUT / "gate-results.json").write_text(json.dumps({"results": results, "apiStopped": server is not None and server.poll() is not None,
                                                                  "database": "disposable dora_a02", "externalModelProfile": "hash/template"}, indent=2) + "\n")


if __name__ == "__main__":
    main()
