"""Eight-fix PG regression, exact disposable target required before mutation."""
import os,time,unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from sqlalchemy import create_engine,event,select,text
from sqlalchemy.orm import Session
from app import db
from app.db_budget import budget_connection,RecordingBudget
from app.models import KnowledgeArchive
from app.repository import Repository
from app.seed import run_seed
from app.runtime.contracts import RuntimeFailure
from app.runtime.executor import RunContext
from app.query.read_view import QueryReadViewReader
from app.query.routing import classify_query
from app.rag.source import KnowledgeSource
from app.rag.ontology import Ontology
from app.graph.service import GraphService
from app.graph.models import GraphBuildMember,GraphState
from app.graph.contracts import GraphError
from tests.graph_test_support import open_case


def require_disposable(env=None):
    env=os.environ if env is None else env
    value=env.get('DATABASE_URL','');u=urlsplit(value)
    if not(u.scheme=='postgresql+psycopg' and u.hostname=='127.0.0.1' and u.port==55460 and
           u.username=='dora_repair' and u.path=='/dora_repair' and not u.query and not u.fragment):
        raise ValueError('explicit disposable dora_repair on 127.0.0.1:55460 required')
    return value

class RepairPostgres(unittest.TestCase):
    def setUp(self):
        self.url=require_disposable();self.engine=db.get_engine()
        with self.engine.begin() as c:
            c.execute(text('DROP SCHEMA public CASCADE'));c.execute(text('CREATE SCHEMA public'))
        db.init_db();run_seed();self.repo=Repository()
        self.tmp=TemporaryDirectory(prefix='dora-p2-pg-');path=Path(self.tmp.name)/'documents.json';path.write_text('[]');self.source=KnowledgeSource(path)
    def tearDown(self):self.tmp.cleanup()
    def test_read_admission_precedes_pg_payload_loading(self):
        with Session(self.engine) as s:
            s.add(KnowledgeArchive(entry_type='lesson',source_id='large',title='利润率',content='中'*1048576));s.commit()
        loaded=[]
        def observe(row,context):loaded.append(row)
        event.listen(KnowledgeArchive,'load',observe)
        try:
            plan=classify_query('利润率有哪些历史处理记录？',Ontology.load(),on_date=date(2026,10,18))
            with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):
                QueryReadViewReader(self.engine,self.source).capture(plan,run_context=RunContext('unified-answer'))
            self.assertEqual(loaded,[])
        finally:event.remove(KnowledgeArchive,'load',observe)
    def test_pool_timeout_uses_remaining_budget(self):
        engine=create_engine(self.url,pool_size=1,max_overflow=0,pool_timeout=2)
        try:
            with engine.connect():
                budget=RecordingBudget(30);started=time.monotonic()
                with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                    with budget_connection(engine,budget):pass
                self.assertLess(time.monotonic()-started,.25)
            self.assertEqual(engine.pool.checkedout(),0)
        finally:engine.dispose()
    def test_protocol_wait_stops_and_pool_recovers(self):
        engine=create_engine(self.url,pool_size=1,max_overflow=0)
        try:
            with engine.connect() as c:self.assertEqual(c.scalar(text('SELECT 1')),1)
            started=time.monotonic()
            with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                with budget_connection(engine,RecordingBudget(60)) as c:c.execute(text('SELECT pg_sleep(3)'))
            self.assertLess(time.monotonic()-started,.35);self.assertEqual(engine.pool.checkedout(),0)
            with engine.connect() as c:self.assertEqual(c.scalar(text('SELECT 1')),1)
        finally:engine.dispose()
    def test_new_budget_connection_can_be_reused_after_old_budget_expires(self):
        engine=create_engine(self.url,pool_size=1,max_overflow=0)
        try:
            budget=RecordingBudget(200)
            with budget_connection(engine,budget) as c:first=c.scalar(text('SELECT pg_backend_pid()'))
            budget.end=budget.clock()-1
            with engine.connect() as c:
                self.assertEqual(c.scalar(text('SELECT pg_backend_pid()')),first)
                c.execute(text('SELECT pg_sleep(0.25)'))
                self.assertEqual(c.scalar(text('SHOW statement_timeout')),'0')
            with budget_connection(engine,RecordingBudget(1000)) as c:self.assertEqual(c.scalar(text('SELECT 1')),1)
            self.assertEqual(engine.pool.checkedout(),0)
        finally:engine.dispose()
    def test_cache_scope_lock_precheck_has_deadline(self):
        version=self.repo.read_business_inputs().business_version
        with self.engine.connect() as c,c.begin():
            c.execute(text("SELECT * FROM business_revision WHERE scope_id='dora:default' FOR UPDATE"))
            budget=RecordingBudget(60);started=time.monotonic()
            with self.assertRaises(Exception) as error:
                self.repo.commit_reasoning_if_current(version,'p1','invalid',{},'template','now',commit_guard=budget.check)
            self.assertLess(time.monotonic()-started,.35)
            self.assertIn(type(error.exception).__name__,('RuntimeFailure','DataSourceUnavailableError'))
    def test_rejected_candidate_import_rolls_back_pg_version(self):
        from app.ingest import IngestCapacityError
        before=self.repo.read_business_inputs();items=[dict(metric_key='margin',label=str(n),dimension='中'*32,value=12,unit='%') for n in range(7000)]
        with self.assertRaises(IngestCapacityError):self.repo.import_dataset(items,dict(updated_at='capacity'))
        self.assertEqual(before.business_version,self.repo.read_business_inputs().business_version)
        self.assertEqual(before.export_inputs(),self.repo.read_business_inputs().export_inputs())
    def test_pg_missing_graph_member_never_reports_healthy(self):
        open_case(self.repo);service=GraphService(self.engine,self.source);built=service.sync()
        with self.engine.begin() as c:
            row=c.execute(select(GraphBuildMember.batch_id,GraphBuildMember.item_kind,GraphBuildMember.item_id).where(GraphBuildMember.batch_id==built['batchId'])).first()
            c.execute(text('DELETE FROM graph_build_member WHERE batch_id=:batch AND item_kind=:kind AND item_id=:item'),{'batch':row.batch_id,'kind':row.item_kind,'item':row.item_id})
        with self.assertRaises(GraphError):service.status()
        with self.engine.connect() as c:self.assertEqual(c.scalar(select(GraphState.head_batch_id)),built['batchId'])

if __name__=='__main__':unittest.main()
