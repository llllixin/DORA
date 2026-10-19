"""隔离验收入口：仅连接本任务测试容器，启动独立 API，结束后关闭子进程。
python -m tests.fullstack_gate [--backend-only|--browser-only|--write-golden]
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
ART=ROOT/'tools/cdp/.artifacts'
# 专属容器映射，不读取开发 .env，不允许无意连现有库。
URL='postgresql+psycopg://dora_test:dora_test@127.0.0.1:55439/dora_test'
BASE='http://127.0.0.1:8041/api'
ENV={**os.environ,'DATABASE_URL':URL,'DORA_API_BASE':BASE,'DORA_REASONING_PROVIDER':'template','DORA_LLM_API_KEY':'','DORA_RAG_ANSWER_PROVIDER':'template','DORA_RAG_EMBEDDING_PROVIDER':'hash','DORA_RAG_OPENAI_API_KEY':'','NO_PROXY':'localhost,127.0.0.1','no_proxy':'localhost,127.0.0.1'}

def run(args, cwd=ROOT/'backend'):
    result=subprocess.run(args,cwd=cwd,env=ENV)
    if result.returncode: raise SystemExit(result.returncode)

def main():
    ART.mkdir(exist_ok=True)
    run([sys.executable,'-m','app.seed'])
    if '--write-golden' in sys.argv:
        run([sys.executable,'-m','tests.golden_check','--write']); return
    with (ART/'test-api.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8041'],cwd=ROOT/'backend',env=ENV,stdout=log,stderr=subprocess.STDOUT)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(80):
                if server.poll() is not None: raise RuntimeError('独立测试 API 启动失败，请查看 test-api.log')
                try:
                    with opener.open(BASE+'/health',timeout=1) as res:
                        if res.status==200: break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('测试 API 未就绪')
            if '--browser-only' not in sys.argv:
                run([sys.executable,'-m','tests.boundary_check'])
                run([sys.executable,'-m','tests.action_atomic_check'])
                run([sys.executable,'-m','tests.run_all'])
            if '--backend-only' not in sys.argv:
                run([sys.executable,'-m','app.seed'])
                run(['node','tools/cdp/run_all.mjs'],ROOT)
            print('隔离验收通过；测试 API 已计划关闭，数据库仅为 dora_test。')
        finally:
            server.terminate()
            try: server.wait(timeout=8)
            except subprocess.TimeoutExpired: server.kill(); server.wait()

if __name__=='__main__':main()
