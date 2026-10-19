import unittest
from datetime import date
from app.query.sources import FrozenWikiRepository,wiki_evidence,archive_evidence,fuse_evidence
from app.query.contracts import QueryOptions,ReadPolicy
from app.query.read_view import QueryReadViewReader
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.rag.embeddings import HashEmbeddingProvider
from app.runtime.executor import RunContext
from tests.query_test_support import query_fixture
from unittest.mock import patch

class Sources(unittest.TestCase):
    def capture(self,f):
        p=classify_query('利润率是什么，有处理记录吗？',Ontology.load(),on_date=date(2026,10,16))
        return QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now).capture(p,run_context=RunContext('unified-answer'))
    def test_a06_live_and_frozen_filter_equivalence(self):
        with query_fixture() as f:
            f.indexer.rebuild()
            view=self.capture(f);options=QueryOptions(includeSimulated=True)
            expected=f.repository.retrieval_snapshot(on_date=date(2026,10,16))
            with patch.object(f.source,'snapshot',side_effect=AssertionError('live file read')):
                actual=FrozenWikiRepository(view,options,ReadPolicy()).retrieval_snapshot()
            self.assertEqual([c['chunk_id'] for c in actual['chunks']],[c['chunk_id'] for c in expected['chunks']])
    def test_source_categories_and_simulation_policy(self):
        with query_fixture() as f:
            f.indexer.rebuild();v=self.capture(f);r=RunContext('unified-answer')
            result=wiki_evidence(v,'利润率',QueryOptions(topK=10),ReadPolicy(),run_context=r,embedding_provider=HashEmbeddingProvider())
            self.assertTrue(result['evidence'])
            self.assertTrue(all(e['sourceType']!='simulated' and e['evidenceLevel']!='simulated' for e in result['evidence']))
            self.assertTrue(all(e['snapshotId'] is None for e in result['evidence']))
    def test_reused_case_without_old_instance_proof_stays_unknown(self):
        from app.models import KnowledgeArchive,ActionCase
        from sqlalchemy.orm import Session
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                s.add(KnowledgeArchive(entry_type='lesson',source_id='reused',title='利润率处理记录',content='利润率排查复核',note='',created_at='2020'))
                s.commit()
            result=archive_evidence(self.capture(f),'利润率',QueryOptions(),ReadPolicy(),run_context=RunContext('unified-answer'))
            e=result['evidence'][0]
            self.assertEqual((e['knowledgeType'],e['archiveType'],e['evidenceLevel']),('case','lesson','legacy_unknown'))
            self.assertIsNone(e['archiveVersion']);self.assertIsNone(e['occurrenceId'])
    def test_source_balanced_rrf_and_verified_origin_group(self):
        wiki=[{'evidenceId':'w1','recordGroupId':'same'},{'evidenceId':'w2','recordGroupId':None}]
        archive=[{'evidenceId':'a1','recordGroupId':'same'},{'evidenceId':'a2','recordGroupId':None}]
        fused=fuse_evidence(wiki,archive,top_k=2)
        self.assertEqual(len(fused),2);self.assertTrue(any(e['evidenceId'].startswith('a') for e in fused));self.assertTrue(any(e['evidenceId'].startswith('w') for e in fused))
        self.assertLessEqual(sum(e['recordGroupId']=='same' for e in fused),1)
    def test_embedding_fault_lexical_fallback(self):
        class Invalid(HashEmbeddingProvider):
            def embed(self,texts):return [[float('nan')]*self.dimensions]
        with query_fixture() as f:
            f.indexer.rebuild();r=RunContext('unified-answer')
            result=wiki_evidence(self.capture(f),'利润率',QueryOptions(),ReadPolicy(),run_context=r,embedding_provider=Invalid())
            self.assertTrue(result['evidence']);self.assertEqual(result['fallbackReason'],'invalid_vector')
    def test_excluded_simulation_does_not_create_pending_count(self):
        from app.rag.source import SourceSnapshot
        from app.rag.identity import canonical,digest,embedding_profile
        from app.rag.contracts import load_documents
        from app.query.read_view import QueryReadView
        docs=[d for d in load_documents() if d['status']=='reviewed' and d['source_type']=='simulated'][:1]
        payload=canonical(docs);snap=SourceSnapshot(payload,digest(payload),date(2026,10,16),'now')
        state={'versions':{},'origins':{},'head':'test','batch':{'profile_hash':'wrong','source_revision':snap.revision},'projections':{},'manifest':{'versions':{},'projections':{},'barriers':{}}}
        view=QueryReadView(source=snap,business=None,indexState=state,archives=[],archiveOrigins={},sourceStates={},readAt='now',businessDate=date(2026,10,16))
        result=FrozenWikiRepository(view,QueryOptions(),ReadPolicy()).retrieval_snapshot(desired_profile=embedding_profile(HashEmbeddingProvider()))
        self.assertEqual(result['index']['pendingCount'],0);self.assertNotEqual(result['index']['indexStatus'],'pending')
