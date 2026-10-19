"""Guarded one-shot verification for the eight selected cross-module repairs."""
import json,os,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,ProxyHandler
from tests.repair_pg_check import require_disposable
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'output/p2-boundaries-2026-10-18'

def validate_environment(env=None):
    env=os.environ if env is None else env
    database=require_disposable(env);api=urlsplit(env.get('DORA_API_BASE',''))
    if not(api.scheme=='http' and api.hostname=='127.0.0.1' and api.port==8060 and api.path=='/api' and not api.query and not api.fragment and not api.username):
        raise ValueError('explicit isolated API http://127.0.0.1:8060/api required')
    return database,8060

def main():
    database,port=validate_environment()
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',port))==0:raise RuntimeError('repair API port already occupied')
    env={**os.environ,'DORA_REASONING_PROVIDER':'template','DORA_LLM_API_KEY':'','OPENAI_API_KEY':'',
         'DORA_RAG_OPENAI_API_KEY':'','DORA_RAG_EMBEDDING_PROVIDER':'hash','DORA_RAG_ANSWER_PROVIDER':'template',
         'DORA_MODEL_EXTERNAL_ENABLED':'false','DORA_GRAPH_ENABLED':'true','NO_PROXY':'127.0.0.1,localhost','no_proxy':'127.0.0.1,localhost'}
    os.environ.update(env);OUT.mkdir(parents=True,exist_ok=True);checks=[];passed=False;server=None
    def run(name,command=None,cwd=None):
        r=subprocess.run(command or [sys.executable,'-m',name],cwd=cwd or ROOT/'backend',env=env,capture_output=True,text=True,timeout=600)
        path=OUT/(name.rsplit('.',1)[-1]+'.log');path.write_text(r.stdout+r.stderr)
        checks.append(dict(name=name,exitCode=r.returncode,log=str(path.relative_to(ROOT))))
        print(name,r.returncode,flush=True)
        if r.returncode:
            print((r.stdout+r.stderr)[-6000:],flush=True);raise RuntimeError('repair gate failed: '+name)
    try:
        run('tests.repair_pg_check');run('app.seed')
        with (OUT/'api.log').open('w') as log:
            server=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT/'backend',env=env,stdout=log,stderr=subprocess.STDOUT)
            opener=build_opener(ProxyHandler({}));base=env['DORA_API_BASE']
            for _ in range(150):
                if server.poll() is not None:raise RuntimeError('repair API exited')
                try:
                    with opener.open(base+'/health',timeout=1) as r:
                        if r.status==200:break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('repair API not ready')
            records=[]
            def request(path,payload=None):
                req=Request(base+path,data=json.dumps(payload,ensure_ascii=False).encode() if payload else None,headers={'Content-Type':'application/json'})
                with opener.open(req,timeout=20) as r:value=json.load(r);records.append(dict(path=path,status=r.status));return value
            before=request('/business/version');request('/wiki/cards');answer=request('/query/answer',{'question':'最新全国利润率是多少？'})
            assert answer['status']!='limited',answer
            from tests.repair_capacity_check import CapacityRepairChecks
            data=CapacityRepairChecks().csv(12000);csv_path=OUT/'oversized.csv';csv_path.write_bytes(data)
            command=['curl','--silent','--show-error','--noproxy','*','--max-time','20','--form','file=@'+str(csv_path),'-w','\n%{http_code}',base+'/datasets']
            result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=25);body,status=result.stdout.rsplit('\n',1)
            assert result.returncode==0 and status=='413',(status,body)
            assert request('/business/version')==before
            records.append(dict(path='/datasets',status=413,bytes=len(data),unchangedVersion=True,body=json.loads(body)))
            (OUT/'http-results.json').write_text(json.dumps(dict(realHTTP=True,records=records),ensure_ascii=False,indent=2))
            checks.append(dict(name='real-http-boundaries',exitCode=0))
            for name in ('tests.boundary_check','tests.action_atomic_check','tests.run_all','tests.check_docs'):run(name)
            run('frontend-build',['npm','run','build'],ROOT/'frontend')
        passed=True
    finally:
        if server:
            server.terminate()
            try:server.wait(8)
            except subprocess.TimeoutExpired:server.kill();server.wait()
        (OUT/'gate-results.json').write_text(json.dumps(dict(passed=passed,checks=checks,apiStopped=bool(server and server.poll() is not None),database='dora_repair:55460',externalModelCalls=0),ensure_ascii=False,indent=2))
    print('eight-fix isolated gate PASS',flush=True)

if __name__=='__main__':main()
