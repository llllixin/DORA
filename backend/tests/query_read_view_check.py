import unittest
from datetime import date
from dataclasses import replace
from sqlalchemy import text
from app.query.read_view import QueryReadViewReader,CaptureBudget
from app.query.contracts import ReadPolicy,ReadLimits,QueryConflict
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.runtime.executor import RunContext
from app.runtime.contracts import RuntimeFailure
from tests.query_test_support import query_fixture

class ReadViews(unittest.TestCase):
    def plan(self,q='最新全国利润率是多少？'):return classify_query(q,Ontology.load(),on_date=date(2026,10,16))
    def test_borrowed_connection_and_outer_transaction_survive(self):
        from app.rag.index_store import RagIndexStore
        with query_fixture([]) as f, f.engine.connect() as conn,conn.begin() as txn:
            conn.execute(text("UPDATE business_revision SET generation=2"))
            RagIndexStore().read_snapshot(connection=conn,documents=[])
            self.assertTrue(txn.is_active);self.assertEqual(conn.scalar(text('SELECT generation FROM business_revision')),2)
            txn.rollback()
        
    def test_view_is_private_no_live_reads(self):
        with query_fixture([]) as f:
            r=RunContext('unified-answer');view=QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now).capture(self.plan(),run_context=r)
            rows=view.business.get_series('margin');rows[0]['value']=999
            self.assertEqual(view.business.get_series('margin')[0]['value'],12)
            self.assertEqual(view.business.source_mode_for('margin'),'uploaded')
            with f.engine.begin() as c:c.execute(text('UPDATE metric_series SET value=99'))
            self.assertEqual(view.business.get_series('margin')[0]['value'],12)
            self.assertFalse(view.source)
    def test_read_limits_before_version_and_embedding(self):
        r=RunContext('unified-answer');b=CaptureBudget(ReadLimits(),r.budget)
        for n in range(10000):b.consume('t',{})
        with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):b.consume('t',{})
        b=CaptureBudget(ReadLimits(),r.budget);b.consume('t',{'text':'中'*699040})
        with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):b.consume('t',{'text':'中'*20})
    def test_source_changed_before_any_embedding(self):
        with query_fixture([]) as f:
            class Changing(QueryReadViewReader):
                def after_database(self):f.write_source(__import__('app.rag.contracts',fromlist=['load_documents']).load_documents())
            reader=Changing(f.engine,f.source,ReadPolicy(),now=f.now)
            with self.assertRaisesRegex(QueryConflict,'read_view_changed'):reader.capture(self.plan('利润率是什么？'),run_context=RunContext('unified-answer'))
    def test_midnight_uses_one_request_business_day(self):
        with query_fixture([]) as f:
            reader=QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now)
            view=reader.capture(self.plan('利润率是什么？'),run_context=RunContext('unified-answer'),read_at=f.now())
            self.assertEqual(view.source.business_date,date(2026,10,16));self.assertEqual(view.businessDate,date(2026,10,16))
    def test_logical_rag_unready_does_not_open_new_view(self):
        from app.rag.migration import _ready
        with query_fixture([]) as f:
            _ready[f.engine]=False
            view=QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now).capture(self.plan('利润率是什么，最新全国是多少？'),run_context=RunContext('unified-answer'))
            self.assertEqual(view.business.get_series('margin')[0]['value'],12)
            self.assertEqual(view.sourceStates['wiki']['reasonCode'],'migration_not_ready')
    def test_initial_and_recheck_file_lock_deadline(self):
        import subprocess,sys,time
        from dataclasses import replace
        with query_fixture([]) as f:
            children=[]
            def lock():
                code="import fcntl,sys,time; f=open(sys.argv[1],'a');fcntl.flock(f,fcntl.LOCK_EX);print('ready',flush=True);time.sleep(10)"
                child=subprocess.Popen([sys.executable,'-c',code,str(f.source.path)+'.lock'],stdout=subprocess.PIPE,text=True)
                self.assertEqual(child.stdout.readline().strip(),'ready');children.append(child)
            try:
                for stage in ('initial','recheck'):
                    r=RunContext('unified-answer');r.budget.deadline=r.budget.clock()+.2
                    class Reader(QueryReadViewReader):
                        def after_database(inner):
                            if stage=='recheck':lock()
                    if stage=='initial':lock()
                    started=time.monotonic()
                    with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
                        Reader(f.engine,f.source,ReadPolicy(),now=f.now).capture(self.plan('利润率是什么？'),run_context=r)
                    self.assertLess(time.monotonic()-started,.8);self.assertEqual(r.budget.invocations,0)
                    for c in children:c.terminate();c.wait();c.stdout.close()
                    children=[]
            finally:
                for c in children:c.terminate();c.wait();c.stdout.close()
    def test_bound_stops_before_complete_version_hash(self):
        from unittest.mock import patch
        with query_fixture([]) as f:
            r=RunContext('unified-answer')
            with patch('app.query.read_view.effective_limits',return_value=ReadLimits(maxReadViewRows=1)),patch('app.business_store.build_version',side_effect=AssertionError('must not hash truncated inputs')):
                with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):
                    QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now).capture(self.plan(),run_context=r)
            self.assertEqual(r.budget.invocations,0)
