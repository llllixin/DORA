"""A07 isolated PG/HTTP gate. Validate both endpoints before any connection/write."""
from __future__ import annotations
import json,os,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/a07-verification'
MODULES=('query_contract_check','query_runtime_check','query_read_view_check','query_sources_check','query_metric_check',
         'query_integration_check','query_hardening_check','query_claim_check','query_api_check','query_evaluation_check')

def validate_environment(env=None):
    env=os.environ if env is None else env
    from tests.query_pg_check import require_disposable
    database=require_disposable(env);api=urlsplit(env.get('DORA_API_BASE',''))
    if not (api.scheme=='http' and api.hostname=='127.0.0.1' and api.port and api.path=='/api' and not api.query and not api.fragment and not api.username):
        raise ValueError('explicit loopback API /api required')
    return database,api.port

def main():
    database,port=validate_environment()
    # Never reuse somebody else's API even if it happens to answer /health.
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('A07 API port already occupied')
    env={**os.environ,'DATABASE_URL':database,'DORA_API_BASE':os.environ['DORA_API_BASE'],'DORA_A07_PG_CHECK':'1',
         'DORA_REASONING_PROVIDER':'template','DORA_LLM_API_KEY':'','DORA_RAG_EMBEDDING_PROVIDER':'hash',
         'DORA_RAG_ANSWER_PROVIDER':'template','DORA_RAG_OPENAI_API_KEY':'','OPENAI_API_KEY':'','DORA_MODEL_EXTERNAL_ENABLED':'false',
         'NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}
    OUT.mkdir(parents=True,exist_ok=True);checks=[];server=None;passed=False
    def run(name,command=None):
        cmd=command or [sys.executable,'-m',name]
        result=subprocess.run(cmd,cwd=ROOT/'backend',env=env,capture_output=True,text=True,timeout=600)
        logfile=OUT/(name.rsplit('.',1)[-1]+'.log');logfile.write_text(result.stdout+result.stderr)
        checks.append({'name':name,'exitCode':result.returncode,'log':str(logfile.relative_to(ROOT))})
        print(name,result.returncode,flush=True)
        if result.returncode:print((result.stdout+result.stderr)[-5500:],flush=True);raise RuntimeError('gate failed:'+name)
    try:
        run('app.seed')
        for module in MODULES:run('tests.'+module,[sys.executable,'-m','unittest','tests.'+module,'-v'])
        run('tests.query_pg_check',[sys.executable,'-m','unittest','tests.query_pg_check','-v'])
        # PG concurrency fixtures change values intentionally. Rebuild the canonical
        # disposable sample before original regression/HTTP acceptance.
        run('app.seed')
        with (OUT/'api.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=build_opener(ProxyHandler({}))
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('API exited before ready')
                try:
                    with opener.open(env['DORA_API_BASE']+'/health',timeout=1) as r:
                        if r.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('API readiness timeout')
            records=[]
            def curl(path,body=None,expected=200):
                cmd=['curl','--silent','--show-error','--max-time','45','-w','\n%{http_code}',env['DORA_API_BASE']+path]
                if body is not None:cmd+=['-H','Content-Type: application/json','--data-binary',json.dumps(body,ensure_ascii=False)]
                result=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=50)
                raw,status=result.stdout.rsplit('\n',1);value=json.loads(raw)
                records.append({'path':path,'httpStatus':int(status),'exitCode':result.returncode,'body':value})
                assert result.returncode==0 and int(status)==expected,(path,status,raw)
                return value
            search=curl('/query/search',{'query':'利润率是什么？'});assert search['hits']
            answer=curl('/query/answer',{'question':'最新全国利润率是多少？','includeSimulated':True})
            assert answer['status']=='answered' and answer['toolExecutions'][0]['tool']=='query_metric'
            assert answer['evidence'][0]['evidenceLevel']=='simulated'
            assert answer['claims'][0]['text'].startswith('【模拟】')
            evidence=curl(answer['citations'][0]['href'].removeprefix('/api'));assert evidence==answer['evidence'][0]
            composite=curl('/query/answer',{'question':'利润率是什么，最新全国是多少？','includeSimulated':True})
            matched=curl('/query/answer',{'question':'利润率是什么，最新全国是多少？','includeSimulated':True,
                'expectedDataRevision':composite['businessVersion']['dataRevision'],'expectedSourceRevision':composite['sourceRevision']})
            assert matched['status']=='answered'
            from sqlalchemy import create_engine,text
            engine=create_engine(database)
            try:
                with engine.begin() as c:c.execute(text('ALTER TABLE rag_index_projection RENAME TO a07_projection_hidden'))
                unavailable=curl('/query/answer',{'question':'利润率是什么？'},503)
                assert unavailable['detail']['runId']
                partial=curl('/query/answer',{'question':'利润率是什么，最新全国是多少？','includeSimulated':True})
                assert partial['status']=='partial' and 'definition' in partial['missingParts']
                retained=curl(answer['citations'][0]['href'].removeprefix('/api'));assert retained==answer['evidence'][0]
            finally:
                with engine.begin() as c:c.execute(text('ALTER TABLE a07_projection_hidden RENAME TO rag_index_projection'))
                engine.dispose()
            curl('/query/answer',{'question':'最新全国利润率是多少？','expectedDataRevision':'wrong'},409)
            curl('/query/answer',{'question':'利润率是什么？','expectedDataRevision':'wrong'},422)
            curl('/query/search',{'query':'利润率','scopeId':'other'},422)
            curl('/query/runs/absent/evidence/absent',expected=404)
            excluded=curl('/query/answer',{'question':'最新全国利润率是多少？'});assert not excluded['evidence']
            from sqlalchemy import select,delete,insert
            from app.models import BusinessRevision
            engine=create_engine(database)
            try:
                with engine.begin() as connection:
                    saved=dict(connection.execute(select(BusinessRevision)).mappings().one())
                    connection.execute(delete(BusinessRevision))
                try:
                    unavailable=curl('/query/answer',{'question':'最新全国利润率是多少？'},503)
                    assert unavailable['detail']['runId']
                finally:
                    with engine.begin() as connection:connection.execute(insert(BusinessRevision).values(**saved))
            finally:engine.dispose()
            old=curl('/rag/answer',{'question':'最新全国利润率是多少？'});assert old['status']=='tool_required'
            # Original metric/archive/Chat HTTP tests remain in tests.run_all.
            (OUT/'http-results.json').write_text(json.dumps({'realHTTP':True,'curl':True,'records':records},ensure_ascii=False,indent=2)+'\n')
            checks.append({'name':'real-http-and-curl','exitCode':0})
            run('tests.run_all')
        passed=True
    finally:
        if server:
            server.terminate()
            try:server.wait(timeout=8)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (OUT/'gate-results.json').write_text(json.dumps({'passed':passed,'checks':checks,'apiStopped':bool(server and server.poll() is not None),
            'database':'disposable dora_a07','externalModelCalls':0,'actualTokens':None,'actualCost':None},ensure_ascii=False,indent=2)+'\n')
    print('A07 isolated gate PASS',flush=True)

if __name__=='__main__':main()
