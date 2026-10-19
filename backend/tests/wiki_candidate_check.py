"""A02 candidate behavior against real SQLite transactions; PG gate follows."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine,select,text
from app import db
from app.models import Base,ActionCase,ActionStep,KnowledgeArchive
from app.repository import Repository
from app.action import flow
from app.rag.contracts import RagContractError

class CandidateChecks(unittest.TestCase):
    def setUp(self):
        self.engine=create_engine('sqlite://');Base.metadata.create_all(self.engine)
        self.binding=patch.object(db,'_engine',self.engine);self.binding.start()
        self.repo=Repository()
        with db.make_session() as s:
            s.add(ActionCase(id='a02-case',case_title='test action',kind='problem',status='waiting_verify',origin='engine'))
            s.add(ActionStep(case_id='a02-case',seq=0,title='step',status='done'));s.commit()
    def tearDown(self):self.binding.stop();self.engine.dispose()
    def service(self):
        from app.wiki.candidates import CandidateService
        return CandidateService()
    def resolve(self):return flow.verify(self.repo,'a02-case','resolved',note='reported outcome')

    def test_resolved_creates_independent_draft(self):
        self.resolve()
        with db.make_session() as s:
            self.assertEqual(s.execute(text('SELECT count(*) FROM knowledge_candidate')).scalar(),1)
        candidate=self.service().list()[0]
        self.assertEqual(candidate['status'],'draft');self.assertEqual(candidate['evidence_level'],'reported')
        self.assertTrue(candidate['source_available']);self.assertEqual(len(self.repo.list_knowledge()),1)

    def test_lesson_and_collection_are_idempotent(self):
        self.resolve();self.repo.create_case_lesson('a02-case','lesson note');self.repo.create_case_lesson('a02-case','lesson note')
        svc=self.service();self.assertEqual(len(svc.list()),2);self.assertEqual(svc.collect()['created'],0)

    def test_candidate_failure_rolls_back_resolved(self):
        from app.wiki import candidates
        with patch.object(candidates,'capture',side_effect=RagContractError('injected capture failure')):
            with self.assertRaises(RagContractError):self.resolve()
        self.assertEqual(self.repo.get_action_case('a02-case')['status'],'waiting_verify')
        self.assertEqual(self.repo.list_knowledge(),[])

    def test_origin_changes_or_deletion_invalidate_review(self):
        self.resolve();svc=self.service();candidate=svc.list()[0]
        approved=svc.review(candidate['candidate_id'],actor='test:operator',reason='check report',decision='approve',base_version=0)
        self.assertEqual(approved['status'],'reviewed')
        with db.make_session() as s:
            row=s.execute(select(KnowledgeArchive)).scalars().first();row.note='changed source';s.commit()
        self.assertFalse(svc.get(candidate['candidate_id'])['source_available'])
        with self.assertRaises(RagContractError):svc.export(candidate['candidate_id'])
        self.assertEqual(svc.collect()['created'],1)
        newest=max(svc.list(),key=lambda x:x['revision']);self.assertEqual(newest['status'],'draft')
        self.repo.delete_action_case('a02-case')
        self.assertFalse(svc.get(newest['candidate_id'])['source_available'])
        with self.assertRaises(RagContractError):svc.review(newest['candidate_id'],actor='test:operator',reason='missing source',decision='approve',base_version=0)

    def test_edit_creates_draft_revision_and_does_not_inherit_review(self):
        self.resolve();svc=self.service();old=svc.list()[0]
        svc.review(old['candidate_id'],actor='test:operator',reason='check report',decision='approve',base_version=0)
        payload=deepcopy(svc.get(old['candidate_id'])['payload']);payload['title']='edited lesson'
        new=svc.revise(old['candidate_id'],payload)
        self.assertEqual(new['revision'],2);self.assertEqual(new['status'],'draft');self.assertIsNone(new['payload']['governance']['review'])
        self.assertEqual(svc.get(old['candidate_id'])['status'],'reviewed')
        with self.assertRaises(RagContractError):svc.export(old['candidate_id'])

    def test_demo_stays_simulated_and_cannot_be_verified(self):
        with db.make_session() as s:s.get(ActionCase,'a02-case').origin='demo';s.commit()
        self.resolve();svc=self.service();candidate=svc.list()[0]
        self.assertEqual(candidate['evidence_level'],'simulated')
        raw=deepcopy(candidate['payload']);raw['source_type']='verified_case'
        with self.assertRaises(RagContractError):svc.revise(candidate['candidate_id'],raw)

    def test_source_reversion_produces_fresh_revision(self):
        self.resolve();svc=self.service()
        with db.make_session() as s:
            row=s.execute(select(KnowledgeArchive)).scalars().first();original=row.note;row.note='new source';s.commit()
        self.assertEqual(svc.collect()['created'],1)
        with db.make_session() as s:
            row=s.execute(select(KnowledgeArchive)).scalars().first();row.note=original;s.commit()
        self.assertEqual(svc.collect()['created'],1)
        latest=max(svc.list(),key=lambda r:r['revision'])
        self.assertEqual(latest['revision'],3);self.assertEqual(latest['status'],'draft');self.assertTrue(latest['source_available'])

    def test_human_reject_records_reason_and_blocks_export(self):
        self.resolve();svc=self.service();candidate=svc.list()[0]
        out=svc.review(candidate['candidate_id'],actor='test:operator',reason='缺少财务与经营结果来源，拒绝发布',decision='reject',base_version=0)
        self.assertEqual(out['status'],'draft');self.assertEqual(out['review_events'][-1]['decision'],'reject')
        self.assertEqual(out['review_events'][-1]['actor'],'test:operator')
        self.assertEqual(len(out['review_events'][-1]['payloadHash']),64)
        with self.assertRaises(RagContractError):svc.export(candidate['candidate_id'])

    def test_recreated_identical_source_does_not_revive_old_approval(self):
        self.resolve();svc=self.service();old=svc.list()[0]
        svc.review(old['candidate_id'],actor='test:operator',reason='old source',decision='approve',base_version=0)
        with db.make_session() as s:
            row=s.execute(select(KnowledgeArchive)).scalars().first()
            fields={k:getattr(row,k) for k in ('entry_type','source_id','code','title','content','note','created_at')}
        self.repo.delete_action_case('a02-case')
        with db.make_session() as s:
            s.add(ActionCase(id='a02-case',case_title='test action',kind='problem',status='resolved',origin='engine'))
            s.add(KnowledgeArchive(**fields));s.commit()
        self.assertFalse(svc.get(old['candidate_id'])['source_available'])
        with self.assertRaises(RagContractError):svc.export(old['candidate_id'])
        self.assertEqual(svc.collect()['created'],1)
        latest=max(svc.list(),key=lambda r:r['revision']);self.assertEqual(latest['status'],'draft')

    def test_candidate_publish_repeat_and_retire(self):
        self.resolve();svc=self.service();candidate=svc.list()[0]
        svc.review(candidate['candidate_id'],actor='test:operator',reason='report only',decision='approve',base_version=0)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'documents.json';target.write_text('[]')
            self.assertEqual(svc.publish(candidate['candidate_id'],target)['added'],1)
            self.assertEqual(svc.publish(candidate['candidate_id'],target)['added'],0)
            svc.review(candidate['candidate_id'],actor='test:operator',reason='withdraw',decision='retire',base_version=1)
            self.assertEqual(svc.export(candidate['candidate_id'])['status'],'retired')
            self.assertEqual(svc.publish(candidate['candidate_id'],target)['added'],1)
            from app.wiki.reader import read_cards
            self.assertEqual(read_cards(target),[])

    def test_published_candidate_can_be_withdrawn_after_source_deletion(self):
        self.resolve();svc=self.service();candidate=svc.list()[0]
        svc.review(candidate['candidate_id'],actor='test:operator',reason='report only',decision='approve',base_version=0)
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'documents.json';target.write_text('[]');svc.publish(candidate['candidate_id'],target)
            self.repo.delete_action_case('a02-case')
            svc.review(candidate['candidate_id'],actor='test:operator',reason='source removed',decision='retire',base_version=1)
            self.assertEqual(svc.publish(candidate['candidate_id'],target)['added'],1)
            from app.wiki.reader import read_cards
            self.assertEqual(read_cards(target),[])

if __name__=='__main__':unittest.main()
