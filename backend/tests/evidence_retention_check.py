import unittest
from unittest.mock import patch
from sqlalchemy import select
from app import db
from app.models import ActionCase
from app.evidence.contracts import EvidenceError
from app.evidence.repository import EvidenceRepository
from app.evidence.action import create_case_captured
from app.seed import run_seed
from tests.evidence_test_support import evidence_fixture,raw_inputs


class RetentionChecks(unittest.TestCase):
    def test_recreated_watch_integer_id_does_not_reuse_binding(self):
        from app.watch.evaluator import evaluate_one
        from app.models import WatchTarget
        with evidence_fixture() as (repo,_):
            target=repo.create_watch_target('old',dict(metric_key='margin',condition=dict(type='below',ref=100)))
            first=evaluate_one(repo,target)['event'];repo.delete_watch_target(target['id'])
            with repo._session_ctx() as s:
                s.add(WatchTarget(id=target['id'],raw_text='new',intent=target['intent'],status='watching',frequency='on_update',created_at=target['created_at']));s.commit()
            second=evaluate_one(repo,repo.get_watch_target(target['id']))['event']
            self.assertEqual(first['id'],second['id'])
            self.assertNotEqual(first['historyEventId'],second['historyEventId'])
            with repo._session_ctx() as s:
                store=EvidenceRepository(s);self.assertEqual(store.get_binding(first['bindingId'])['sourceStatus'],'deleted')
                self.assertEqual(store.get_binding(second['bindingId'])['sourceStatus'],'available')
    def test_ready_sample_reset_does_not_reenter_schema_migration(self):
        with evidence_fixture():
            with patch('app.db.init_db',side_effect=AssertionError('ready DB must not migrate on sample request')):
                run_seed(reset_watch_events=True)
    def create(self,repo):return create_case_captured(repo,insight_type_id='p1',expected_revision=repo.read_business_inputs().business_version['revision'])
    def test_sample_reset_preserves_history_and_is_atomic(self):
        from app.watch.evaluator import evaluate_one
        with evidence_fixture() as (repo,_):
            opening=self.create(repo)['openingBinding'];target=repo.create_watch_target('sample',dict(metric_key='margin',condition=dict(type='below',ref=100)))
            evaluate_one(repo,target);before=repo.read_business_inputs().business_version;events=repo.list_watch_events(target['id'])
            with patch('app.evidence.retention.clear_watch_events_captured',side_effect=RuntimeError('reset fault')):
                with self.assertRaises(RuntimeError):run_seed(reset_watch_events=True)
            self.assertEqual(repo.read_business_inputs().business_version,before);self.assertEqual(repo.list_watch_events(target['id']),events)
            run_seed(reset_watch_events=True);self.assertEqual(repo.list_watch_events(target['id']),[]);self.assertEqual(repo.get_watch_target(target['id'])['status'],'watching')
            with repo._session_ctx() as s:self.assertEqual(EvidenceRepository(s).get_binding(opening['bindingId']),opening)
    def test_deleted_source_retains_history_and_blocks_old_approval(self):
        from app.action import flow
        from app.wiki.candidates import CandidateService
        with evidence_fixture() as (repo,_):
            opened=self.create(repo);cid=opened['case']['id'];binding=opened['openingBinding']
            for step in repo.get_action_case(cid)['steps']:repo.set_action_step_status(cid,step['seq'],'done')
            flow.verify(repo,cid,'resolved','statement');svc=CandidateService();candidate=svc.list()[0]
            svc.review(candidate['candidate_id'],actor='test',reason='reported',decision='approve',base_version=0)
            self.assertTrue(repo.delete_action_case(cid));self.assertFalse(repo.delete_action_case(cid))
            with repo._session_ctx() as s:
                self.assertEqual(EvidenceRepository(s).get_binding(binding['bindingId'])['sourceStatus'],'deleted')
                with self.assertRaises(EvidenceError):EvidenceRepository(s).case_history(cid)
            self.assertFalse(svc.get(candidate['candidate_id'])['source_available'])
            with self.assertRaises(EvidenceError) as e:self.create(repo)
            self.assertEqual(e.exception.code,'source_instance_deleted')
            with repo.business_transaction(source_mode='sample') as tx:tx.upsert_series(raw_inputs()['rows'])
            self.assertNotEqual(self.create(repo)['case']['id'],cid)
    def test_same_public_id_and_time_do_not_reuse_instance(self):
        from app.action.builder import create_case_from_insight
        from app.engine.engine import run_engine
        with evidence_fixture() as (repo,_):
            insight=next(i for i in run_engine(repo)['insights'] if i['id']=='p1')
            first=create_case_from_insight(repo,insight);old=first['openingBinding'];timestamp=first['case']['created_at']
            repo.delete_action_case('p1');second=create_case_from_insight(repo,insight)
            with repo._session_ctx() as s:s.get(ActionCase,'p1').created_at=timestamp;s.commit()
            self.assertNotEqual(old['sourceInstanceId'],second['openingBinding']['sourceInstanceId'])
            with repo._session_ctx() as s:
                store=EvidenceRepository(s);self.assertEqual(store.get_binding(old['bindingId'])['sourceStatus'],'deleted')
                self.assertEqual(store.case_history('p1')['opening']['bindingId'],second['openingBinding']['bindingId'])


if __name__=='__main__':unittest.main()
