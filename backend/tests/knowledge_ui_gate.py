"""A08 one-shot local/full gate. Default is help; full owns every resource it creates."""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]
OUTPUT_ROOT=ROOT/'tmp/a06-a08-2026-10-18/full'
DATABASE_URL='postgresql+psycopg://dora_a08:dora_a08@127.0.0.1:55458/dora_a08'
A06_DATABASE_URL='postgresql+psycopg://dora_a06:dora_a06@127.0.0.1:55458/dora_a06'
OWNER_LABEL='dev.dora.knowledge-ui-gate.owner'
IMAGE='postgres:16'
DEFAULTS={'DATABASE_URL':DATABASE_URL,'DORA_API_BASE':'http://127.0.0.1:8088/api',
    'DORA_UI_BASE':'http://127.0.0.1:5188','DORA_MODEL_EXTERNAL_ENABLED':'false',
    'DORA_REASONING_PROVIDER':'template','DORA_RAG_ANSWER_PROVIDER':'template',
    'DORA_RAG_EMBEDDING_PROVIDER':'hash','VITE_API_BASE_URL':'/api','VITE_API_MODE':'http','VITE_PROXY_TARGET':'http://127.0.0.1:8088'}
KEYS=('DORA_LLM_API_KEY','DORA_RAG_OPENAI_API_KEY','OPENAI_API_KEY')
LOCAL_MODULES=('wiki_catalog_check','knowledge_ui_gate_check')
HTTP_MODULES=('agent_check','e2e_api_check','action_check','watch_check','rag_check')
CDP_SCRIPTS=('knowledge_entry_fault_check.mjs','knowledge_entry_check.mjs')


def validate_environment(env=None):
    env=os.environ if env is None else env
    if any(key.startswith('PG') and value for key,value in env.items()):raise ValueError('inherited libpq PG configuration is not permitted in disposable gate')
    for key,value in DEFAULTS.items():
        if env.get(key)!=value:raise ValueError(f'A08 gate requires exact {key}={value}')
    return DATABASE_URL,8088,5188


def safe_environment(source=None):
    source=dict(os.environ if source is None else source)
    result={**DEFAULTS,**source}
    validate_environment(result)
    for key in KEYS:result[key]=''
    result.update(NO_PROXY='127.0.0.1,localhost',no_proxy='127.0.0.1,localhost',DORA_GRAPH_ENABLED='true')
    return result


def assert_ports_free(ports=(55458,8088,5188)):
    for port in ports:
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',port))
            except OSError as exc:raise RuntimeError(f'A08 port {port} occupied or unavailable') from exc


def validate_container(info,owner,*,image=IMAGE):
    config=info.get('Config') or {};host=info.get('HostConfig') or {}
    expected={'5432/tcp':[{'HostIp':'127.0.0.1','HostPort':'55458'}]}
    mounts=info.get('Mounts') or []
    if not(re.fullmatch('[a-f0-9]{64}',info.get('Id','')) and config.get('Image')==image
           and (config.get('Labels') or {}).get(OWNER_LABEL)==owner and host.get('AutoRemove') is True
           and not host.get('Binds') and host.get('NetworkMode') in ('bridge','default')
           and host.get('PortBindings')==expected
           and set(host.get('Tmpfs') or {})=={'/var/lib/postgresql/data'}
           and all(m.get('Type')=='tmpfs' and m.get('Destination')=='/var/lib/postgresql/data' for m in mounts)):
        raise ValueError('A08 container must be this run owner, exact loopback port, --rm, and tmpfs without user mounts')
    return info['Id']


def audit_http_targets():
    """Current legacy HTTP tests already expose DORA_API_BASE; reject regressions to hardcoded calls."""
    report={}
    for name in HTTP_MODULES:
        path=ROOT/'backend/tests'/f'{name}.py';tree=ast.parse(path.read_text())
        parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
        count=0
        for node in ast.walk(tree):
            if not isinstance(node,ast.Constant) or not isinstance(node.value,str):continue
            if not re.fullmatch(r'http://(?:localhost|127\.0\.0\.1):8000/api',node.value):continue
            parent=parents.get(node)
            if not(isinstance(parent,ast.Call) and isinstance(parent.func,ast.Attribute)
                   and parent.func.attr=='get' and parent.args and isinstance(parent.args[0],ast.Constant)
                   and parent.args[0].value=='DORA_API_BASE'):
                raise ValueError(f'uncontrolled :8000 HTTP URL in {path.name}:{node.lineno}')
            count+=1
        if not count:raise ValueError(f'legacy HTTP base no longer statically verified: {name}')
        report[name]={'guardedURLs':count,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    return report


def source_hashes():
    roots=[ROOT/'backend/app',ROOT/'backend/tests',ROOT/'frontend/src',ROOT/'frontend/scripts',ROOT/'tools/cdp']
    return {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
            for base in roots for path in sorted(base.rglob('*'))
            if path.is_file() and path.suffix in ('.py','.ts','.tsx','.css','.mjs') and '.artifacts' not in path.parts}


class Evidence:
    def __init__(self,out,env):
        self.out=out;self.env=env;self.steps=[];out.mkdir(parents=True,exist_ok=False)
    def run(self,name,command,*,cwd=None,env=None,timeout=600,allow_failure=False):
        number=len(self.steps)+1;log=self.out/f'{number:03d}-{name}.log';started=time.monotonic()
        record={'name':name,'command':list(command),'cwd':str(cwd or ROOT/'backend'),'log':str(log.relative_to(ROOT))}
        self.steps.append(record)
        proc=None
        try:
            proc=subprocess.Popen(command,cwd=cwd or ROOT/'backend',env=env or self.env,
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            stdout,stderr=proc.communicate(timeout=timeout)
            result=subprocess.CompletedProcess(command,proc.returncode,stdout,stderr)
            log.write_text(stdout+stderr);record['exitCode']=result.returncode
        except BaseException as exc:
            if proc is not None:
                stop_service(name,proc)
                stdout,stderr=proc.communicate();log.write_text(stdout+stderr)
            record['exitCode']='timeout' if isinstance(exc,subprocess.TimeoutExpired) else 'interrupted'
            raise
        finally:record['elapsedMs']=round((time.monotonic()-started)*1000,2)
        print(f'{name}: {result.returncode}',flush=True)
        if result.returncode and not allow_failure:raise RuntimeError(f'A08 gate failed: {name}; see {log}')
        return result
    def module(self,name,*,env=None):return self.run(name,[sys.executable,'-m',name],env=env)
    def unittest(self,*names,env=None):
        return self.run('unittest-'+'-'.join(names),[sys.executable,'-m','unittest',*['tests.'+n for n in names],'-v'],env=env)


def local_checks(evidence):
    evidence.unittest(*LOCAL_MODULES)
    evidence.run('query-client',['node','scripts/query-client-check.mjs'],cwd=ROOT/'frontend')


def wait_http(url,proc,timeout=45):
    opener=build_opener(ProxyHandler({}));end=time.monotonic()+timeout
    while time.monotonic()<end:
        if proc.poll() is not None:raise RuntimeError(f'owned service {proc.pid} exited before ready')
        try:
            with opener.open(url,timeout=1) as response:
                if response.status==200:return
        except OSError:time.sleep(.1)
    raise RuntimeError(f'owned service readiness timeout: {url}')


def launch(evidence,name,command,cwd,services):
    log=(evidence.out/f'{name}.log').open('w')
    try:proc=subprocess.Popen(command,cwd=cwd,env=evidence.env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    finally:log.close()
    services.append((name,proc))
    evidence.steps.append({'name':name,'command':list(command),'cwd':str(cwd),'pid':proc.pid,
        'log':str((evidence.out/f'{name}.log').relative_to(ROOT)),'exitCode':'running'})
    return proc


def stop_service(name,proc):
    # start_new_session makes this process group exclusively ours, including Vite's npm child.
    try:os.killpg(proc.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        proc.wait(timeout=5)
    return {'name':name,'pid':proc.pid,'stopped':proc.poll() is not None,'returnCode':proc.returncode}


def real_http_checks(evidence):
    target=evidence.out/'real-http';target.mkdir()
    records=[]
    def curl(name,path,body=None,expected=200):
        command=['curl','--silent','--show-error','--noproxy','*','--max-time','45','-w','\n%{http_code}',evidence.env['DORA_API_BASE']+path]
        if body is not None:command+=['-H','Content-Type: application/json','--data-binary',json.dumps(body,ensure_ascii=False)]
        result=evidence.run('http-'+name,command,timeout=50)
        raw,status=result.stdout.rsplit('\n',1);packet=json.loads(raw)
        (target/(name+'.json')).write_text(json.dumps({'path':path,'input':body,'status':int(status),'response':packet},ensure_ascii=False,indent=2))
        records.append({'name':name,'path':path,'status':int(status)})
        if int(status)!=expected:raise AssertionError((name,status,packet))
        return packet
    curl('search','/query/search',{'query':'利润率是什么？'})
    definition=curl('definition','/query/answer',{'question':'利润率是什么？'})
    for name,question,simulated in [('current','最新全国利润率是多少？',True),('reported','利润率有哪些历史处理记录？',False),
                                    ('no-data','ZXQUNKNOWN不存在资料是什么？',False),('today','今天全国利润率是多少？',True),
                                    ('exclude-simulated','最新全国利润率是多少？',False)]:
        curl(name,'/query/answer',{'question':question,'includeSimulated':simulated})
    if not definition.get('citations'):raise AssertionError('real definition answer must have persisted evidence')
    citation=definition['citations'][0];href=citation.get('href','')
    if not href.startswith('/api/query/runs/'):raise AssertionError('unexpected evidence identity')
    curl('evidence',href.removeprefix('/api'))
    catalog=curl('catalog','/wiki/catalog')
    if not catalog['cards']:raise AssertionError('real catalog must have reviewed cards')
    card=catalog['cards'][0]
    curl('explicit-version',f"/wiki/cards/{quote(card['id'],safe='')}?version={card['version']}")
    curl('catalog-revision-conflict','/wiki/catalog?offset=20&expectedCatalogRevision=deliberately-stale',expected=409)
    curl('archive','/knowledge')
    (target/'results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))


def full_checks(evidence,owner):
    env=evidence.env;docker=shutil.which('docker')
    if not docker:raise RuntimeError('Docker required; no implicit installation or pull')
    required=[ROOT/'tools/cdp'/name for name in CDP_SCRIPTS]
    if any(not path.is_file() for path in required):raise RuntimeError('both production CDP scripts must exist before creating resources')
    for executable in ('node','npm','curl','openspec'):
        if not shutil.which(executable):raise RuntimeError(f'missing gate executable: {executable}')
    legacy=audit_http_targets();assert_ports_free()
    (evidence.out/'legacy-http-audit.json').write_text(json.dumps(legacy,indent=2))
    local_checks(evidence)
    evidence.run('frontend-build',['npm','run','build'],cwd=ROOT/'frontend')
    evidence.module('tests.check_docs')
    evidence.run('openspec-strict',['openspec','validate','knowledge-query-ui','--strict'],cwd=ROOT)
    listed=evidence.run('image-local-id',[docker,'image','ls','--no-trunc','--quiet','--filter','reference='+IMAGE],timeout=30)
    ids=listed.stdout.split()
    if len(ids)!=1 or not re.fullmatch(r'sha256:[a-f0-9]{64}',ids[0]):raise RuntimeError('exact one local PostgreSQL image required')
    image=ids[0]
    image_info=json.loads(evidence.run('image-preflight',[docker,'image','inspect',image],timeout=30).stdout)[0]
    if image_info.get('Id')!=image or IMAGE not in (image_info.get('RepoTags') or []):raise RuntimeError('local image identity/tag mismatch')
    assert_ports_free()
    name='dora-a08-gate-'+owner[-12:];container_id=None;services=[];cleanup=[];created=False
    try:
        previous=evidence.run('name-preflight',[docker,'container','inspect',name],timeout=30,allow_failure=True)
        if previous.returncode==0:raise RuntimeError('container name conflict; unknown container cannot be reused')
        command=[docker,'run','--detach','--rm','--pull=never','--name',name,'--label',OWNER_LABEL+'='+owner,
            '--tmpfs','/var/lib/postgresql/data:rw','-e','PGDATA=/var/lib/postgresql/data',
            '-e','POSTGRES_USER=dora_a08','-e','POSTGRES_PASSWORD=dora_a08','-e','POSTGRES_DB=dora_a08',
            '-p','127.0.0.1:55458:5432',image]
        created=True
        result=evidence.run('postgres-create',command,timeout=60);container_id=result.stdout.strip()
        inspect=evidence.run('postgres-inspect',[docker,'inspect',container_id],timeout=30)
        info=json.loads(inspect.stdout)[0];container_id=validate_container(info,owner,image=image)
        (evidence.out/'resources.json').write_text(json.dumps({'owner':owner,'containerId':container_id,'containerName':name,
            'database':DATABASE_URL,'a06Database':A06_DATABASE_URL,'interpreter':sys.executable,'pythonVersion':sys.version},indent=2))
        end=time.monotonic()+45
        while True:
            ready=evidence.run('postgres-ready',[docker,'exec',container_id,'pg_isready','-h','127.0.0.1','-U','dora_a08','-d','dora_a08'],timeout=5,allow_failure=True)
            if ready.returncode==0:break
            if time.monotonic()>end:raise RuntimeError('owned PostgreSQL readiness timeout')
            time.sleep(.2)
        for sql in ("CREATE ROLE dora_a06 LOGIN PASSWORD 'dora_a06'",'CREATE DATABASE dora_a06 OWNER dora_a06'):
            evidence.run('a06-create',[docker,'exec',container_id,'psql','-U','dora_a08','-d','postgres','-v','ON_ERROR_STOP=1','-c',sql],timeout=30)
        a06={**env,'DATABASE_URL':A06_DATABASE_URL}
        evidence.module('app.seed',env=a06)
        evidence.unittest('runtime_deadline_pg_check','knowledge_index_pg_check',env=a06)
        evidence.unittest('wiki_catalog_pg_check')
        evidence.module('app.seed')
        api_command=[sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8088']
        api=launch(evidence,'api',api_command,ROOT/'backend',services)
        wait_http(env['DORA_API_BASE']+'/health',api)
        for module in ('tests.boundary_check','tests.action_atomic_check','tests.run_all'):evidence.module(module)
        # Old regression checks intentionally mutate fixtures. Restart on a fresh canonical sample.
        cleanup.append(stop_service('api-before-ui',api));services.remove(('api',api))
        evidence.module('app.seed')
        api=launch(evidence,'api-for-ui',api_command,ROOT/'backend',services)
        wait_http(env['DORA_API_BASE']+'/health',api)
        real_http_checks(evidence)
        vite=launch(evidence,'vite',['npm','run','dev','--','--host','127.0.0.1','--port','5188','--strictPort'],ROOT/'frontend',services)
        wait_http(env['DORA_UI_BASE'],vite)
        for script in CDP_SCRIPTS:
            artifacts=ROOT/'tools/cdp/.artifacts'
            before={p:p.stat().st_mtime_ns for p in artifacts.rglob('*') if p.is_file()} if artifacts.exists() else {}
            try:evidence.run(script,['node','tools/cdp/'+script],cwd=ROOT,timeout=300)
            finally:
                destination=evidence.out/('cdp-'+script.removesuffix('.mjs'));destination.mkdir()
                for path in artifacts.rglob('*'):
                    if path.is_file() and before.get(path)!=path.stat().st_mtime_ns:
                        copy=destination/path.relative_to(artifacts);copy.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,copy)
    finally:
        for service,proc in reversed(services):
            try:cleanup.append(stop_service(service,proc))
            except Exception as exc:cleanup.append({'name':service,'pid':proc.pid,'stopped':False,'reason':repr(exc)})
        try:
            if created:
                # Lookup only our unique name; never stop anything unless its immutable identity and owner match.
                inspect=evidence.run('cleanup-inspect',[docker,'container','inspect',name],timeout=30,allow_failure=True)
                if inspect.returncode==0:
                    info=json.loads(inspect.stdout)[0]
                    if (info.get('Config',{}).get('Labels') or {}).get(OWNER_LABEL)!=owner:
                        cleanup.append({'container':name,'stopped':False,'reason':'owner mismatch; left untouched'})
                    elif container_id and info['Id']!=container_id:
                        cleanup.append({'container':name,'stopped':False,'reason':'identity mismatch; left untouched'})
                    else:
                        stopped=evidence.run('postgres-stop',[docker,'stop','--time','8',info['Id']],timeout=20,allow_failure=True)
                        cleanup.append({'container':name,'containerId':info['Id'],'stopped':stopped.returncode==0})
                else:cleanup.append({'container':name,'stopped':True,'alreadyAbsent':True})
        except Exception as exc:cleanup.append({'container':name,'stopped':False,'reason':repr(exc)})
        finally:(evidence.out/'cleanup.json').write_text(json.dumps(cleanup,indent=2))
        for step in evidence.steps:
            if step.get('exitCode')=='running':
                match=next((item for item in cleanup if item.get('pid')==step.get('pid')),None)
                if match:step['exitCode']=match.get('returnCode','cleanup_failed')
        if any(not item['stopped'] for item in cleanup):raise RuntimeError('owned resource cleanup incomplete; see cleanup.json')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--local-only',action='store_true');mode.add_argument('--full',action='store_true')
    args=parser.parse_args(argv)
    if not(args.local_only or args.full):parser.print_help();return 0
    env=safe_environment();owner='a08-'+uuid4().hex
    evidence=Evidence(OUTPUT_ROOT/owner,env);passed=False;error=None
    (evidence.out/'source-before.json').write_text(json.dumps(source_hashes(),indent=2))
    previous_sigterm=signal.getsignal(signal.SIGTERM)
    def terminate(signum,frame):raise KeyboardInterrupt('A08 gate terminated; cleaning owned resources')
    signal.signal(signal.SIGTERM,terminate)
    try:
        if args.local_only:local_checks(evidence)
        else:full_checks(evidence,owner)
        passed=True
    except BaseException as exc:error=repr(exc);raise
    finally:
        signal.signal(signal.SIGTERM,previous_sigterm)
        after=source_hashes();(evidence.out/'source-after.json').write_text(json.dumps(after,indent=2))
        (evidence.out/'gate-results.json').write_text(json.dumps({'passed':passed,'mode':'full' if args.full else 'local-only',
            'owner':owner,'interpreter':sys.executable,'error':error,'checks':evidence.steps,
            'environment':{key:env[key] for key in (*DEFAULTS,*KEYS)},'runAllGroups':len(__import__('tests.run_all',fromlist=['STEPS']).STEPS)},ensure_ascii=False,indent=2))
        print('Evidence: '+str(evidence.out),flush=True)
    return 0

if __name__=='__main__':raise SystemExit(main())
