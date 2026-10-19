"""A06 real SQLite transactions, immutable history and migration fault checks."""
from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text, select, event
from app import db
from app.models import Base
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.indexer import RagIndexer
from app.rag.repository import RagRepository
from app.runtime.executor import RunContext, runtime_managed
from app.runtime.budget import load_profile
from app.runtime.contracts import RuntimeFailure
from tests.model_runtime_support import MemoryRuns
from tests.wiki_check import draft, reviewed


class CountingHash(HashEmbeddingProvider):
    def __init__(self): super().__init__();self.inputs=0;self.after=None
    def _one(self, value):
        self.inputs+=1
        if self.after:self.after()
        return super()._one(value)


class IndexIntegration(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.root=Path(self.temp.name)
        self.engine=create_engine('sqlite:///'+str(self.root/'test.db'))
        self.patch=patch.object(db,'_engine',self.engine);self.patch.start()
        self.path=self.root/'documents.json';self.provider=CountingHash();self.runs=MemoryRuns()

    def tearDown(self): self.patch.stop();self.engine.dispose();self.temp.cleanup()

    def doc(self, version=1, **changes):
        d=draft();d['id']='index-topic';d['version']=version;d['valid_from']='2026-01-01';d.update(changes)
        return reviewed(d,base=version-1)

    def write(self, docs): self.path.write_text(json.dumps(docs,ensure_ascii=False))

    def setup_index(self, docs=None):
        from app.rag.source import KnowledgeSource
        from app.rag.migration import init_rag_index
        Base.metadata.create_all(self.engine);init_rag_index(self.engine)
        self.write(docs or [self.doc()]);self.repo=RagRepository(source=KnowledgeSource(self.path))
        self.index=RagIndexer(self.repo,self.provider,self.runs)
        return self.index.rebuild()

    def test_repeated_rebuild_zero_embedding(self):
        self.setup_index();self.assertGreater(self.provider.inputs,0);self.provider.inputs=0
        report=self.index.rebuild();self.assertEqual(self.provider.inputs,0)
        self.assertEqual(report['updated'],0);self.assertEqual(report['projectionCreated'],0)
        self.assertTrue(self.repo.active_chunks())

    def test_same_version_last_conflict_before_calls(self):
        self.setup_index();head=self.repo.index_status()['indexBatchId'];self.provider.inputs=0
        conflict=self.doc(title='same version changed');other=self.doc(2)
        self.write([conflict,other])
        from app.rag.contracts import RagIndexConflict
        with self.assertRaisesRegex(RagIndexConflict,'document_version_conflict') as failed:self.index.rebuild()
        self.assertEqual(self.provider.inputs,0)
        report=self.runs.get_agent_run(failed.exception.run_id)['output']['indexReport']
        self.assertEqual(report['previousBatchId'],head);self.assertIsNone(report['indexBatchId'])
        self.assertTrue(report['sourceRevision']);self.assertTrue(report['embeddingProfileHash'])
        from app.rag.index_store import RagIndexStore
        self.assertEqual(RagIndexStore().read_snapshot()['head'],head)
        self.assertNotEqual(self.repo.get_document('index-topic',1)['title'],conflict['title'])

    def test_new_version_reuses_vectors_and_preserves_history(self):
        old=self.doc();self.setup_index([old]);before=self.repo.get_document('index-topic',1)
        self.provider.inputs=0;self.write([old,self.doc(2)])
        result=self.index.rebuild();self.assertEqual(self.provider.inputs,0);self.assertGreater(result['reusedInputs'],0)
        after=self.repo.get_document('index-topic',1)
        self.assertEqual(before['content'],after['content']);self.assertEqual(before['chunks'],after['chunks'])
        self.assertTrue(all(c['version']==2 for c in self.repo.active_chunks()))

    def test_latest_pending_retirement_and_expiry_without_sync(self):
        old=self.doc();self.setup_index([old]);self.write([old,self.doc(2,title='new knowledge')])
        self.assertEqual(self.repo.active_chunks(),[]);self.assertEqual(self.repo.index_status()['indexStatus'],'pending')
        from app.wiki.contracts import retire
        retired=retire(self.doc(2),actor='test',reason='retired',base_version=1)
        self.write([old,retired]);self.assertEqual(self.repo.active_chunks(),[])
        self.assertEqual(self.repo.get_document('index-topic',1)['content'],old['content'])

    def test_removed_version_barrier_survives_restore(self):
        old=self.doc();self.setup_index([old]);self.write([])
        self.assertEqual(self.repo.active_chunks(),[]);self.index.rebuild();self.write([old]);self.index.rebuild()
        self.assertEqual(self.repo.active_chunks(),[])
        self.write([old,self.doc(2)]);self.index.rebuild();self.assertTrue(self.repo.active_chunks())

    def test_profile_change_preserves_chunks(self):
        self.setup_index();before=self.repo.get_document('index-topic',1)['chunks'];self.provider.dimensions=64
        self.index.rebuild();self.assertEqual(self.repo.get_document('index-topic',1)['chunks'],before)
        self.assertEqual(len(self.repo.active_chunks()[0]['embedding']),64)

    def test_bad_vector_count_rolls_back(self):
        old=self.doc();self.setup_index([old]);self.write([old,self.doc(2,title='new input')])
        @runtime_managed
        def bad(texts,*,run_context=None):return []
        self.provider.embed=bad
        with self.assertRaisesRegex(RuntimeFailure,'invalid_vector'):self.index.rebuild()
        self.assertIsNone(self.repo.get_document('index-topic',2))

    def test_source_changed_during_embedding_rolls_back(self):
        old=self.doc();self.setup_index([old]);new=self.doc(2,title='new input');self.write([old,new])
        self.provider.after=lambda:self.write([old,new,self.doc(3)])
        from app.rag.contracts import RagIndexConflict
        with self.assertRaisesRegex(RagIndexConflict,'source_changed'):self.index.rebuild()
        self.assertIsNone(self.repo.get_document('index-topic',2))

    def test_commit_guard_rolls_back_head_and_documents(self):
        old=self.doc();self.setup_index([old]);self.write([old,self.doc(2,title='new input')])
        from tests.model_runtime_check import Clock
        clock=Clock();run=RunContext('rag-index',repository=self.runs,clock=clock,
            profile=replace(load_profile('rag-index',False),maxElapsedMs=10,attemptTimeoutMs=10))
        def slow(conn,cursor,statement,parameters,context,many):
            if 'INSERT INTO RAG_DOCUMENT' in statement.upper():clock.sleep(.02)
        event.listen(self.engine,'before_cursor_execute',slow)
        try:
            with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):self.index.rebuild(run_context=run)
        finally:event.remove(self.engine,'before_cursor_execute',slow)
        self.assertIsNone(self.repo.get_document('index-topic',2))

    def legacy_table(self, partial):
        with self.engine.begin() as c:
            c.execute(text('CREATE TABLE rag_document (pk TEXT PRIMARY KEY,document_id TEXT,version INTEGER,title TEXT,knowledge_type TEXT,status TEXT,content TEXT,metadata_json JSON,content_hash TEXT,active BOOLEAN,created_at TEXT,updated_at TEXT)'))
            c.execute(text("INSERT INTO rag_document VALUES ('old@1','old',1,'Old title','rule','reviewed','Historical body preserved','{}','old-hash',1,'then','then')"))
            c.execute(text('CREATE TABLE rag_chunk (chunk_id TEXT PRIMARY KEY,document_pk TEXT,chunk_index INTEGER,content TEXT)'))
            c.execute(text("INSERT INTO rag_chunk VALUES ('old@1#0','old@1',0,'Historical body preserved')"))
            if partial:c.execute(text('ALTER TABLE rag_document ADD COLUMN source_snapshot JSON'))

    def test_historical_get_before_or_partial_migration(self):
        from app.rag.contracts import RagIndexUnavailable
        for partial in (False,True):
            with self.subTest(partial=partial):
                self.legacy_table(partial);self.write([])
                from app.rag.source import KnowledgeSource
                repo=RagRepository(source=KnowledgeSource(self.path))
                old=repo.get_document('old',1);self.assertEqual(old['content'],'Historical body preserved')
                self.assertTrue(old['legacyUnknown'])
                with self.assertRaisesRegex(RagIndexUnavailable,'migration_not_ready'):repo.active_chunks()
                with self.engine.begin() as c:c.execute(text('DROP TABLE rag_chunk'));c.execute(text('DROP TABLE rag_document'))

    def test_migration_idempotent(self):
        from app.rag.migration import init_rag_index
        self.legacy_table(False);init_rag_index(self.engine);init_rag_index(self.engine)
        row=RagRepository().get_document('old',1);self.assertEqual(row['content'],'Historical body preserved');self.assertTrue(row['legacyUnknown'])

    def client(self, repo):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.rag.service import RagService
        from app.rag.answer import TemplateAnswerProvider
        service=RagService(repo,self.runs,self.provider,TemplateAnswerProvider())
        self.addCleanup(self._stop_patches)
        self.http_patch=patch('app.routers.RagService',return_value=service);self.http_patch.start()
        self.repo_patch=patch('app.routers.RagRepository',return_value=repo);self.repo_patch.start()
        return TestClient(app,raise_server_exceptions=False)

    def _stop_patches(self):
        if hasattr(self,'http_patch'):self.http_patch.stop()
        if hasattr(self,'repo_patch'):self.repo_patch.stop()

    def test_http_history_without_new_columns_and_search_503(self):
        from app.rag.source import KnowledgeSource
        for partial in (False,True):
            with self.subTest(partial=partial):
                self.legacy_table(partial);self.write([])
                client=self.client(RagRepository(source=KnowledgeSource(self.path)))
                response=client.get('/api/rag/documents/old?version=1')
                self.assertEqual(response.status_code,200);self.assertEqual(response.json()['document']['content'],'Historical body preserved')
                for route,body in [('/api/rag/search',{'query':'利润率口径'}),('/api/rag/answer',{'question':'利润率口径'})]:
                    response=client.post(route,json=body)
                    self.assertEqual(response.status_code,503);self.assertEqual(response.json()['detail']['reasonCode'],'migration_not_ready')
                self._stop_patches()
                with self.engine.begin() as c:c.execute(text('DROP TABLE rag_chunk'));c.execute(text('DROP TABLE rag_document'))

    def test_http_migration_conflict_is_503_version_conflict_409(self):
        self.setup_index();client=self.client(self.repo)
        self.write([self.doc(title='different immutable title')])
        response=client.post('/api/rag/index')
        self.assertEqual(response.status_code,409);self.assertEqual(response.json()['detail']['reasonCode'],'document_version_conflict')
        with self.engine.begin() as c:c.execute(text('UPDATE rag_document SET source_snapshot=NULL,source_version_hash=NULL'))
        response=client.post('/api/rag/index')
        self.assertEqual(response.status_code,503);self.assertEqual(response.json()['detail']['reasonCode'],'migration_conflict')

    def test_nonfinite_source_is_unavailable(self):
        self.setup_index();raw=self.doc();raw['invalid']=float('nan');self.write([raw])
        from app.rag.contracts import RagIndexUnavailable
        with self.assertRaisesRegex(RagIndexUnavailable,'source_unavailable'):self.repo.active_chunks()

    def test_corrupt_cached_input_hash_not_reused_or_returned(self):
        self.setup_index()
        from app.models import RagIndexProjection
        from app.rag.contracts import RagIndexUnavailable
        with db.make_session() as s:
            row=s.scalar(select(RagIndexProjection));chunks=deepcopy(row.chunks_json)
            chunks[0]['embedding_input_hash']='wrong-input-hash';row.chunks_json=chunks;s.commit()
        self.provider.inputs=0
        with self.assertRaisesRegex(RagIndexUnavailable,'index_corrupt'):self.index.rebuild()
        self.assertEqual(self.provider.inputs,0)
        with self.assertRaisesRegex(RagIndexUnavailable,'index_corrupt'):self.repo.active_chunks()

    def test_config_change_is_pending_until_rebuild(self):
        self.setup_index()
        with patch.dict('os.environ',{'DORA_RAG_HASH_DIMENSIONS':'64'}):
            self.assertEqual(self.repo.index_status()['indexStatus'],'pending')

    def test_patch_freezes_all_source_versions_of_requested_topic(self):
        old=self.doc();self.setup_index([old]);self.write([old,self.doc(2)])
        self.index.rebuild([old])
        self.assertEqual({c['version'] for c in self.repo.active_chunks()},{2})
        self.assertEqual(self.repo.get_document('index-topic',2)['content'],old['content'])

    def test_patch_rejects_unseen_divergent_or_absent_source_before_calls(self):
        from app.rag.contracts import RagIndexConflict
        self.setup_index();head=self.repo.index_store.read_snapshot()['head']
        official=self.doc(2,title='official');self.write([self.doc(),official]);self.provider.inputs=0
        for supplied in (self.doc(2,title='unofficial'),self.doc(3)):
            with self.subTest(version=supplied['version']):
                with self.assertRaisesRegex(RagIndexConflict,'document_version_conflict'):self.index.rebuild([supplied])
                self.assertEqual(self.provider.inputs,0)
                self.assertIsNone(self.repo.get_document('index-topic',supplied['version']))
                self.assertEqual(self.repo.index_store.read_snapshot()['head'],head)

    def test_partial_profile_patch_reports_remaining_pending_topic(self):
        a=self.doc();b=self.doc(id='another-topic',title='another input');self.setup_index([a,b])
        self.provider.dimensions=64
        result=self.index.rebuild([a])
        with patch.dict('os.environ',{'DORA_RAG_HASH_DIMENSIONS':'64'}):
            status=self.repo.index_status()
        self.assertEqual(status['indexStatus'],'pending');self.assertEqual(status['pendingCount'],1)
        self.assertEqual(result['pendingVersions'],1)

    def test_http_storage_read_errors_are_503_for_search_answer_and_history(self):
        from sqlalchemy.exc import OperationalError
        self.setup_index();client=self.client(self.repo)
        def fail(conn,cursor,statement,parameters,context,many):
            if statement.lstrip().upper().startswith('SELECT') and 'rag_' in statement:
                raise OperationalError(statement,parameters,Exception('injected storage read failure'))
        event.listen(self.engine,'before_cursor_execute',fail)
        try:
            for route,body in [('/api/rag/search',{'query':'利润率口径'}),('/api/rag/answer',{'question':'利润率口径'})]:
                response=client.post(route,json=body)
                self.assertEqual(response.status_code,503,response.text)
                self.assertEqual(response.json()['detail']['reasonCode'],'data_source_unavailable')
                run_id=response.json()['detail']['runId'];self.assertTrue(run_id)
                self.assertEqual(self.runs.get_agent_run(run_id)['output']['reasonCode'],'data_source_unavailable')
            response=client.get('/api/rag/documents/index-topic?version=1')
            self.assertEqual(response.status_code,503,response.text)
        finally:event.remove(self.engine,'before_cursor_execute',fail)

    def test_history_does_not_resolve_embedding_provider(self):
        from fastapi.testclient import TestClient
        from app.main import app
        self.setup_index()
        with patch.dict('os.environ',{'DORA_RAG_EMBEDDING_PROVIDER':'openai','DORA_RAG_OPENAI_API_KEY':'','OPENAI_API_KEY':''}):
            client=TestClient(app,raise_server_exceptions=False)
            response=client.get('/api/rag/documents/index-topic?version=1')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['document']['content'],self.doc()['content'])
            response=client.get('/api/rag/index/status')
            self.assertEqual(response.status_code,503,response.text)
            self.assertEqual(response.json()['detail']['reasonCode'],'configuration_error')

    def test_retained_chunk_prefix_collision_rejected_before_head_switch(self):
        from app.rag.identity import digest,canonical,profile_hash
        from app.rag.contracts import RagIndexUnavailable
        self.setup_index();state=self.repo.index_store.read_snapshot();old=next(iter(state['projections'].values()))
        candidate=deepcopy(old);candidate.pop('created_at');chunk=candidate['chunks_json'][0]
        body=chunk['content'][:-1];collision=chunk['content_hash'][:12]+digest(body)[12:]
        candidate['profile_json']['chunker']='test-alternate-chunker'
        candidate['profile_hash']=profile_hash({k:v for k,v in candidate['profile_json'].items() if k!='responseModel'})
        candidate['projection_id']='p-'+digest(canonical([candidate['document_pk'],candidate['profile_hash']]))
        chunk.update(content=body,content_hash=collision,embedding_input_hash=digest(chunk['title']+'\n'+body))
        manifest=deepcopy(state['manifest']);manifest['projections'][candidate['document_pk']]=candidate['projection_id']
        report={'sourceRevision':state['batch']['source_revision'],'embeddingProfileHash':candidate['profile_hash']}
        with patch('app.rag.index_store.digest',side_effect=lambda s:collision if s==body else digest(s)):
            with self.engine.connect() as connection:
                with self.assertRaisesRegex(RagIndexUnavailable,'chunk_identity_conflict'):
                    self.repo.index_store.commit_batch([], [candidate],manifest,report,expected_head=state['head'],commit_guard=lambda:None,connection=connection)
        self.assertEqual(self.repo.index_store.read_snapshot()['head'],state['head'])

    def test_empty_patch_dedup_and_inactive_versions(self):
        from app.wiki.contracts import retire
        a=self.doc();b=self.doc(id='same-input-topic')
        self.setup_index([a,b]);self.assertEqual(self.provider.inputs,1)
        self.provider.inputs=0;self.index.rebuild([])
        self.assertEqual({c['document_id'] for c in self.repo.active_chunks()},{a['id'],b['id']})
        inactive=[self.doc(id='future-topic',valid_from='2099-01-01'),self.doc(id='expired-topic',valid_to='2026-01-02'),
                  retire(self.doc(id='retired-topic'),actor='test',reason='retired',base_version=0)]
        draft_doc=draft();draft_doc['id']='draft-topic';inactive.append(draft_doc)
        self.write([a,b,*inactive]);self.index.rebuild()
        self.assertEqual(self.provider.inputs,0)
        for d in inactive:self.assertIsNotNone(self.repo.get_document(d['id'],d['version']))
        self.write([]);self.index.rebuild();self.assertEqual(self.repo.active_chunks(),[])

    def test_date_boundaries_and_reads_have_no_dml_or_embedding(self):
        old=self.doc(valid_from='2026-10-14',valid_to='2026-10-16')
        from datetime import datetime,timezone
        with patch('app.rag.source.datetime') as source_clock:
            source_clock.now.return_value=datetime(2026,10,14,12,tzinfo=timezone.utc)
            self.setup_index([old])
        self.provider.inputs=0;writes=[]
        def observe(conn,cursor,statement,parameters,context,many):
            if statement.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')):writes.append(statement)
        event.listen(self.engine,'before_cursor_execute',observe)
        try:
            for day,visible in [(date(2026,10,14),True),(date(2026,10,16),True),(date(2026,10,17),False)]:
                self.assertEqual(bool(self.repo.retrieval_snapshot(on_date=day)['chunks']),visible)
            self.repo.index_status();self.repo.get_document(old['id'],1)
        finally:event.remove(self.engine,'before_cursor_execute',observe)
        self.assertEqual(writes,[]);self.assertEqual(self.provider.inputs,0)

    def test_invalid_vectors_leave_valid_other_topic_and_old_head(self):
        from app.runtime.contracts import ProviderEnvelope
        from app.runtime.executor import managed_call
        a=self.doc();b=self.doc(id='healthy-topic',title='healthy');self.setup_index([a,b])
        head=self.repo.index_store.read_snapshot()['head'];self.write([a,b,self.doc(2,title='new input')])
        for fault in ('missing','extra','nan','dimension','model'):
            @runtime_managed
            def bad(texts,*,run_context=None):
                vectors=[[0.]*self.provider.dimensions for _ in texts]
                if fault=='missing':vectors=[]
                elif fault=='extra':vectors.append(vectors[0])
                elif fault=='nan':vectors[0][0]=float('nan')
                elif fault=='dimension':vectors[0]=[0.]
                return managed_call('rag-index',run_context,'index_embedding',self.provider,{'input':texts},
                    lambda attempt:ProviderEnvelope(vectors,responseModel='unexpected-model' if fault=='model' else None),output_tokens=0)
            self.provider.embed=bad
            with self.subTest(fault=fault),self.assertRaisesRegex(RuntimeFailure,'embedding_profile_mismatch' if fault=='model' else 'invalid_vector'):self.index.rebuild()
            self.assertEqual(self.repo.index_store.read_snapshot()['head'],head)
            self.assertIsNone(self.repo.get_document(a['id'],2))
            self.assertEqual({c['document_id'] for c in self.repo.active_chunks()},{b['id']})

    def test_invalid_query_vectors_and_response_model_use_lexical_fallback(self):
        from app.rag.service import RagService
        from app.rag.answer import TemplateAnswerProvider
        from app.runtime.contracts import ProviderEnvelope
        from app.runtime.executor import managed_call
        self.setup_index()
        for fault in ('missing','extra','nan','dimension','model'):
            @runtime_managed
            def bad(texts,*,run_context=None):
                vectors=[[0.]*self.provider.dimensions for _ in texts]
                if fault=='missing':vectors=[]
                elif fault=='extra':vectors.append(vectors[0])
                elif fault=='nan':vectors[0][0]=float('nan')
                elif fault=='dimension':vectors[0]=[0.]
                return managed_call('rag-search',run_context,'query_embedding',self.provider,{'input':texts},
                    lambda attempt:ProviderEnvelope(vectors,responseModel='unexpected-model' if fault=='model' else None),output_tokens=0)
            self.provider.embed=bad
            with self.subTest(fault=fault):
                result=RagService(self.repo,self.runs,self.provider,TemplateAnswerProvider()).search(self.doc()['title'])
                self.assertEqual(result.get('fallbackReason'),'embedding_profile_mismatch' if fault=='model' else 'invalid_vector')
                self.assertTrue(result['hits']);self.assertTrue(all(h['retrieval']=='lexical' and h['vector_score']==0 for h in result['hits']))

    def test_head_cas_and_sql_failure_leave_no_partial_batch(self):
        from app.rag.contracts import RagIndexConflict,RagIndexUnavailable
        from sqlalchemy.exc import OperationalError
        self.setup_index();state=self.repo.index_store.read_snapshot()
        with self.engine.connect() as connection:
            with self.assertRaisesRegex(RagIndexConflict,'head_changed'):
                self.repo.index_store.commit_batch([],[],state['manifest'],{},expected_head='stale-head',commit_guard=lambda:None,connection=connection)
        self.write([self.doc(),self.doc(2,title='new input')])
        def fail(conn,cursor,statement,parameters,context,many):
            if 'INSERT INTO RAG_INDEX_PROJECTION' in statement.upper():raise OperationalError(statement,parameters,Exception('injected persistence failure'))
        event.listen(self.engine,'before_cursor_execute',fail)
        try:
            with self.assertRaisesRegex(RagIndexUnavailable,'data_source_unavailable'):self.index.rebuild()
        finally:event.remove(self.engine,'before_cursor_execute',fail)
        self.assertEqual(self.repo.index_store.read_snapshot()['head'],state['head'])
        self.assertIsNone(self.repo.get_document('index-topic',2))

    def test_unreadable_or_unverifiable_source_closes_retrieval(self):
        from app.rag.contracts import RagIndexUnavailable
        self.setup_index()
        invalid=self.doc();invalid['content']+=' unreviewed edit'
        for body in ('not-json',json.dumps([invalid])):
            self.path.write_text(body)
            with self.assertRaisesRegex(RagIndexUnavailable,'source_unavailable'):self.repo.active_chunks()
            self.assertEqual(self.repo.get_document('index-topic',1)['content'],self.doc()['content'])
        self.path.unlink()
        with self.assertRaisesRegex(RagIndexUnavailable,'source_unavailable'):self.repo.active_chunks()

    def test_changed_chunker_retains_previous_references(self):
        from app.rag.identity import embedding_profile
        self.setup_index();old={c['chunk_id'] for c in self.repo.get_document('index-topic',1)['chunks']}
        profile=embedding_profile(self.provider);profile['chunker']='test-two-chunks-v2'
        with patch('app.rag.identity.embedding_profile',return_value=profile),patch('app.rag.indexer.split_text',side_effect=lambda body:[body[:100],body[100:]]):
            self.index.rebuild()
        current={c['chunk_id'] for c in self.repo.active_chunks()}
        self.assertTrue(current-old)
        self.assertTrue(old|current <= {c['chunk_id'] for c in self.repo.get_document('index-topic',1)['chunks']})

    def test_rag_migration_failure_does_not_disable_business_reads(self):
        from app.rag.contracts import RagIndexUnavailable
        with patch('app.rag.migration.init_rag_index',side_effect=RagIndexUnavailable('migration_not_ready')):
            with self.assertRaises(RagIndexUnavailable):db.init_db()
        db.require_business_ready(self.engine)

    def test_published_origin_removal_and_reuse_do_not_revive(self):
        self.setup_index()
        from app.models import ActionCase,ActionStep,KnowledgeArchive
        from app.repository import Repository
        from app.action import flow
        from app.wiki.candidates import CandidateService
        with db.make_session() as s:
            s.add(ActionCase(id='a06-case',kind='problem',case_title='来源案例',status='waiting_verify',origin='engine'))
            s.add(ActionStep(case_id='a06-case',seq=0,title='完成步骤',status='done'));s.commit()
        business=Repository();flow.verify(business,'a06-case','resolved',note='仅处理记录，无企业效果验证')
        candidates=CandidateService();candidate=candidates.list()[0]
        candidates.review(candidate['candidate_id'],actor='test',reason='report only',decision='approve',base_version=0)
        self.write([]);candidates.publish(candidate['candidate_id'],self.path);self.index.rebuild()
        self.assertTrue(self.repo.active_chunks())
        from app.models import KnowledgeCandidate
        with db.make_session() as s:
            row=s.scalar(select(KnowledgeArchive));original_body=row.content;row.content+=' changed after approval';s.commit()
        self.assertEqual(self.repo.active_chunks(),[])
        with db.make_session() as s:
            s.scalar(select(KnowledgeArchive)).content=original_body
            row=s.get(KnowledgeCandidate,candidate['candidate_id']);original_events=deepcopy(row.review_events)
            row.review_events=[*row.review_events,{'eventType':'source_deleted'}];s.commit()
        self.assertEqual(self.repo.active_chunks(),[])
        with db.make_session() as s:s.get(KnowledgeCandidate,candidate['candidate_id']).review_events=original_events;s.commit()
        self.assertTrue(self.repo.active_chunks())
        from sqlalchemy.exc import OperationalError
        from app.rag.contracts import RagIndexUnavailable
        def fail_origin(conn,cursor,statement,parameters,context,many):
            if statement.lstrip().upper().startswith('SELECT') and 'knowledge_candidate' in statement:
                raise OperationalError(statement,parameters,Exception('injected origin read failure'))
        event.listen(self.engine,'before_cursor_execute',fail_origin)
        try:
            with self.assertRaisesRegex(RagIndexUnavailable,'data_source_unavailable'):self.repo.active_chunks()
        finally:event.remove(self.engine,'before_cursor_execute',fail_origin)
        with db.make_session() as s:
            row=s.scalar(select(KnowledgeArchive));fields={k:getattr(row,k) for k in ('entry_type','source_id','code','title','content','note','created_at')}
        business.delete_action_case('a06-case');self.assertEqual(self.repo.active_chunks(),[])
        with db.make_session() as s:
            s.add(ActionCase(id='a06-case',kind='problem',case_title='来源案例',status='resolved',origin='engine'))
            s.add(KnowledgeArchive(**fields));s.commit()
        self.assertEqual(self.repo.active_chunks(),[])
        self.assertTrue(self.repo.get_document(candidate['payload']['id'],1)['content'])


if __name__=='__main__':unittest.main(verbosity=2)
