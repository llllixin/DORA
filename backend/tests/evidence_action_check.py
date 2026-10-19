import unittest
from unittest.mock import patch
from sqlalchemy import select,func
from app.evidence.repository import EvidenceRepository
from app.evidence.contracts import EvidenceError
from app.models import ActionCase,ActionVerification,EvidenceSnapshot,KnowledgeCandidate
from app.action import flow
from tests.evidence_test_support import evidence_fixture,raw_inputs


class ActionEvidenceChecks(unittest.TestCase):
    def create(self,repo,**kw):
        from app.evidence.action import create_case_captured
        return create_case_captured(repo,insight_type_id='p1',expected_revision=repo.read_business_inputs().business_version['revision'],**kw)
    def history(self,repo,cid):
        with repo._session_ctx() as s:return EvidenceRepository(s).case_history(cid)
    def done(self,repo,cid):
        for step in repo.get_action_case(cid)['steps']:repo.set_action_step_status(cid,step['seq'],'done')
    def test_occurrence_case_identity(self):
        with evidence_fixture() as (repo,_):
            first=self.create(repo);second=self.create(repo)
            self.assertEqual(first['case']['id'],second['case']['id']);self.assertFalse(second['created']);self.assertEqual(len(first['case']['id']),32)
            with repo.business_transaction(source_mode='sample') as tx:tx.upsert_series(raw_inputs()['rows'])
            self.assertNotEqual(first['case']['id'],self.create(repo)['case']['id'])
    def test_legacy_create_claim_and_steps_are_compatible(self):
        from app.action.builder import create_case_from_insight
        from app.engine.engine import run_engine
        with evidence_fixture() as (repo,_):
            insight=next(i for i in run_engine(repo)['insights'] if i['id']=='p1')
            first=create_case_from_insight(repo,insight);self.assertEqual(first['case']['id'],'p1')
            self.assertIsNotNone(self.history(repo,'p1')['opening']);repo.claim_action_case('p1')
            self.assertFalse(create_case_from_insight(repo,insight)['created'])
            flow.done_step(repo,'p1',1,note='observed');self.assertEqual(repo.get_action_case('p1')['steps'][1]['status'],'done')
    def test_opening_and_verifications_keep_separate_versions(self):
        with evidence_fixture() as (repo,_):
            cid=self.create(repo)['case']['id'];opening=self.history(repo,cid)['opening']
            flow.verify(repo,cid,'continue','first')
            with repo.business_transaction(source_mode='sample') as tx:tx.upsert_series(raw_inputs()['rows'])
            self.done(repo,cid);flow.verify(repo,cid,'resolved','human statement')
            history=self.history(repo,cid);self.assertEqual(history['opening'],opening)
            self.assertEqual([v['seq'] for v in history['verifications']],[1,2])
            self.assertNotEqual(history['verifications'][0]['binding']['snapshotId'],history['verifications'][1]['binding']['snapshotId'])
            with self.assertRaises(flow.ActionFlowError):flow.verify(repo,cid,'continue')
    def test_absent_signal_does_not_prove_causal_success(self):
        with evidence_fixture() as (repo,_):
            cid=self.create(repo)['case']['id']
            with repo.business_transaction(source_mode='uploaded') as tx:tx.upsert_series(raw_inputs(margin=99)['rows'])
            flow.verify(repo,cid,'continue','signal absent')
            binding=self.history(repo,cid)['verifications'][0]['binding']
            self.assertFalse(binding['sourceRecord']['signalPresent']);self.assertIsNone(binding['occurrenceId'])
            self.assertFalse(binding['sourceRecord']['causalSuccessVerified'])
    def test_candidate_failure_rolls_back_whole_verification(self):
        with evidence_fixture() as (repo,_):
            cid=self.create(repo)['case']['id'];self.done(repo,cid);before=repo.get_action_case(cid)
            with repo.business_transaction(source_mode='sample') as tx:tx.upsert_series(raw_inputs()['rows'])
            with repo._session_ctx() as s:before_snapshots=s.scalar(select(func.count()).select_from(EvidenceSnapshot))
            with patch('app.wiki.candidates.capture',side_effect=RuntimeError('candidate fault')):
                with self.assertRaises(RuntimeError):flow.verify(repo,cid,'resolved','statement')
            self.assertEqual(repo.get_action_case(cid),before);self.assertEqual(self.history(repo,cid)['verifications'],[]);self.assertEqual(repo.list_knowledge(),[])
            with repo._session_ctx() as s:self.assertEqual(s.scalar(select(func.count()).select_from(EvidenceSnapshot)),before_snapshots)
    def test_old_case_verification_does_not_backfill_opening(self):
        from app.action.builder import _case_for,_steps_for
        from app.engine.engine import run_engine
        with evidence_fixture() as (repo,_):
            insight=next(i for i in run_engine(repo)['insights'] if i['id']=='p1')
            repo.create_action_case(_case_for(insight),_steps_for(insight));repo.claim_action_case('p1')
            self.assertIsNone(self.history(repo,'p1')['opening']);flow.verify(repo,'p1','continue','new observation')
            history=self.history(repo,'p1');self.assertIsNone(history['opening']);self.assertEqual(len(history['verifications']),1)
            self.assertFalse(history['verifications'][0]['binding']['sourceRecord']['openingCaptured'])
    def test_claimed_sample_and_mixed_inputs_remain_simulated(self):
        with evidence_fixture() as (repo,_):
            with repo.business_transaction(source_mode='uploaded') as tx:tx.upsert_series([r for r in raw_inputs()['rows'] if r['metric_key']=='margin'])
            cid=self.create(repo)['case']['id'];repo.claim_action_case(cid);self.done(repo,cid);flow.verify(repo,cid,'resolved','human statement')
            with repo._session_ctx() as s:
                candidate=s.scalar(select(KnowledgeCandidate));self.assertEqual(candidate.evidence_level,'simulated')
    def test_new_candidate_refs_and_legacy_approval_are_compatible(self):
        from app.wiki.candidates import CandidateService
        with evidence_fixture() as (repo,_):
            # Genuine pre-A05 source: low-level legacy writer deliberately has no binding.
            from app.action.builder import _case_for,_steps_for
            from app.engine.engine import run_engine
            insight=next(i for i in run_engine(repo)['insights'] if i['id']=='p1')
            repo.create_action_case(_case_for(insight),_steps_for(insight));repo.verify_action_case('p1','resolved','legacy')
            svc=CandidateService();old=svc.list()[0];svc.review(old['candidate_id'],actor='test',reason='reported',decision='approve',base_version=0)
            self.assertNotIn('history_refs',old['payload']['governance']['origin']['snapshot'])
            cid=self.create(repo)['case']['id'];self.done(repo,cid);flow.verify(repo,cid,'resolved','new')
            newest=next(x for x in svc.list() if x['source_id']==cid)
            self.assertIn('history_refs',newest['payload']['governance']['origin']['snapshot']);self.assertTrue(svc.get(old['candidate_id'])['source_available'])
    def test_oversize_capture_leaves_no_case(self):
        with evidence_fixture() as (repo,_):
            with patch('app.evidence.contracts.MAX_SNAPSHOT_BYTES',10):
                with self.assertRaises(EvidenceError) as raised:self.create(repo)
            self.assertEqual(raised.exception.status_code,413);self.assertEqual(repo.list_action_cases(),[])
            with repo._session_ctx() as s:self.assertEqual(s.scalar(select(func.count()).select_from(EvidenceSnapshot)),0)


if __name__=='__main__':unittest.main()
