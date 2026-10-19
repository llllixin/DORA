"""A02 PostgreSQL/HTTP boundary checks; refuses all non-disposable URLs."""
import json,os,sys,tempfile,threading,urllib.request,urllib.error
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from sqlalchemy import event
from app import db
from app.models import ActionCase,ActionStep
from app.repository import Repository
from app.action import flow
from app.rag.contracts import RagContractError
from app.wiki.candidates import CandidateService


def main():
    u=urlsplit(os.environ.get('DATABASE_URL',''))
    assert u.hostname=='127.0.0.1' and u.username=='dora_a02' and u.path=='/dora_a02'
    base=os.environ['DORA_API_BASE'];api=urlsplit(base)
    assert api.hostname=='127.0.0.1' and api.scheme=='http' and api.path=='/api'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def get(path):
        with opener.open(base+path,timeout=15) as response:return json.loads(response.read())
    def post(path,body):
        req=urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        with opener.open(req,timeout=15) as response:return json.loads(response.read())
    def add_case(case_id):
        with db.make_session() as s:
            s.add(ActionCase(id=case_id,case_title='A02 PostgreSQL processing record',kind='problem',status='waiting_verify',origin='engine',created_at=datetime.now(timezone.utc).isoformat()))
            s.add(ActionStep(case_id=case_id,seq=0,title='completed test step',status='done'));s.commit()
    repo=Repository();svc=CandidateService();ids=['a02-pg-http','a02-pg-failure','a02-pg-concurrency','a02-pg-delete']
    for case_id in ids:repo.delete_action_case(case_id);add_case(case_id)
    def deletion_race():
        flow.verify(repo,'a02-pg-delete','resolved',note='delete race fixture')
        row=max((c for c in svc.list() if c['source_id']=='a02-pg-delete'),key=lambda c:c['revision'])
        svc.review(row['candidate_id'],actor='test:operator',reason='report only',decision='approve',base_version=0)
        case_locked=threading.Event();deletion_started=threading.Event();resume=threading.Event();archive_requested=threading.Event()
        def before(conn,cursor,statement,parameters,context,executemany):
            name=threading.current_thread().name
            if name.startswith('A02Delete') and ('FROM action_case' in statement and 'FOR UPDATE' in statement):
                deletion_started.set()
            if name.startswith('A02Publish') and 'FROM knowledge_archive' in statement and 'FOR UPDATE' in statement:archive_requested.set()
        def after(conn,cursor,statement,parameters,context,executemany):
            name=threading.current_thread().name
            if name.startswith('A02Publish') and 'FROM action_case' in statement and 'FOR UPDATE' in statement:
                case_locked.set();assert resume.wait(10)
            if name.startswith('A02Delete') and statement.startswith('DELETE FROM knowledge_archive'):
                deletion_started.set();assert archive_requested.wait(10)
        engine=db.get_engine();event.listen(engine,'before_cursor_execute',before);event.listen(engine,'after_cursor_execute',after)
        try:
            with tempfile.TemporaryDirectory() as directory:
                target=Path(directory)/'documents.json';target.write_text('[]')
                with ThreadPoolExecutor(1,thread_name_prefix='A02Publish') as pub,ThreadPoolExecutor(1,thread_name_prefix='A02Delete') as delete:
                    future=pub.submit(svc.publish,row['candidate_id'],target)
                    assert case_locked.wait(10)
                    removed=delete.submit(repo.delete_action_case,'a02-pg-delete')
                    assert deletion_started.wait(10);resume.set()
                    assert future.result(timeout=20)['added']==1 and removed.result(timeout=20)
        finally:
            resume.set();event.remove(engine,'before_cursor_execute',before);event.remove(engine,'after_cursor_execute',after)

    checks=[]
    try:
        if '--delete-race-only' in sys.argv:
            deletion_race();print('publication/delete lock order passed');return
        cards=get('/wiki/cards')['cards'];assert len(cards)==44 and all(c['schemaVersion']==2 for c in cards)
        assert get('/wiki/cards/metric-margin?version=1')['card']['legacy']
        checks.append('44 governed cards / explicit legacy version over HTTP')
        try:post('/wiki/cards',{})
        except urllib.error.HTTPError as exc:assert exc.code==405
        else:raise AssertionError('HTTP publication write exposed')
        post('/action/cases/a02-pg-http/verify',{'outcome':'resolved','note':'reported result, not verified enterprise performance'})
        row=max((c for c in get('/wiki/candidates')['candidates'] if c['sourceId']=='a02-pg-http'),key=lambda c:c['revision'])
        assert row['candidateStatus']=='draft' and row['sourceAvailable'] and row['evidenceLevel']=='reported'
        assert not get('/wiki/candidates/'+row['candidateId'])['candidate']['superseded']
        checks.append('real HTTP resolved generates draft with reported provenance')
        approved=svc.review(row['candidateId'],actor='test:PG-operator',reason='test report only',decision='approve',base_version=0)
        assert approved['status']=='reviewed'
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'documents.json';target.write_text('[]')
            assert svc.publish(row['candidateId'],target)['added']==1
            assert svc.publish(row['candidateId'],target)['added']==0
            repo.delete_action_case('a02-pg-http')
            assert not svc.get(row['candidateId'])['source_available']
            try:svc.publish(row['candidateId'],target)
            except RagContractError:pass
            else:raise AssertionError('deleted source published')
        checks.append('reviewed publish/repeat and source deletion guard in PostgreSQL')
        with patch('app.wiki.candidates.capture',side_effect=RagContractError('injected candidate failure')):
            try:flow.verify(repo,'a02-pg-failure','resolved',note='must rollback')
            except RagContractError:pass
            else:raise AssertionError('failure swallowed')
        assert repo.get_action_case('a02-pg-failure')['status']=='waiting_verify'
        assert not any(r['source_id']=='a02-pg-failure' for r in repo.list_knowledge())
        checks.append('injected candidate failure rolls back real PostgreSQL transaction')
        flow.verify(repo,'a02-pg-concurrency','resolved',note='concurrency fixture')
        barrier=threading.Barrier(2);seen=threading.local()
        def synchronize(conn,cursor,statement,parameters,context,executemany):
            if threading.current_thread().name.startswith('A02Lesson') and 'FROM action_case' in statement and not getattr(seen,'ready',False):
                seen.ready=True;barrier.wait(timeout=10)
        event.listen(db.get_engine(),'before_cursor_execute',synchronize)
        try:
            with ThreadPoolExecutor(2,thread_name_prefix='A02Lesson') as pool:
                results=list(pool.map(lambda _:repo.create_case_lesson('a02-pg-concurrency','same lesson'),range(2)))
            assert sorted(r['created'] for r in results)==[False,True]
        finally:event.remove(db.get_engine(),'before_cursor_execute',synchronize)
        assert len([r for r in svc.list() if r['source_id']=='a02-pg-concurrency' and r['entry_type']=='lesson' and r['source_available'] and not r['superseded']])==1
        checks.append('concurrent lesson creation preserves idempotency and one candidate')
        deletion_race();checks.append('publication and source deletion serialize without deadlock')
        output=Path('../output/a02-verification/pg-results.json');output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps({'checks':checks,'passed':True,'database':'disposable dora_a02'},ensure_ascii=False,indent=2)+'\n')
        print('wiki_pg_check:',len(checks),'checks passed')
    finally:
        for case_id in ids:repo.delete_action_case(case_id)

if __name__=='__main__':main()
