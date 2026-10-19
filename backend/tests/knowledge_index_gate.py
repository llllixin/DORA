"""A06 disposable PostgreSQL/HTTP gate. Refuse user DB before any seed/write."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/a06-verification'


def validate_environment(env=None):
    env=os.environ if env is None else env
    database=env.get('DATABASE_URL','');api=env.get('DORA_API_BASE','')
    u=urlsplit(database);a=urlsplit(api)
    if not (u.scheme=='postgresql+psycopg' and u.hostname=='127.0.0.1' and u.username=='dora_a06' and u.path=='/dora_a06' and u.port):
        raise RuntimeError('explicit disposable loopback dora_a06 database required')
    if not (a.scheme=='http' and a.hostname=='127.0.0.1' and a.port and a.path=='/api'):
        raise RuntimeError('explicit loopback API /api required')
    return database,a.port


def main():
    database,port=validate_environment();base=os.environ['DORA_API_BASE'];OUT.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'DATABASE_URL':database,'DORA_API_BASE':base,'DORA_MODEL_EXTERNAL_ENABLED':'false',
        'DORA_REASONING_PROVIDER':'template','DORA_LLM_API_KEY':'','DORA_RAG_EMBEDDING_PROVIDER':'hash',
        'DORA_RAG_ANSWER_PROVIDER':'template','DORA_RAG_OPENAI_API_KEY':'','OPENAI_API_KEY':'',
        'NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}
    checks=[];server=None
    def run(module):
        result=subprocess.run([sys.executable,'-m',module],cwd=ROOT/'backend',env=env,capture_output=True,text=True,timeout=300)
        (OUT/(module.rsplit('.',1)[-1]+'.log')).write_text(result.stdout+result.stderr)
        checks.append({'name':module,'exitCode':result.returncode});print(module,result.returncode,flush=True)
        if result.returncode:print((result.stdout+result.stderr)[-7000:],flush=True);raise RuntimeError('gate_failed:'+module)
    try:
        for module in ('app.seed','tests.knowledge_index_check','tests.knowledge_index_integration_check','tests.knowledge_index_evaluation_check','tests.runtime_deadline_pg_check','tests.knowledge_index_pg_check'):run(module)
        with (OUT/'api.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('API exited before ready')
                try:
                    with opener.open(base+'/health',timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('API readiness timeout')
            def request(path,body=None):
                req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,
                    headers={'Content-Type':'application/json'},method='POST' if body is not None else 'GET')
                with opener.open(req,timeout=120) as response:return json.loads(response.read())
            first=request('/rag/index',{});second=request('/rag/index',{})
            assert first['ok'] and second['ok'] and second['embeddedInputs']==0 and second['projectionCreated']==0
            assert second['usage']['externalModelCalls']==0 and second['usage']['totalTokens'] is None
            status=request('/rag/index/status');assert status['indexStatus']=='in_sync'
            search=request('/rag/search',{'query':'利润率口径'});assert search['hits'] and search['index']['indexStatus']=='in_sync'
            answer=request('/rag/answer',{'question':'利润率口径是什么'});assert answer['status']=='answered' and answer['citations']
            history=request('/rag/documents/metric-margin?version=1');assert history['document']['version']==1
            wiki=request('/wiki/cards');assert wiki['indexStatus']=='in_sync'
            report=request('/rag/evaluate',{});assert report['passed']
            runs=request('/agent/runs/'+second['runId']);assert not any(e.get('stage')=='index_embedding' for e in runs['run']['events'])
            curl=subprocess.run(['curl','--fail','--silent','--show-error',base+'/rag/index/status'],env=env,capture_output=True,text=True,timeout=10)
            (OUT/'curl-results.json').write_text(json.dumps({'exitCode':curl.returncode,'stdout':curl.stdout,'stderr':curl.stderr},ensure_ascii=False,indent=2)+'\n')
            assert curl.returncode==0 and json.loads(curl.stdout)['indexStatus']=='in_sync'
            (OUT/'http-results.json').write_text(json.dumps({'firstIndex':first,'secondIndex':second,'status':status,'search':search,'answer':answer,'history':history,'wikiStatus':wiki['indexStatus'],'evaluation':report},ensure_ascii=False,indent=2)+'\n')
            checks.append({'name':'real-HTTP-index-search-answer-history-status-wiki-evaluation-and-curl','exitCode':0})
            run('tests.run_all')
            # Restart the actual API against the same successful head. Startup must
            # create its audit run without issuing document embedding attempts.
            from sqlalchemy import create_engine,select
            from app.models import AgentRun
            engine=create_engine(database)
            def startup_runs():
                with engine.connect() as connection:
                    return {r.id:dict(r._mapping) for r in connection.execute(select(AgentRun.id,AgentRun.status,AgentRun.output,AgentRun.events).where(AgentRun.trigger=='model_rag-index'))}
            before=startup_runs();server.terminate();server.wait(timeout=8)
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('restarted API exited')
                try:
                    with opener.open(base+'/health',timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('restarted API readiness timeout')
            after=startup_runs();engine.dispose();created=[v for k,v in after.items() if k not in before]
            assert len(created)==1 and created[0]['status']=='done',created
            assert created[0]['output']['embeddedInputs']==0 and created[0]['output']['projectionCreated']==0
            assert not any(e.get('stage')=='index_embedding' for e in created[0]['events'])
            assert request('/rag/index/status')['indexStatus']=='in_sync'
            (OUT/'startup-results.json').write_text(json.dumps({'newRuns':created,'restarted':True},ensure_ascii=False,indent=2)+'\n')
            checks.append({'name':'real-API-restart-zero-document-embeddings','exitCode':0})
    finally:
        if server:
            server.terminate()
            try:server.wait(timeout=8)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (OUT/'gate-results.json').write_text(json.dumps({'checks':checks,'apiStopped':bool(server and server.poll() is not None),
            'database':'disposable dora_a06','externalModelCalls':0,'actualTokens':None,'actualCost':None},ensure_ascii=False,indent=2)+'\n')
    print('A06 isolated gate PASS',flush=True)


if __name__=='__main__':main()
