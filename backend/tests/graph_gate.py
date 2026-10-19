"""Guarded A09 PG/HTTP/full regression. Only the exact disposable DB is mutable."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener,ProxyHandler

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/a09-verification'
MODULES=('graph_contract_check','graph_source_check','graph_projection_check','graph_store_check',
         'graph_query_check','graph_api_check','graph_lifecycle_check','graph_gate_guard_check')


def validate_environment(env=None):
    env=os.environ if env is None else env
    from tests.graph_pg_check import require_disposable
    database=require_disposable(env);api=urlsplit(env.get('DORA_API_BASE',''))
    if not (api.scheme=='http' and api.hostname=='127.0.0.1' and api.port==8059 and api.path=='/api'
            and not api.query and not api.fragment and not api.username):
        raise ValueError('explicit A09 API http://127.0.0.1:8059/api required')
    return database,api.port


def main():
    database,port=validate_environment()
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('A09 port already occupied')
    env={**os.environ,'DORA_REASONING_PROVIDER':'template','DORA_LLM_API_KEY':'','OPENAI_API_KEY':'',
         'DORA_RAG_OPENAI_API_KEY':'','DORA_RAG_EMBEDDING_PROVIDER':'hash','DORA_RAG_ANSWER_PROVIDER':'template',
         'DORA_MODEL_EXTERNAL_ENABLED':'false','DORA_GRAPH_ENABLED':'true','NO_PROXY':'127.0.0.1,localhost',
         'no_proxy':'127.0.0.1,localhost','PYTHONDONTWRITEBYTECODE':'1'}
    os.environ.update(env);OUT.mkdir(parents=True,exist_ok=True);checks=[];passed=False;server=None
    def run(name,command=None,cwd=None):
        result=subprocess.run(command or [sys.executable,'-m',name],cwd=cwd or ROOT/'backend',env=env,
                              capture_output=True,text=True,timeout=600)
        path=OUT/(name.rsplit('.',1)[-1]+'.log');path.write_text(result.stdout+result.stderr)
        checks.append(dict(name=name,exitCode=result.returncode,log=str(path.relative_to(ROOT))))
        print(name,result.returncode,flush=True)
        if result.returncode:
            print((result.stdout+result.stderr)[-7000:],flush=True);raise RuntimeError('A09 gate failed: '+name)
    def reset():
        from sqlalchemy import create_engine,text
        engine=create_engine(database)
        try:
            with engine.begin() as c:c.execute(text('DROP SCHEMA public CASCADE'));c.execute(text('CREATE SCHEMA public'))
        finally:engine.dispose()
        run('app.seed')
    try:
        for module in MODULES:run('tests.'+module)
        run('tests.graph_pg_check');reset()
        with (OUT/'api.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],
                                    cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=build_opener(ProxyHandler({}))
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('A09 API exited')
                try:
                    with opener.open(env['DORA_API_BASE']+'/health',timeout=1) as response:
                        if response.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('A09 API not ready')
            records=[]
            def curl(path,body=None,expected=200):
                command=['curl','--silent','--show-error','--noproxy','*','--max-time','20','-w','\n%{http_code}',env['DORA_API_BASE']+path]
                if body is not None:command+=['-H','Content-Type: application/json','--data-binary',json.dumps(body,ensure_ascii=False)]
                result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=25)
                raw,status=result.stdout.rsplit('\n',1);value=json.loads(raw)
                records.append(dict(path=path,status=int(status),body=value))
                assert result.returncode==0 and int(status)==expected,(path,status,raw)
                return value
            assert not curl('/graph/status')['ready']
            version=curl('/business/version')
            opened=curl('/history/action-cases',dict(insightTypeId='p1',expectedRevision=version['revision']))
            from app.graph.service import GraphService
            from app.graph.models import GraphEntity,GraphRelationEvidence
            from app.repository import Repository
            from app import db
            from sqlalchemy import select,text
            service=GraphService();one=service.sync();two=service.sync();assert two['unchanged']
            with db.make_session() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='ActionCase' and n.data['attributes']['caseId']==opened['case']['id'])
            body=dict(entityId=root,includeSimulated=True,maxHops=2)
            value=curl('/graph/neighborhood',body);assert value['relations']
            edge=value['relations'][0]
            curl('/graph/relations/'+edge['id']+'/evidence?batchId='+one['batchId']+'&includeSimulated=true')
            curl('/graph/neighborhood',{**body,'expectedGraphRevision':'stale'},409)
            curl('/graph/neighborhood',{**body,'scopeId':'foreign'},422)
            curl('/graph/neighborhood',dict(entityId='unknown'),404)
            curl('/graph/neighborhood',{**body,'mode':'historical'},422)
            repo=Repository();repo.delete_action_case(opened['case']['id'])
            curl('/graph/neighborhood',body,404)
            historical=curl('/graph/neighborhood',{**body,'mode':'historical','batchId':one['batchId']})
            assert any(w['sourceCurrentStatus']=='deleted' for w in historical['evidence'])
            with db.get_engine().begin() as c:c.execute(text('ALTER TABLE graph_relation_evidence RENAME TO a09_evidence_hidden'))
            try:
                curl('/graph/status',expected=503)
                curl('/history/snapshots/'+opened['openingBinding']['snapshotId'])
            finally:
                with db.get_engine().begin() as c:c.execute(text('ALTER TABLE a09_evidence_hidden RENAME TO graph_relation_evidence'))
            (OUT/'http-results.json').write_text(json.dumps(dict(realHTTP=True,curl=True,records=records),ensure_ascii=False,indent=2)+'\n')
            checks.append(dict(name='real-http-curl',exitCode=0))
            run('app.seed')
            for name in ('tests.boundary_check','tests.action_atomic_check','tests.run_all'):run(name)
            run('frontend-build',['npm','run','build'],ROOT/'frontend')
        passed=True
    finally:
        if server:
            server.terminate()
            try:server.wait(8)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (OUT/'gate-results.json').write_text(json.dumps(dict(passed=passed,checks=checks,apiStopped=bool(server and server.poll() is not None),
            database='disposable dora_a09',externalModelCalls=0,actualTokens=None,actualCost=None),ensure_ascii=False,indent=2)+'\n')
    print('A09 isolated gate PASS',flush=True)


if __name__=='__main__':main()
