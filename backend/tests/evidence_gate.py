"""A05 dedicated PG, real HTTP, original full regression; no implicit DB fallback."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener,ProxyHandler
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/a05-verification'
MODULES=('evidence_contract_check','evidence_store_check','evidence_api_check','evidence_watch_check','evidence_action_check','evidence_retention_check')


def validate_environment(env=None):
    env=os.environ if env is None else env
    from tests.evidence_pg_check import require_disposable
    database=require_disposable(env);api=urlsplit(env.get('DORA_API_BASE',''))
    if not (api.scheme=='http' and api.hostname=='127.0.0.1' and api.port==8057 and api.path=='/api' and not api.query and not api.fragment and not api.username):raise ValueError('explicit A05 API http://127.0.0.1:8057/api required')
    return database,api.port


def safe_environment():
    return {**os.environ,'DORA_REASONING_PROVIDER':'template','DORA_LLM_API_KEY':'','DORA_RAG_EMBEDDING_PROVIDER':'hash',
        'DORA_RAG_ANSWER_PROVIDER':'template','DORA_RAG_OPENAI_API_KEY':'','OPENAI_API_KEY':'','DORA_MODEL_EXTERNAL_ENABLED':'false',
        'NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost','PYTHONDONTWRITEBYTECODE':'1'}


def main():
    database,port=validate_environment()
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('A05 API port occupied')
    env=safe_environment();os.environ.update(env);OUT.mkdir(parents=True,exist_ok=True);checks=[];server=None;passed=False
    def run(name,command=None):
        result=subprocess.run(command or [sys.executable,'-m',name],cwd=ROOT/'backend',env=env,capture_output=True,text=True,timeout=600)
        path=OUT/(name.rsplit('.',1)[-1]+'.log');path.write_text(result.stdout+result.stderr)
        checks.append(dict(name=name,exitCode=result.returncode,log=str(path.relative_to(ROOT))))
        print(name,result.returncode,flush=True)
        if result.returncode:print((result.stdout+result.stderr)[-7000:],flush=True);raise RuntimeError('gate failed: '+name)
    try:
        # This URL has already passed the exact isolated DB/user/port guard.
        # Repeated gate runs start clean; no user data or mounted volume exists.
        from sqlalchemy import create_engine,text
        clean=create_engine(database)
        try:
            with clean.begin() as c:
                c.execute(text('DROP SCHEMA public CASCADE'));c.execute(text('CREATE SCHEMA public'))
        finally:clean.dispose()
        run('app.seed')
        for name in MODULES:run('tests.'+name)
        run('tests.evidence_pg_check')
        run('app.seed')
        with (OUT/'api.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=build_opener(ProxyHandler({}))
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('A05 API exited')
                try:
                    with opener.open(env['DORA_API_BASE']+'/health',timeout=1) as r:
                        if r.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('A05 API not ready')
            records=[]
            def curl(path,body=None,expected=200,method=None):
                cmd=['curl','--silent','--show-error','--noproxy','*','--max-time','20','-w','\n%{http_code}',env['DORA_API_BASE']+path]
                if method:cmd+=['-X',method]
                if body is not None:cmd+=['-H','Content-Type: application/json','--data-binary',json.dumps(body,ensure_ascii=False)]
                r=subprocess.run(cmd,env=env,capture_output=True,text=True,timeout=25)
                raw,status=r.stdout.rsplit('\n',1);value=json.loads(raw);records.append(dict(path=path,status=int(status),body=value))
                assert r.returncode==0 and int(status)==expected,(path,status,raw)
                return value
            version=curl('/business/version');opened=curl('/history/action-cases',dict(insightTypeId='p1',expectedRevision=version['revision']))
            cid=opened['case']['id'];binding=opened['openingBinding'];snap=curl('/history/snapshots/'+binding['snapshotId'])['snapshot']
            assert curl('/history/bindings/'+binding['bindingId'])['binding']==binding
            assert curl('/history/action-cases/'+cid)['history']['opening']==binding
            assert curl('/insights/p1')['id']=='p1';curl('/evidence/p1?revision='+version['revision'])
            curl('/history/action-cases',dict(insightTypeId='p1',expectedRevision='stale'),409)
            curl('/history/action-cases',dict(insightTypeId='p1',expectedRevision=version['revision'],sourceWatchBindingId='absent'),409)
            # Create a real captured Watch in this same explicit PG, then read via HTTP.
            from app.watch.evaluator import evaluate_one
            from app.repository import Repository
            repo=Repository();target=repo.create_watch_target('HTTP fixture',dict(metric_key='margin',condition=dict(type='below',ref=100)))
            event=evaluate_one(repo,target)['event'];assert curl('/history/watch-events/'+event['bindingId'])['event']['snapshotId']
            repo.delete_watch_target(target['id']);assert curl('/history/watch-events/'+event['bindingId'])['event']['sourceStatus']=='deleted'
            from sqlalchemy import create_engine,text
            engine=create_engine(database)
            try:
                with engine.begin() as c:c.execute(text('UPDATE evidence_snapshot SET payload_hash=:bad WHERE snapshot_id=:id'),dict(bad='corrupt',id=snap['snapshotId']))
                curl('/history/snapshots/'+snap['snapshotId'],expected=409)
                with engine.begin() as c:c.execute(text('UPDATE evidence_snapshot SET payload_hash=:sha WHERE snapshot_id=:id'),dict(sha=snap['payloadHash'],id=snap['snapshotId']))
                with engine.begin() as c:c.execute(text('ALTER TABLE evidence_binding RENAME TO a05_binding_hidden'))
                curl('/history/bindings/'+binding['bindingId'],expected=503)
                with engine.begin() as c:c.execute(text('ALTER TABLE a05_binding_hidden RENAME TO evidence_binding'))
                curl('/history/snapshots/absent',expected=404)
            finally:engine.dispose()
            (OUT/'http-results.json').write_text(json.dumps(dict(realHTTP=True,curl=True,records=records),ensure_ascii=False,indent=2)+'\n')
            checks.append(dict(name='real-http-curl',exitCode=0))
            repo.delete_action_case(cid)
            for name in ('tests.boundary_check','tests.action_atomic_check','tests.run_all'):run(name)
        passed=True
    finally:
        if server:
            server.terminate()
            try:server.wait(8)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (OUT/'gate-results.json').write_text(json.dumps(dict(passed=passed,checks=checks,apiStopped=bool(server and server.poll() is not None),database='disposable dora_a05',externalModelCalls=0,actualTokens=None,actualCost=None),ensure_ascii=False,indent=2)+'\n')
    print('A05 isolated gate PASS',flush=True)


if __name__=='__main__':main()
