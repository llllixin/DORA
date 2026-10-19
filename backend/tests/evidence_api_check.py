import unittest
from unittest.mock import patch
from sqlalchemy import event,select
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient
from app import models
from tests.evidence_test_support import evidence_fixture
from app.evidence.contracts import build_snapshot


class HistoryApiChecks(unittest.TestCase):
    def test_manual_watch_check_has_one_atomic_touch(self):
        from app.repository import Repository
        client=self.client();original=Repository.touch_watch_target;calls=[]
        def touch(repo,*a,**kw):calls.append(repo._transactional);return original(repo,*a,**kw)
        with evidence_fixture() as (repo,_):
            target=repo.create_watch_target('margin',dict(metric_key='margin',condition=dict(type='below',ref=100)))
            with patch.object(Repository,'touch_watch_target',touch):
                response=client.post('/api/watch/'+target['id']+'/check')
            self.assertEqual(response.status_code,200);self.assertEqual(calls,[True])
    def test_watch_link_valid_old_and_other_scope(self):
        from app.watch.evaluator import evaluate_one
        from app.business_version import SCOPE_ID
        from uuid import uuid4
        from tests.evidence_test_support import raw_inputs
        client=self.client()
        with evidence_fixture() as (repo,engine):
            target=repo.create_watch_target('margin',dict(metric_key='margin',condition=dict(type='below',ref=100)))
            out=evaluate_one(repo,target);version=repo.read_business_inputs().business_version
            opened=client.post('/api/history/action-cases',json=dict(insightTypeId='p1',expectedRevision=version['revision'],sourceWatchBindingId=out['event']['bindingId']))
            self.assertEqual(opened.status_code,200)
            self.assertEqual(opened.json()['openingBinding']['sourceRecord']['sourceWatchBindingId'],out['event']['bindingId'])
            with repo.business_transaction(source_mode='uploaded') as tx:tx.upsert_series(raw_inputs()['rows'])
            other=uuid4().hex
            with Session(engine) as s:
                s.add(models.EvidenceBinding(binding_id=other,scope_id='other:scope',snapshot_id=None,owner_kind='watch_event',owner_instance_id=uuid4().hex,
                    owner_public_id='1',source_kind='watch_target',source_instance_id=uuid4().hex,occurrence_id=None,capture_context={},source_record={},recorded_at='other'))
                s.commit();before=s.query(models.EvidenceSnapshot).count()
            for ref in (out['event']['bindingId'],other):
                response=client.post('/api/history/action-cases',json=dict(insightTypeId='p1',expectedRevision=repo.read_business_inputs().business_version['revision'],sourceWatchBindingId=ref))
                self.assertEqual(response.status_code,409);self.assertEqual(response.json()['reasonCode'],'source_occurrence_conflict')
            with Session(engine) as s:self.assertEqual(s.query(models.EvidenceSnapshot).count(),before)
    def test_stale_create_revision_is_409_without_writes(self):
        client=self.client()
        with evidence_fixture() as (repo,engine):
            response=client.post('/api/history/action-cases',json=dict(insightTypeId='p1',expectedRevision='old'))
            self.assertEqual(response.status_code,409);self.assertEqual(response.json()['reasonCode'],'revision_conflict')
            self.assertEqual(repo.list_action_cases(),[])
            with Session(engine) as s:self.assertEqual(s.query(models.EvidenceSnapshot).count(),0)
    def test_wrong_watch_reference_is_409(self):
        client=self.client()
        with evidence_fixture() as (repo,engine):
            version=repo.read_business_inputs().business_version
            for ref in ('missing','some-other-scope'):
                response=client.post('/api/history/action-cases',json=dict(insightTypeId='p1',expectedRevision=version['revision'],sourceWatchBindingId=ref))
                self.assertEqual(response.status_code,409);self.assertEqual(response.json()['reasonCode'],'source_occurrence_conflict')
            self.assertEqual(repo.list_action_cases(),[])
            with Session(engine) as s:self.assertEqual(s.query(models.EvidenceSnapshot).count(),0)
    def client(self):
        from app.main import app
        self.assertTrue(any(getattr(r,'path','')=='/api/history/snapshots/{snapshot_id}' for r in app.routes),'history API not implemented')
        return TestClient(app)
    def save(self,repo,engine,scope=None):
        from app.evidence.repository import EvidenceRepository
        package=build_snapshot(repo.read_business_inputs())
        if scope:
            from app.business_version import canonical_hash
            package['scopeId']=scope;package['factVersion']['scopeId']=scope
            package['payloadHash']=canonical_hash(package['payload']);package['snapshotId']='snap-v1:'+package['payloadHash']
        with Session(engine) as s:
            EvidenceRepository(s,scope_id=scope or 'dora:default').put_snapshot(package,captured_at='saved');s.commit()
        return package
    def test_get_does_not_write_or_recompute(self):
        client=self.client()
        with evidence_fixture() as (repo,engine):
            p=self.save(repo,engine);writes=[]
            def watch(conn,cursor,statement,*_):
                if statement.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','ALTER','CREATE'):writes.append(statement)
            event.listen(engine,'before_cursor_execute',watch)
            with patch.dict('os.environ',{'DORA_REASONING_PROVIDER':'invalid-profile'}),patch('app.engine.engine.run_engine',side_effect=AssertionError('recompute')),patch('urllib.request.urlopen',side_effect=AssertionError('transport')):
                for _ in range(2):self.assertEqual(client.get('/api/history/snapshots/'+p['snapshotId']).json()['snapshot']['capturedAt'],'saved')
            self.assertEqual(writes,[])
    def test_corrupt_snapshot_rejected_without_current_fallback(self):
        client=self.client()
        with evidence_fixture() as (repo,engine):
            p=self.save(repo,engine)
            with Session(engine) as s:
                row=s.get(models.EvidenceSnapshot,p['snapshotId']);row.payload_hash='corrupt';s.commit()
            response=client.get('/api/history/snapshots/'+p['snapshotId']);self.assertEqual(response.status_code,409)
    def test_other_scope_is_404(self):
        client=self.client()
        with evidence_fixture() as (repo,engine):
            p=self.save(repo,engine,scope='other:scope')
            self.assertEqual(client.get('/api/history/snapshots/'+p['snapshotId']).status_code,404)
    def test_legacy_history_stays_unknown_without_id_assignment(self):
        client=self.client()
        from app.action.builder import _case_for,_steps_for
        from app.engine.engine import run_engine
        with evidence_fixture() as (repo,engine):
            insight=next(i for i in run_engine(repo)['insights'] if i['id']=='p1')
            repo.create_action_case(_case_for(insight),_steps_for(insight))
            result=client.get('/api/history/action-cases/p1').json()['history']
            self.assertEqual(result['provenanceStatus'],'insufficient_provenance');self.assertIsNone(result['opening'])
            with Session(engine) as s:self.assertIsNone(s.get(models.ActionCase,'p1').history_instance_id)


if __name__=='__main__':unittest.main()
