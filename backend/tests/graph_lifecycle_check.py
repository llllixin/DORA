"""Real governed lessons, lifecycle propagation and verification provenance."""
import unittest,json
from copy import deepcopy
from sqlalchemy import select
from tests.graph_test_support import graph_fixture,open_case,install_document
from app.graph.contracts import GraphError,Budget,GraphLimits,GraphRequest
from app.graph.source import SourceReader
from app.graph.projector import project
from app.graph.service import GraphService
from app.action import flow
from app.wiki.candidates import CandidateService
from app.rag.contracts import load_documents
from app.graph.models import GraphEntity


class GraphLifecycle(unittest.TestCase):
    def lesson(self,repo):
        cid=open_case(repo)['case']['id']
        flow.verify(repo,cid,'continue','first observation')
        for step in repo.get_action_case(cid)['steps']:repo.set_action_step_status(cid,step['seq'],'done')
        flow.verify(repo,cid,'resolved','reported result, not causal verification')
        repo.create_case_lesson(cid,'only this case, reported result')
        candidate=next(c for c in CandidateService().list() if c['entry_type']=='lesson')
        return cid,candidate
    def publish(self,engine,source,candidate):
        svc=CandidateService();svc.review(candidate['candidate_id'],actor='test:reviewer',reason='fixture text reviewed, no enterprise effect claim',decision='approve',base_version=0)
        svc.publish(candidate['candidate_id'],path=source.path)
        doc=load_documents(source.path)[-1];install_document(engine,source,doc);return doc
    def test_draft_excluded_reviewed_lesson_link_and_verifications_separate(self):
        with graph_fixture() as (repo,engine,source):
            cid,candidate=self.lesson(repo);reader=SourceReader(engine,source)
            draft=project(reader.capture(Budget()),GraphLimits(),Budget())
            self.assertFalse(any(n['type']=='Lesson' for n in draft['nodes']))
            self.publish(engine,source,candidate)
            graph=project(reader.capture(Budget()),GraphLimits(),Budget())
            self.assertEqual(len([e for e in graph['relations'] if e['type']=='lesson_from']),1)
            verified=[e for e in graph['relations'] if e['type']=='verified_with']
            self.assertEqual(len(verified),2);self.assertEqual(len({e['qualifier']['bindingId'] for e in verified}),2)
            self.assertTrue(all(w['sourceLevel']=='simulated' for w in graph['evidence'] if w['sourceKind']=='document'))
    def test_retirement_before_sync_hides_root_but_preserves_batch(self):
        with graph_fixture() as (repo,engine,source):
            cid,candidate=self.lesson(repo);doc=self.publish(engine,source,candidate);service=GraphService(engine,source);batch=service.sync()
            with repo._session_ctx() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='Lesson')
            request=GraphRequest(entityId=root,includeSimulated=True,mode='historical',batchId=batch['batchId'])
            first=service.neighborhood(request)
            svc=CandidateService();svc.review(candidate['candidate_id'],actor='test:reviewer',reason='retired fixture',decision='retire',base_version=1);svc.publish(candidate['candidate_id'],path=source.path)
            with self.assertRaises(GraphError):service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            old=service.neighborhood(request);self.assertEqual(first['relations'],old['relations'])
            self.assertTrue(any(w['sourceCurrentStatus']=='retired' for w in old['evidence']))
    def test_new_published_version_pending_and_removed_source_do_not_revive_old(self):
        with graph_fixture() as (repo,engine,source):
            cid,candidate=self.lesson(repo);doc=self.publish(engine,source,candidate);service=GraphService(engine,source);batch=service.sync()
            with repo._session_ctx() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='Lesson')
            # A formally reviewed new version, not yet imported into A06 originals.
            svc=CandidateService();payload=deepcopy(svc.get(candidate['candidate_id'])['payload'])
            payload['title']='new reviewed fixture version'
            newer=svc.revise(candidate['candidate_id'],payload)
            svc.review(newer['candidate_id'],actor='test:reviewer',reason='new fixture version',decision='approve',base_version=1)
            svc.publish(newer['candidate_id'],path=source.path)
            view=service.reader.capture(Budget());self.assertTrue(any(m['reason']=='document_pending' for m in view['missing']))
            self.assertNotEqual(view['records'][f"document:{doc['id']}@1"]['status'],'available')
            with self.assertRaises(GraphError):service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            source.path.write_text('[]')
            with self.assertRaises(GraphError):service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            self.assertEqual(service.status()['sourceState'],'pending')
    def test_legacy_missing_watch_and_signal_absence_are_not_invented(self):
        from app.watch.evaluator import evaluate_one
        from tests.evidence_test_support import raw_inputs
        with graph_fixture() as (repo,engine,source):
            opened=open_case(repo);target=repo.create_watch_target('margin',dict(metric_key='margin',condition=dict(type='below',ref=100)));evaluate_one(repo,target)
            repo.upsert_series(raw_inputs(margin=99)['rows']);flow.verify(repo,opened['case']['id'],'continue','signal absent')
            graph=project(SourceReader(engine,source).capture(Budget()),GraphLimits(),Budget())
            self.assertEqual(len([e for e in graph['relations'] if e['type']=='verified_with']),1)
            self.assertTrue(all(e['causality']=='not_asserted' for e in graph['relations']))
    def test_unavailable_source_has_stable_service_error(self):
        with graph_fixture() as (repo,engine,source):
            open_case(repo);service=GraphService(engine,source);service.sync();source.path.unlink()
            with self.assertRaises(GraphError) as error:service.status()
            self.assertEqual(error.exception.status_code,503)

    def test_expiry_and_origin_deletion_filter_old_lesson_before_graph_sync(self):
        from datetime import date,timedelta
        from unittest.mock import patch
        for change in ('expired','origin_deleted'):
            with self.subTest(change=change),graph_fixture() as (repo,engine,source):
                cid,candidate=self.lesson(repo);svc=CandidateService()
                day=date.fromisoformat(candidate['payload']['valid_from']);payload=deepcopy(candidate['payload'])
                payload['valid_to']=day.isoformat();candidate=svc.revise(candidate['candidate_id'],payload)
                doc=self.publish(engine,source,candidate);original=source.locked_snapshot;as_of=[day]
                with patch.object(source,'locked_snapshot',lambda **kw:original(on_date=as_of[0],**kw)):
                    service=GraphService(engine,source);batch=service.sync()
                    with repo._session_ctx() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='Lesson')
                    if change=='expired':as_of[0]=day+timedelta(days=1)
                    else:repo.delete_action_case(cid)
                    with self.assertRaises(GraphError) as error:service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
                    self.assertEqual(error.exception.status_code,404)
                    old=service.neighborhood(GraphRequest(entityId=root,mode='historical',batchId=batch['batchId'],includeSimulated=True))
                    expected='expired' if change=='expired' else 'origin_unavailable'
                    self.assertTrue(any(w['sourceCurrentStatus']==expected for w in old['evidence']))

    def test_a06_removal_barrier_does_not_revive_readded_same_version(self):
        from app.rag.repository import RagRepository
        from app.rag.indexer import RagIndexer
        from app.rag.embeddings import HashEmbeddingProvider
        from tests.model_runtime_support import MemoryRuns
        with graph_fixture() as (repo,engine,source):
            cid,candidate=self.lesson(repo);doc=self.publish(engine,source,candidate)
            indexer=RagIndexer(RagRepository(source=source),HashEmbeddingProvider(),MemoryRuns())
            indexer.rebuild();service=GraphService(engine,source);batch=service.sync()
            with repo._session_ctx() as s:root=next(n.data['id'] for n in s.scalars(select(GraphEntity)) if n.data['type']=='Lesson')
            source.path.write_text('[]');indexer.rebuild()
            source.path.write_text(json.dumps([doc],ensure_ascii=False))
            with self.assertRaises(GraphError):service.neighborhood(GraphRequest(entityId=root,includeSimulated=True))
            old=service.neighborhood(GraphRequest(entityId=root,mode='historical',batchId=batch['batchId'],includeSimulated=True))
            self.assertTrue(any(w['sourceCurrentStatus']=='removed' for w in old['evidence']))


if __name__=='__main__':unittest.main()
