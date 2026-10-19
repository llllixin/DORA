"""Offline semantic replay evidence must not silently become a paid call or promotion."""
import importlib.util
import unittest
from copy import deepcopy


class EvaluationBoundary(unittest.TestCase):
    def test_missing_snapshot_keeps_current_strategy_unfinished(self):
        self.assertIsNotNone(importlib.util.find_spec('app.rag.semantic_evaluation'))
        from app.rag.semantic_evaluation import compare_semantic_snapshot
        result=compare_semantic_snapshot()
        self.assertEqual(result['status'],'not_executed')
        self.assertFalse(result['candidateEligibleForDefault'])
        self.assertEqual(result['defaultPolicy'],'lexical-gated-rrf-v1')
        self.assertIsNone(result['actualTokens'])

    def test_foreign_space_and_hash_probes_are_rejected(self):
        self.assertIsNotNone(importlib.util.find_spec('app.rag.semantic_evaluation'))
        from app.rag.semantic_evaluation import compare_semantic_snapshot
        from app.runtime.contracts import RuntimeFailure
        for profile in ({'provider':'hash','dimensions':32},{'provider':'semantic','dimensions':32}):
            with self.subTest(profile=profile),self.assertRaises(RuntimeFailure):
                compare_semantic_snapshot({'embeddingProfile':profile,'profileHash':'wrong','documents':[],'queries':[]})

    def test_synthetic_replay_never_qualifies_as_real_semantic_evidence(self):
        from app.rag.semantic_evaluation import compare_semantic_snapshot
        from app.rag.source import KnowledgeSource
        from app.rag.contracts import load_eval_set
        from app.rag.embeddings import HashEmbeddingProvider
        from app.rag.identity import embedding_profile,profile_hash,digest
        from app.rag.indexer import split_text
        from app.rag.ontology import Ontology
        from app.wiki.reader import effective_documents
        from unittest.mock import patch
        source=KnowledgeSource().snapshot();embed=HashEmbeddingProvider();ontology=Ontology.load()
        profile=embedding_profile(embed);profile.update(provider='synthetic-fixture',model='synthetic-not-semantic')
        ph=profile_hash(profile);documents=[];queries=[]
        for doc in effective_documents(source.documents,source.business_date):
            for index,body in enumerate(split_text(doc['content'])):
                value=doc['title']+'\n'+body
                documents.append({'chunk_id':f"{doc['id']}@{doc['version']}#{index}-{digest(body)[:12]}",
                    'embeddingInputHash':digest(value),'profileHash':ph,'vector':embed._one(value)})
        for q in load_eval_set('ontology-v2'):
            value=' '.join([q['query'],*ontology.expand(q['query'])['terms']])
            queries.append({'id':q['id'],'embeddingInputHash':digest(value),'profileHash':ph,'vector':embed._one(value)})
        data={'embeddingProfile':profile,'profileHash':ph,'sourceRevision':source.revision,'semanticThreshold':.8,
            'documents':documents,'queries':queries,'provenance':{'kind':'synthetic'}}
        with patch('app.db.make_session',side_effect=AssertionError('offline replay must not access DB')),patch('urllib.request.urlopen',side_effect=AssertionError('no network')):
            result=compare_semantic_snapshot(data)
        self.assertEqual(result['status'],'synthetic_diagnostic_only');self.assertFalse(result['candidateEligibleForDefault'])
        self.assertEqual(result['reports']['lexical-gated-rrf-v1']['ontology-v2']['metrics']['questions'],40)
        self.assertEqual(result['externalModelCalls'],0)
        report=result['reports']['lexical-gated-rrf-v1']['ontology-v2']
        self.assertEqual(report['strategyProfile'],'lexical-gated-rrf-v1')
        self.assertIn('p95',report['contextBodyChars']);self.assertIn('templateSelectedBodyChars',report)
        data['provenance']['kind']='captured'
        with patch('app.db.make_session',side_effect=AssertionError('offline replay must not access DB')):
            self.assertEqual(compare_semantic_snapshot(data)['status'],'synthetic_diagnostic_only')
        data['queries'][0]['profileHash']='different-space'
        from app.runtime.contracts import RuntimeFailure
        with self.assertRaisesRegex(RuntimeFailure,'invalid_semantic_snapshot'):compare_semantic_snapshot(data)

    def test_gate_rejects_user_database_before_any_work(self):
        self.assertIsNotNone(importlib.util.find_spec('tests.knowledge_index_gate'))
        from tests.knowledge_index_gate import validate_environment
        for database in ('','postgresql+psycopg://dora:dora@127.0.0.1:5432/dora','postgresql+psycopg://dora_a06:x@example.org:55466/dora_a06'):
            with self.subTest(database=database),self.assertRaises(RuntimeError):
                validate_environment({'DATABASE_URL':database,'DORA_API_BASE':'http://127.0.0.1:8066/api'})
        self.assertEqual(validate_environment({'DATABASE_URL':'postgresql+psycopg://dora_a06:x@127.0.0.1:55466/dora_a06','DORA_API_BASE':'http://127.0.0.1:8066/api'})[1],8066)


if __name__=='__main__':unittest.main(verbosity=2)
