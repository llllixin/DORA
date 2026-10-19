"""Watch capture regressions against a private SQLite database."""
import unittest
from unittest.mock import patch
from sqlalchemy import select,func
from app.models import EvidenceBinding,EvidenceSnapshot
from app.evidence.repository import EvidenceRepository
from tests.evidence_test_support import evidence_fixture


class WatchEvidenceChecks(unittest.TestCase):
    def test_profile_only_change_does_not_duplicate_event(self):
        from app.evidence import service
        with evidence_fixture() as (repo,_):
            target=self.target(repo);self.evaluate(repo,target);repo.set_watch_status(target['id'],'watching')
            original=service.freeze_business_inputs
            with patch.object(service,'freeze_business_inputs',side_effect=lambda *a,**kw:original(*a,**kw).with_profile({'changed':'profile'})):
                self.assertTrue(self.evaluate(repo,target)['skipped'])
    def evaluate(self,repo,target):
        from app.watch.evaluator import evaluate_one
        return evaluate_one(repo,target)

    def target(self,repo,key='margin'):
        return repo.create_watch_target('capture',dict(metric_key=key,dimension='',condition=dict(type='below',ref=999999)))

    def binding(self,repo,out):
        self.assertIn('bindingId',out['event'])
        with repo._session_ctx() as s:return EvidenceRepository(s).get_binding(out['event']['bindingId'])

    def test_values_and_engine_share_frozen_inputs(self):
        with evidence_fixture() as (repo,_):
            target=self.target(repo)
            with patch.object(repo,'get_series',side_effect=AssertionError('live series forbidden')):
                out=self.evaluate(repo,target)
            binding=self.binding(repo,out)
            self.assertEqual(binding['sourceRecord']['target']['intent'],target['intent'])
            self.assertEqual(repo.list_watch_events(target['id'])[-1]['bindingId'],binding['bindingId'])
            with repo._session_ctx() as s:snapshot=EvidenceRepository(s).get_snapshot(binding['snapshotId'])
            self.assertEqual(binding['captureContext']['factVersion'],snapshot['factVersion'])
            from app.watch.evaluator import _chrono_values
            rows=[r for r in snapshot['payload']['rawSeries'] if r['metric_key']=='margin']
            self.assertEqual(out['event']['values']['cur'],_chrono_values(rows,'')[-1])
            self.assertIn(binding['occurrenceId'],[i['occurrenceId'] for i in snapshot['payload']['factInsights']])

    def test_same_intent_and_fact_deduplicated(self):
        with evidence_fixture() as (repo,_):
            target=self.target(repo);self.evaluate(repo,target);repo.set_watch_status(target['id'],'watching')
            out=self.evaluate(repo,target);self.assertTrue(out['skipped']);self.assertEqual(len(repo.list_watch_events(target['id'])),1)

    def test_new_generation_same_values_new_event(self):
        with evidence_fixture() as (repo,_):
            target=self.target(repo);first=self.evaluate(repo,target);repo.set_watch_status(target['id'],'watching')
            with repo.business_transaction(source_mode='sample') as tx:
                from tests.evidence_test_support import raw_inputs
                tx.upsert_series(raw_inputs()['rows'])
            second=self.evaluate(repo,target);self.assertFalse(second['skipped'])
            self.assertNotEqual(self.binding(repo,first)['snapshotId'],self.binding(repo,second)['snapshotId'])

    def test_nonwatching_target_cannot_record_event(self):
        with evidence_fixture() as (repo,_):
            target=self.target(repo);repo.set_watch_status(target['id'],'paused')
            self.assertFalse(self.evaluate(repo,target)['hit']);self.assertEqual(repo.list_watch_events(target['id']),[])

    def test_change_has_no_fake_occurrence(self):
        with evidence_fixture() as (repo,_):
            from tests.evidence_test_support import raw_inputs
            with repo.business_transaction(source_mode='sample') as tx:tx.upsert_series(raw_inputs(margin=99)['rows'])
            target=repo.create_watch_target('change',dict(metric_key='margin',dimension='',condition=dict(type='above',ref=0)))
            out=self.evaluate(repo,target)
            self.assertEqual(out['kind'],'change');self.assertIsNone(self.binding(repo,out)['occurrenceId'])

    def test_binding_failure_rolls_back_event_and_status(self):
        with evidence_fixture() as (repo,_):
            target=self.target(repo)
            with patch.object(EvidenceRepository,'put_binding',side_effect=RuntimeError('fault')):
                with self.assertRaises(RuntimeError):self.evaluate(repo,target)
            self.assertEqual(repo.list_watch_events(target['id']),[]);self.assertEqual(repo.get_watch_target(target['id'])['status'],'watching')
            with repo._session_ctx() as s:self.assertEqual(s.scalar(select(func.count()).select_from(EvidenceSnapshot)),0)


if __name__=='__main__':unittest.main()
