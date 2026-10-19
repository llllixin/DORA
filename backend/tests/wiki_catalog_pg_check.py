"""A08 real PostgreSQL capture checks; exact disposable URL only."""
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from app.models import Base, RagIndexState, RagIndexBatch, RagIndexProjection, ActionCase, KnowledgeArchive
from app.rag.source import KnowledgeSource
from app.rag.identity import document_key, source_version_hash, profile_hash, embedding_profile
from app.rag.embeddings import HashEmbeddingProvider
from app.wiki.catalog import CatalogOptions, CatalogError, build_catalog
from app.wiki.catalog_store import CatalogStore, CatalogBudget
from tests.wiki_check import draft, reviewed

URL='postgresql+psycopg://dora_a08:dora_a08@127.0.0.1:55458/dora_a08'


def require_disposable():
    if os.environ.get('DATABASE_URL')!=URL:
        raise RuntimeError('exact guarded loopback dora_a08:55458 URL required')
    if os.environ.get('DORA_MODEL_EXTERNAL_ENABLED','').lower()!='false' or os.environ.get('DORA_RAG_EMBEDDING_PROVIDER','hash')!='hash':
        raise RuntimeError('external models must be disabled and embedding must be hash')


class CatalogPostgres(unittest.TestCase):
    def setUp(self):
        require_disposable()
        self.schema='a08_catalog_'+uuid4().hex[:12]
        self.admin=create_engine(URL)
        with self.admin.begin() as conn:conn.execute(text('CREATE SCHEMA '+self.schema))
        self.engine=create_engine(URL,connect_args={'options':'-csearch_path='+self.schema},pool_size=3,max_overflow=0)
        Base.metadata.create_all(self.engine)
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'documents.json'
        raw=draft();raw['id']='a08-catalog-pg';raw['valid_from']='2026-01-01';self.doc=reviewed(raw)
        self.write([self.doc]);self.source=KnowledgeSource(self.path)
        self.profile=profile_hash(embedding_profile(HashEmbeddingProvider()))
        self.reader=CatalogStore(self.engine,self.source,now=lambda:datetime(2026,10,18,tzinfo=ZoneInfo('Asia/Shanghai')))

    def tearDown(self):
        self.engine.dispose();self.temp.cleanup()
        with self.admin.begin() as conn:conn.execute(text('DROP SCHEMA '+self.schema+' CASCADE'))
        self.admin.dispose()

    def write(self,docs):self.path.write_text(json.dumps(docs,ensure_ascii=False))

    def head(self,batch_id):
        with Session(self.engine) as session:
            session.add(RagIndexBatch(batch_id=batch_id,source_revision=self.source.snapshot().revision,
                profile_hash=self.profile,manifest_json={'versions':{},'projections':{},'barriers':{}},report_json={},created_at='2026-10-18'))
            session.commit()

    def test_repeatable_read_head_switch_and_no_capture_writes(self):
        self.head('b-old');self.head('b-new')
        with Session(self.engine) as session:session.add(RagIndexState(scope='repository-json',head_batch_id='b-old',revision=1));session.commit()
        statements=[];switched=False;capture_connection=None
        def after(conn,cursor,statement,parameters,context,many):
            nonlocal switched,capture_connection
            if capture_connection is None:capture_connection=conn
            if conn is capture_connection:statements.append(statement.lower())
            if not switched and statement.startswith('SELECT rag_index_state.'):
                switched=True
                with self.engine.begin() as writer:writer.execute(text("UPDATE rag_index_state SET head_batch_id='b-new',revision=2"))
        event.listen(self.engine,'after_cursor_execute',after)
        try:snapshot=self.reader.capture()
        finally:event.remove(self.engine,'after_cursor_execute',after)
        self.assertTrue(switched);self.assertEqual(snapshot.index_head,'b-old');self.assertEqual(snapshot.batch['batch_id'],'b-old')
        self.assertEqual(self.reader.capture().index_head,'b-new')
        writes=[sql for sql in statements if sql.lstrip().startswith(('insert','update','delete','create','alter'))]
        self.assertEqual(writes,[])
        self.assertEqual(self.engine.pool.checkedout(),0)

    def test_vector_payload_is_not_fetched_or_admitted(self):
        key=document_key(self.doc);sha=source_version_hash(self.doc)
        with Session(self.engine) as session:
            session.add(RagIndexProjection(projection_id='p-large',document_pk=key,source_version_hash=sha,
                profile_hash=self.profile,profile_json={},chunks_json=[{'embedding':[1]*800000}],created_at='2026-10-18'))
            session.add(RagIndexBatch(batch_id='b-large',source_revision=self.source.snapshot().revision,
                profile_hash=self.profile,manifest_json={'versions':{},'projections':{key:'p-large'},'barriers':{}},report_json={},created_at='2026-10-18'))
            session.add(RagIndexState(scope='repository-json',head_batch_id='b-large',revision=1));session.commit()
        statements=[]
        def before(conn,cursor,statement,parameters,context,many):statements.append(statement.lower())
        event.listen(self.engine,'before_cursor_execute',before)
        try:packet=build_catalog(self.reader.capture(),CatalogOptions())
        finally:event.remove(self.engine,'before_cursor_execute',before)
        self.assertEqual(packet['total'],1);self.assertEqual(packet['indexStatus'],'in_sync')
        self.assertFalse(any('chunks_json' in sql for sql in statements))
        self.assertFalse(any(sql.lstrip().startswith(('insert','update','delete','create','alter')) for sql in statements))

    def test_remaining_sql_deadline_and_connection_return(self):
        with self.engine.connect() as blocker:
            transaction=blocker.begin();blocker.execute(text('LOCK TABLE rag_index_state IN ACCESS EXCLUSIVE MODE'))
            started=time.monotonic()
            try:
                with self.assertRaises(CatalogError):self.reader.capture(budget=CatalogBudget(.15))
                self.assertLess(time.monotonic()-started,1.)
            finally:transaction.rollback()
        self.assertEqual(self.engine.pool.checkedout(),0)
        self.assertEqual(build_catalog(self.reader.capture(),CatalogOptions())['total'],1)

    def test_origin_deletion_uses_one_mvcc_view(self):
        from app.wiki.candidates import capture
        from app.wiki.contracts import approve
        with Session(self.engine) as session:
            case=ActionCase(id='pg-catalog-case',status='resolved',origin='engine',created_at='2026-01-01')
            archive=KnowledgeArchive(entry_type='resolution',source_id=case.id,code='C',title='PG report',content='reported',note='unverified',created_at='2026-01-01')
            session.add_all([case,archive]);session.flush();candidate,_=capture(session,archive,case)
            candidate.payload=approve(candidate.payload,actor='test:pg',reason='report only',base_version=0)
            candidate.status='reviewed';doc=deepcopy(candidate.payload);session.commit()
        self.write([doc]);changed=False
        def after(conn,cursor,statement,parameters,context,many):
            nonlocal changed
            if not changed and statement.startswith('SELECT rag_index_state.'):
                changed=True
                with self.engine.begin() as writer:writer.execute(text("UPDATE knowledge_candidate SET review_events=CAST(:events AS JSON)"),{'events':json.dumps([{'eventType':'source_deleted'}])})
        event.listen(self.engine,'after_cursor_execute',after)
        try:before=build_catalog(self.reader.capture(),CatalogOptions())
        finally:event.remove(self.engine,'after_cursor_execute',after)
        after=build_catalog(self.reader.capture(),CatalogOptions())
        self.assertTrue(changed);self.assertEqual(before['total'],1);self.assertEqual(after['total'],0)
        self.assertEqual(before['sourceRevision'],after['sourceRevision']);self.assertNotEqual(before['catalogRevision'],after['catalogRevision'])
        self.assertEqual(self.engine.pool.checkedout(),0)

if __name__=='__main__':unittest.main()
