"""A03 disposable PG/API gate. Explicit dora_a03 database and API base required."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "output/a03-verification"


def main():
    from tests.business_pg_check import require_disposable
    require_disposable()
    base = os.environ.get("DORA_API_BASE", "")
    api = urlsplit(base)
    if not (api.scheme == "http" and api.hostname == "127.0.0.1" and api.port and api.path == "/api"):
        raise RuntimeError("explicit loopback A03 API base required")
    environment = {**os.environ, "DORA_REASONING_PROVIDER": "template", "DORA_LLM_API_KEY": "",
                   "DORA_MODEL_EXTERNAL_ENABLED": "false", "DORA_RAG_ANSWER_PROVIDER": "template",
                   "DORA_RAG_EMBEDDING_PROVIDER": "hash", "DORA_RAG_OPENAI_API_KEY": "", "OPENAI_API_KEY": "",
                   "NO_PROXY": "localhost,127.0.0.1", "no_proxy": "localhost,127.0.0.1"}
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = []

    def run(module):
        result = subprocess.run([sys.executable, "-m", module], cwd=ROOT / "backend", env=environment,
                                capture_output=True, text=True, timeout=240)
        (OUTPUT / (module.rsplit(".", 1)[-1] + ".log")).write_text(result.stdout + result.stderr)
        results.append(dict(module=module, exitCode=result.returncode))
        print(module, "PASS" if result.returncode == 0 else "FAIL", flush=True)
        if result.returncode:
            print((result.stdout + result.stderr)[-7000:], flush=True)
            raise RuntimeError("A03 gate failed: " + module)

    server = None
    try:
        for module in ["app.seed", "tests.business_version_check", "tests.business_store_check", "tests.business_api_check", "tests.business_pg_check"]:
            run(module)
        with (OUTPUT / "api.log").open("w") as log:
            server = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api.port)],
                                      cwd=ROOT / "backend", env=environment, stdout=log, stderr=subprocess.STDOUT)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(100):
                if server.poll() is not None: raise RuntimeError("A03 API failed to start")
                try:
                    with opener.open(base + "/health", timeout=1) as response:
                        if response.status == 200: break
                except OSError: time.sleep(.1)
            else: raise RuntimeError("A03 API not ready")
            # Explicit real HTTP/curl evidence in addition to in-process API tests.
            def curl(path):
                result = subprocess.run(["curl", "--fail", "--silent", "--show-error", "--noproxy", "*", base + path], capture_output=True, text=True, timeout=15)
                if result.returncode: raise RuntimeError(result.stderr)
                return json.loads(result.stdout)
            version = curl("/business/version")
            assert version["versionStatus"] == "complete" and version["scopeId"] == "dora:default"
            detail = curl("/insights/p1")
            assert detail["businessVersion"]["revision"] == version["revision"]
            assert curl("/evidence/p1?revision=" + version["revision"])["occurrenceId"] == detail["occurrenceId"]
            (OUTPUT / "http-version.json").write_text(json.dumps(version, ensure_ascii=False, indent=2) + "\n")
            results.append(dict(module="real-http-curl-version-and-evidence", exitCode=0))
            for module in ["tests.boundary_check", "tests.action_atomic_check", "tests.run_all"]:
                run(module)
    finally:
        if server is not None:
            server.terminate()
            try: server.wait(8)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
        (OUTPUT / "gate-results.json").write_text(json.dumps(dict(results=results,
            apiStopped=server is not None and server.poll() is not None, database="disposable dora_a03",
            externalModelProfile="template/hash/fake; external disabled"), indent=2) + "\n")
    print("A03 isolated PG/HTTP gate passed", flush=True)


if __name__ == "__main__":
    main()
