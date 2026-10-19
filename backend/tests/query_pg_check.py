"""Explicit A07 disposable PostgreSQL acceptance; never use the default URL."""
from __future__ import annotations
import os
import unittest
from datetime import date
from sqlalchemy import create_engine,text,event
from sqlalchemy.orm import Session
from app.models import Base,BusinessRevision,MetricSeries,RagIndexState,RagIndexBatch,KnowledgeArchive
from app.business_store import initialize_scope
from app.rag.migration import init_rag_index
from app.rag.source import KnowledgeSource
from app.query.contracts import ReadPolicy
from app.query.read_view import QueryReadViewReader
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.runtime.executor import RunContext
from tests.model_runtime_support import MemoryRuns

def require_disposable(env):
    from sqlalchemy.engine import make_url
    value=env.get('DATABASE_URL','');u=make_url(value)
    if not (u.drivername=='postgresql+psycopg' and u.host=='127.0.0.1' and u.port and u.username==u.database=='dora_a07'):
        raise ValueError('explicit disposable dora_a07 database required')
    return value

@unittest.skipUnless(os.environ.get('DORA_A07_PG_CHECK')=='1','explicit disposable PG only')
class PostgreSQLViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=create_engine(require_disposable(os.environ));Base.metadata.create_all(cls.engine);init_rag_index(cls.engine)
        with Session(cls.engine) as s:
            initialize_scope(s);state=s.get(BusinessRevision,'dora:default');state.source_manifest={'metric:margin':'uploaded'}
            
            if not s.get(RagIndexState,'repository-json'):s.add(RagIndexState(scope='repository-json',revision=0))
            else:s.get(RagIndexState,'repository-json').head_batch_id=None
            s.query(KnowledgeArchive).filter(KnowledgeArchive.source_id=='a07-mvcc').delete()
            s.add(KnowledgeArchive(entry_type='problem',source_id='a07-mvcc',title='利润率旧视图',content='旧记录。',code='',note='',created_at='old'))
            s.query(MetricSeries).delete();s.add(MetricSeries(metric_key='margin',dimension='全国',label='当前',unit='%',value=12));s.commit()
    @classmethod
    def tearDownClass(cls):cls.engine.dispose()
    def plan(self):return classify_query('利润率是什么，最新全国是多少？',Ontology.load(),on_date=date(2026,10,16))
    def test_same_mvcc_view_during_upload_and_head_switch(self):
        previous=[];fired=[]
        with self.engine.connect() as c:old=c.scalar(text('SELECT generation FROM business_revision'));head=c.scalar(text("SELECT revision FROM rag_index_state WHERE scope='repository-json'"))
        def after(conn,cursor,statement,parameters,context,many):
            if not fired and statement.startswith('SELECT metric_series'):
                fired.append(1)
                with self.engine.begin() as writer:
                    writer.execute(text('UPDATE business_revision SET generation=generation+1'))
                    writer.execute(text('UPDATE metric_series SET value=99'))
                    writer.execute(text("INSERT INTO rag_index_batch (batch_id,source_revision,profile_hash,manifest_json,report_json,created_at) VALUES ('b-a07-concurrent',:sha,:sha,:manifest,'{}','') ON CONFLICT (batch_id) DO NOTHING"),{'sha':'f'*64,'manifest':'{"versions":{},"projections":{},"barriers":{}}'})
                    writer.execute(text("UPDATE rag_index_state SET revision=revision+1,head_batch_id='b-a07-concurrent' WHERE scope='repository-json'"))
                    writer.execute(text("DELETE FROM knowledge_archive WHERE source_id='a07-mvcc'"))
        event.listen(self.engine,'after_cursor_execute',after)
        try:view=QueryReadViewReader(self.engine,KnowledgeSource(),ReadPolicy()).capture(self.plan(),run_context=RunContext('unified-answer'))
        finally:event.remove(self.engine,'after_cursor_execute',after)
        self.assertTrue(fired);self.assertEqual(view.business.get_series('margin')[0]['value'],12)
        self.assertEqual(view.business._raw['generation'],old)
        self.assertEqual(view.indexState['revision'],head or 0)
        self.assertIsNone(view.indexState['head'])
        self.assertTrue(any(a['source_id']=='a07-mvcc' for a in view.archives))
    def test_statement_timeout_uses_remaining_budget(self):
        from dataclasses import replace
        r=RunContext('unified-answer');p=replace(r.profile,maxElapsedMs=1200,attemptTimeoutMs=1000)
        observed=[]
        def after(conn,cursor,statement,params,ctx,many):
            if statement.startswith('SELECT metric_series'):
                with conn.connection.cursor() as cur:cur.execute('SHOW statement_timeout');observed.append(cur.fetchone()[0])
        event.listen(self.engine,'after_cursor_execute',after)
        try:
            with r.limit_scope(p):QueryReadViewReader(self.engine,KnowledgeSource(),ReadPolicy()).capture(self.plan(),run_context=r)
        finally:event.remove(self.engine,'after_cursor_execute',after)
        self.assertTrue(observed);self.assertTrue(all(int(v.removesuffix('ms'))<=1200 for v in observed))
    def test_model_sees_closed_read_transaction(self):
        pool=self.engine.pool
        class Reader(QueryReadViewReader):
            def after_database(inner):self.assertEqual(pool.checkedout(),0)
        Reader(self.engine,KnowledgeSource(),ReadPolicy()).capture(self.plan(),run_context=RunContext('unified-answer'))
    def test_no_business_or_knowledge_dml(self):
        statements=[]
        def before(c,cu,s,p,ctx,m):statements.append(s)
        event.listen(self.engine,'before_cursor_execute',before)
        try:QueryReadViewReader(self.engine,KnowledgeSource(),ReadPolicy()).capture(self.plan(),run_context=RunContext('unified-answer'))
        finally:event.remove(self.engine,'before_cursor_execute',before)
        self.assertFalse([s for s in statements if s.lstrip().split()[0].upper() in ('INSERT','UPDATE','DELETE','CREATE','ALTER')])

    def test_real_statement_timeout_deadline_and_closed_transaction(self):
        from unittest.mock import patch
        from dataclasses import replace
        from app.runtime.contracts import RuntimeFailure
        p=classify_query('最新全国利润率是多少？',Ontology.load(),on_date=date(2026,10,16))
        run=RunContext('unified-answer');small=replace(run.profile,maxElapsedMs=150,attemptTimeoutMs=100)
        def slow(session,**kwargs):session.execute(text('SELECT pg_sleep(1)'))
        with run.limit_scope(small),patch('app.query.read_view.freeze_business_inputs',side_effect=slow):
            with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                QueryReadViewReader(self.engine,KnowledgeSource(),ReadPolicy()).capture(p,run_context=run)
        self.assertEqual(self.engine.pool.checkedout(),0)
        self.assertEqual(run.budget.invocations,0)
