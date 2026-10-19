"""A04 disposable PostgreSQL/HTTP gate; refuses implicit or non-test database."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'output/a04-verification'


def main():
    database = os.environ.get('DATABASE_URL', ''); base = os.environ.get('DORA_API_BASE', '')
    u, api = urlsplit(database), urlsplit(base)
    if not (u.scheme=='postgresql+psycopg' and u.hostname=='127.0.0.1' and u.username=='dora_a04' and u.path=='/dora_a04' and u.port):
        raise RuntimeError('explicit disposable loopback dora_a04 database required')
    if not (api.scheme=='http' and api.hostname=='127.0.0.1' and api.port and api.path=='/api'):
        raise RuntimeError('explicit loopback API required')
    env = {**os.environ, 'DATABASE_URL':database, 'DORA_API_BASE':base, 'DORA_MODEL_EXTERNAL_ENABLED':'false',
           'DORA_REASONING_PROVIDER':'template', 'DORA_LLM_API_KEY':'', 'DORA_RAG_EMBEDDING_PROVIDER':'hash',
           'DORA_RAG_ANSWER_PROVIDER':'template', 'DORA_RAG_OPENAI_API_KEY':'', 'OPENAI_API_KEY':'',
           'NO_PROXY':'127.0.0.1,localhost', 'no_proxy':'127.0.0.1,localhost'}
    os.environ.update(env)
    OUT.mkdir(parents=True, exist_ok=True); checks=[]; server=None
    def run(module):
        result=subprocess.run([sys.executable,'-m',module],cwd=ROOT/'backend',env=env,capture_output=True,text=True,timeout=240)
        (OUT/(module.rsplit('.',1)[-1]+'.log')).write_text(result.stdout+result.stderr)
        checks.append({'name':module,'exitCode':result.returncode})
        print(module, 'PASS' if not result.returncode else 'FAIL',flush=True)
        if result.returncode:
            print((result.stdout+result.stderr)[-6500:],flush=True)
            raise RuntimeError('gate_failed:'+module)
    run('app.seed')
    with (OUT/'api.log').open('w') as log:
        try:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(api.port)],
                    cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(100):
                if server.poll() is not None: raise RuntimeError('A04 API exited before ready')
                try:
                    with opener.open(base+'/health',timeout=1) as response:
                        if response.status==200: break
                except OSError: time.sleep(.1)
            else: raise RuntimeError('A04 API not ready')
            def post(path,body):
                req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
                with opener.open(req,timeout=40) as response:return json.loads(response.read())
            def get(path):
                with opener.open(base+path,timeout=10) as response:return json.loads(response.read())
            index=post('/rag/index',{})
            assert index['ok'] and index['usage']['externalModelCalls']==0 and index['usage']['totalTokens'] is None
            answer=post('/rag/answer',{'question':'利润率的项目口径是什么'})
            assert answer['status']=='answered' and answer['citations'] and answer['runId']==answer['run_id']
            assert answer['usage']['externalModelCalls']==0 and answer['usage']['measurementStatus']=='unknown'
            stored=get('/agent/runs/'+answer['runId'])['run']
            assert stored['output']['usage']==answer['usage']
            assert any(e['type']=='model_attempt' for e in stored['events'])
            search=post('/rag/search',{'query':'利润率口径'})
            assert search['hits'] and search['usage']['externalModelCalls']==0
            refresh=post('/reason/refresh',{})
            assert refresh['ok'] and refresh['usage']['externalModelCalls']==0 and refresh['budget']['pendingAttempts']==0
            checks.append({'name':'real-http-index-answer-search-refresh-and-run-record','exitCode':0})
            # Real concurrent PostgreSQL transactions must not overwrite event arrays.
            from app.repository import Repository
            repo=Repository(); row=repo.create_agent_run(status='running')
            def append(i): repo.append_agent_run_event(row['id'],{'type':'a04-concurrency','seq':i})
            with ThreadPoolExecutor(8) as pool:list(pool.map(append,range(40)))
            final=repo.get_agent_run(row['id'])
            assert len(final['events'])==40 and {e['seq'] for e in final['events']}==set(range(40))
            before=repo.create_agent_run(events=[{'type':'legacy'}],output={'answer':'old'})
            assert repo.get_agent_run(before['id'])==before
            checks.append({'name':'pg-concurrent-40-events-and-legacy-retention','exitCode':0})
            for module in ['tests.model_runtime_check','tests.model_runtime_integration_check','tests.agent_loop_check','tests.run_all','tests.check_docs']:
                run(module)
            (OUT/'http-results.json').write_text(json.dumps({'index':index,'answer':answer,'search':search,'refresh':refresh},ensure_ascii=False,indent=2)+'\n')
            print('A04 isolated PostgreSQL/HTTP gate: PASS',flush=True)
        finally:
            if server is not None:
                server.terminate()
                try:server.wait(timeout=8)
                except subprocess.TimeoutExpired:server.kill();server.wait()
            (OUT/'gate-results.json').write_text(json.dumps({'checks':checks,'apiStopped':server is not None and server.poll() is not None,
                'database':'disposable dora_a04','externalModelCalls':0,'paidProviderTransport':'mock only'},ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
