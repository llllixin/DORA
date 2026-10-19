"""F04/F08: real disposable pools, controlled readiness and refresh failures."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool
from app import db
from app.models import Base
from app.business_store import init_business_revision
from app.repository import Repository, DataSourceUnavailableError
from app.runtime.budget import load_profile
from app.runtime.executor import RunContext
from app.runtime.contracts import RuntimeFailure, normalize_usage
from tests.model_runtime_support import MemoryRuns
from tests.model_runtime_check import Clock


def profile(route='reasoning-refresh'):
    return replace(load_profile(route, False), maxElapsedMs=10, attemptTimeoutMs=10)


class RuntimeBoundaryRepair(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dora-repair-runtime-')
        self.engine = create_engine('sqlite:///' + str(Path(self.tmp.name)/'test.sqlite'),
            poolclass=QueuePool, pool_size=1, max_overflow=0, pool_timeout=.2)
        self.previous = db._engine; db._engine = self.engine
        Base.metadata.create_all(self.engine); init_business_revision(self.engine)
        self.repo = Repository()

    def tearDown(self):
        self.engine.dispose(); db._engine = self.previous; self.tmp.cleanup()

    def bounded(self, operation, exception=Exception):
        start = time.monotonic()
        with self.assertRaises(exception) as raised: operation()
        elapsed = time.monotonic() - start
        print(f'{self._testMethodName}: elapsed_ms={elapsed*1000:.2f}; exception={type(raised.exception).__name__}:{raised.exception}', flush=True)
        self.assertLess(elapsed, .100, '10ms budget waited on configured 200ms QueuePool timeout')
        self.assertEqual(self.engine.pool.timeout(), .2, 'shared pool timeout must remain unchanged')
        return raised.exception

    def test_query_pool_checkout_uses_remaining_budget(self):
        from app.query.read_view import QueryReadViewReader
        with self.engine.connect():
            run = RunContext('unified-answer', repository=MemoryRuns(), profile=profile('unified-answer'))
            exc = self.bounded(lambda:QueryReadViewReader(self.engine,None).capture(
                SimpleNamespace(businessDate=None,sourceKinds=()),run_context=run))
        self.assertIsInstance(exc, RuntimeFailure)
        self.assertEqual(str(exc), 'deadline_exceeded')

    def test_cache_precheck_pool_checkout_uses_commit_guard(self):
        version = self.repo.read_business_inputs().business_version
        with self.engine.connect():
            run = RunContext('reasoning-refresh', repository=MemoryRuns(), profile=profile())
            exc = self.bounded(lambda:self.repo.commit_reasoning_if_current(version,'p1','unused',{},'template','fixture',commit_guard=run.budget.check))
        self.assertIsInstance(exc, RuntimeFailure)

    def test_evidence_readiness_pool_wait_shares_capture_deadline(self):
        from app.evidence.service import capture_transaction
        from app.evidence.deadline import CaptureDeadline
        from app.evidence.contracts import EvidenceError
        def capture():
            with capture_transaction(self.repo,deadline=CaptureDeadline(max_elapsed_ms=10)):pass
        with self.engine.connect(): exc = self.bounded(capture)
        self.assertIsInstance(exc,EvidenceError)
        self.assertEqual(str(exc),'evidence_capture_timeout')

    def test_graph_readiness_pool_wait_shares_query_deadline(self):
        from app.graph.service import GraphService
        from app.graph.contracts import GraphLimits,GraphError
        service = GraphService(self.engine,limits=GraphLimits(queryAdmissionMs=10))
        with self.engine.connect(): exc = self.bounded(service.status)
        self.assertIsInstance(exc,GraphError)
        self.assertEqual(str(exc),'graph_deadline')

    def test_graph_slow_readiness_cannot_start_source_work_after_expiry(self):
        from app.graph.service import GraphService
        from app.graph.contracts import GraphLimits,GraphError
        service=GraphService(self.engine,limits=GraphLimits(queryAdmissionMs=10))
        with patch('app.graph.service.require_graph_ready',side_effect=lambda *a,**k:time.sleep(.02)), patch.object(service.reader.source,'locked_snapshot') as source:
            with self.assertRaisesRegex(GraphError,'graph_deadline'):service.status()
        source.assert_not_called()

    def test_runtime_create_pool_wait_uses_new_run_deadline(self):
        with self.engine.connect():
            exc=self.bounded(lambda:RunContext('reasoning-refresh',repository=self.repo,profile=profile()))
        self.assertIsInstance(exc,RuntimeFailure)

    def test_runtime_audit_pool_wait_uses_shared_run_deadline(self):
        run=RunContext('reasoning-refresh',repository=self.repo,profile=replace(profile(),maxElapsedMs=100,attemptTimeoutMs=100))
        with self.engine.connect():
            run.budget.deadline=time.monotonic()+.01
            exc=self.bounded(lambda:run.emit({'type':'fixture'}))
        self.assertIsInstance(exc,RuntimeFailure)

    def test_owned_refresh_final_read_failure_records_terminal_and_usage(self):
        from app.reasoning.cache import refresh
        original = DataSourceUnavailableError('single transient final read failure')
        create=RunContext
        runs=[]
        def capture_run(*a,**k):
            run=create(*a,**k);run.usages.append(normalize_usage({'input_tokens':3,'output_tokens':2,'total_tokens':5},'responses',external_calls=1));runs.append(run);return run
        with patch('app.reasoning.cache.RunContext',side_effect=capture_run), patch.object(self.repo,'read_business_inputs',side_effect=original):
            with self.assertRaises(DataSourceUnavailableError) as raised:
                refresh(self.repo,[],{'businessVersion':{'versionStatus':'complete','revision':'fixture'}},provider=SimpleNamespace(kind='template',external=False))
        self.assertIs(raised.exception,original)
        row=self.repo.get_agent_run(runs[0].run_id)
        self.assertEqual(row['status'],'failed')
        self.assertEqual(row['output']['usage']['totalTokens'],5)
        self.assertEqual(row['output']['usage']['externalModelCalls'],1)
        self.assertEqual(row['output']['budget']['pendingAttempts'],0)

    def test_owned_refresh_terminal_event_failure_still_finishes_once(self):
        from app.reasoning.cache import refresh
        from app.db_budget import current_budget
        for original,status in [(DataSourceUnavailableError('single final read failure'),'failed'),
                                (RuntimeFailure('deadline_exceeded'),'limited')]:
            with self.subTest(status=status):
                class EventFailureRuns(MemoryRuns):
                    def __init__(self):super().__init__();self.finishes=[];self.recording_budgets=[]
                    def append_agent_run_event(self,key,event):
                        if event['type']=='model_run_finished':
                            self.recording_budgets.append(current_budget())
                            raise RuntimeError('transient terminal event append failure')
                        return super().append_agent_run_event(key,event)
                    def finish_agent_run(self,key,state,output):
                        self.finishes.append((key,state,output));self.recording_budgets.append(current_budget())
                        return super().finish_agent_run(key,state,output)
                    def read_business_inputs(self):raise original
                repo=EventFailureRuns();runs=[]
                def capture(*a,**k):
                    run=RunContext(*a,**k)
                    run.usages.append(normalize_usage({'input_tokens':3,'output_tokens':2,'total_tokens':5},'responses',external_calls=1))
                    runs.append(run);return run
                with patch('app.reasoning.cache.RunContext',side_effect=capture):
                    with self.assertRaises(type(original)) as raised:
                        refresh(repo,[],{'businessVersion':{'versionStatus':'complete','revision':'fixture'}},provider=SimpleNamespace(kind='template',external=False))
                self.assertIs(raised.exception,original)
                self.assertEqual(len(repo.finishes),1)
                row=repo.get_agent_run(runs[0].run_id)
                self.assertEqual(row['status'],status)
                self.assertEqual(row['output']['usage']['totalTokens'],5)
                self.assertEqual(row['output']['usage']['externalModelCalls'],1)
                self.assertIs(repo.recording_budgets[0],repo.recording_budgets[1],'terminal sinks must share one cleanup allowance')
                self.assertTrue(runs[0].finished)

    def test_done_terminal_event_failure_retains_strict_audit_semantics(self):
        class EventFailureRuns(MemoryRuns):
            def __init__(self):super().__init__();self.finishes=0
            def append_agent_run_event(self,key,event):
                if event['type']=='model_run_finished':raise RuntimeError('terminal event failure')
                return super().append_agent_run_event(key,event)
            def finish_agent_run(self,*args):self.finishes+=1;return super().finish_agent_run(*args)
        repo=EventFailureRuns();run=RunContext('reasoning-refresh',repository=repo)
        with self.assertRaisesRegex(RuntimeError,'terminal event failure'):run.finish({},'done')
        self.assertEqual(repo.finishes,0)
        self.assertFalse(run.finished)

    def test_parent_refresh_failure_does_not_finish_shared_run(self):
        from app.reasoning.cache import refresh
        repo=MemoryRuns();repo.read_business_inputs=lambda:(_ for _ in ()).throw(DataSourceUnavailableError('temporary'))
        run=RunContext('reasoning-refresh',repository=repo)
        with self.assertRaises(DataSourceUnavailableError):
            refresh(repo,[],{'businessVersion':{'versionStatus':'complete','revision':'fixture'}},provider=SimpleNamespace(kind='template',external=False),run_context=run)
        self.assertEqual(repo.get_agent_run(run.run_id)['status'],'running')
        self.assertFalse(run.finished)
    def test_prepare_session_logical_transaction_pool_wait_is_bounded(self):
        from sqlalchemy.orm import Session
        from app.db_budget import prepare_session,RecordingBudget
        with self.engine.connect():
            with Session(self.engine) as session, session.begin() as transaction:
                budget=RecordingBudget(10)
                error=self.bounded(lambda:prepare_session(session,budget))
                self.assertIsInstance(error,RuntimeFailure)
                self.assertIs(session.get_transaction(),transaction)
                self.assertTrue(transaction.is_active)
                self.assertIs(session.bind,self.engine)
        self.assertEqual(self.engine.pool.checkedout(),0)

    def test_prepare_session_preserves_logical_transaction_commit_and_rollback(self):
        from sqlalchemy import text
        from sqlalchemy.orm import Session
        from app.db_budget import prepare_session,RecordingBudget
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE repair_budget_tx (value INTEGER)'))
        with Session(self.engine) as session:
            with session.begin() as transaction:
                prepare_session(session,RecordingBudget(1000))
                self.assertIs(session.get_transaction(),transaction)
                session.execute(text('INSERT INTO repair_budget_tx VALUES (1)'))
            self.assertFalse(session.in_transaction())
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT sum(value) FROM repair_budget_tx')),1)
        with Session(self.engine) as session:
            with self.assertRaisesRegex(ValueError,'rollback fixture'):
                with session.begin() as transaction:
                    prepare_session(session,RecordingBudget(1000))
                    self.assertIs(session.get_transaction(),transaction)
                    session.execute(text('INSERT INTO repair_budget_tx VALUES (2)'))
                    raise ValueError('rollback fixture')
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT sum(value) FROM repair_budget_tx')),1)
        self.assertEqual(self.engine.pool.checkedout(),0)

    def test_prepare_session_reuses_already_enlisted_transaction_connection(self):
        from sqlalchemy import text
        from sqlalchemy.orm import Session
        from app.db_budget import prepare_session,RecordingBudget
        with Session(self.engine) as session, session.begin() as transaction:
            first=session.connection()
            session.execute(text('CREATE TABLE repair_budget_existing (value INTEGER)'))
            prepare_session(session,RecordingBudget(1000))
            self.assertIs(session.connection(),first)
            self.assertIs(session.get_transaction(),transaction)
            session.execute(text('INSERT INTO repair_budget_existing VALUES (3)'))
        with self.engine.connect() as connection:
            self.assertEqual(connection.scalar(text('SELECT value FROM repair_budget_existing')),3)
        self.assertEqual(self.engine.pool.checkedout(),0)

    def test_owned_refresh_deadline_failure_records_limited_and_original_error(self):
        from app.reasoning.cache import refresh
        original=RuntimeFailure('deadline_exceeded');repo=MemoryRuns();runs=[]
        def fail():raise original
        repo.read_business_inputs=fail
        def capture(*a,**k):
            run=RunContext(*a,**k);runs.append(run);return run
        with patch('app.reasoning.cache.RunContext',side_effect=capture):
            with self.assertRaises(RuntimeFailure) as raised:
                refresh(repo,[],{'businessVersion':{'versionStatus':'complete','revision':'fixture'}},provider=SimpleNamespace(kind='template',external=False))
        self.assertIs(raised.exception,original)
        self.assertEqual(repo.get_agent_run(runs[0].run_id)['status'],'limited')
        self.assertEqual(repo.get_agent_run(runs[0].run_id)['output']['budget']['pendingAttempts'],0)

    def test_owned_refresh_recording_failure_preserves_original_read_exception(self):
        from app.reasoning.cache import refresh
        original=DataSourceUnavailableError('original business failure');repo=MemoryRuns()
        def fail():raise original
        repo.read_business_inputs=fail
        repo.finish_agent_run=lambda *a,**k:(_ for _ in ()).throw(RuntimeError('independent terminal recording failure'))
        with self.assertRaises(DataSourceUnavailableError) as raised:
            refresh(repo,[],{'businessVersion':{'versionStatus':'complete','revision':'fixture'}},provider=SimpleNamespace(kind='template',external=False))
        self.assertIs(raised.exception,original)



class PsycopgBoundaryRepair(unittest.TestCase):
    def wire_listener(self, backlog):
        import socket
        # Exercise libpq's real startup/query protocol without platform TCP
        # setup spending the 50/100ms operation budget before local accept.
        # /tmp also keeps the Unix socket path below the platform length limit.
        directory=tempfile.TemporaryDirectory(dir='/tmp',prefix='dora-wire-')
        self.addCleanup(directory.cleanup)
        listener=socket.socket(socket.AF_UNIX)
        self.addCleanup(listener.close)
        listener.bind(str(Path(directory.name)/'.s.PGSQL.5432'))
        listener.listen(backlog);listener.settimeout(.5)
        return directory.name,listener

    def stalled_server(self, handshake):
        import struct
        from threading import Event, Thread
        endpoint,listener=self.wire_listener(1)
        stop=Event();accepted=Event();query_seen=Event()
        def serve():
            try:
                connection,_=listener.accept()
                with connection:
                    connection.settimeout(.5); accepted.set()
                    if handshake:
                        packet=connection.recv(65536)
                        def msg(kind,payload):return kind+struct.pack('!I',len(payload)+4)+payload
                        connection.sendall(msg(b'R',struct.pack('!I',0))+msg(b'S',b'client_encoding\x00UTF8\x00')+
                            msg(b'S',b'server_version\x0016.0\x00')+msg(b'S',b'integer_datetimes\x00on\x00')+msg(b'Z',b'I'))
                        if connection.recv(65536):query_seen.set()
                    stop.wait(.3)
            except (TimeoutError,OSError):pass
            finally:listener.close()
        thread=Thread(target=serve,name='repair-runtime-controlled-pg-endpoint');thread.start()
        return endpoint,stop,thread,accepted,query_seen

    def assert_stalled_pg_bounded(self,handshake):
        from app.db_budget import budget_connection
        # Initialize psycopg's local adapter/parameter caches before the timed I/O.
        from psycopg import Connection as PsycopgConnection
        PsycopgConnection._get_connection_params('', host='127.0.0.1')
        endpoint,stop,thread,accepted,query_seen=self.stalled_server(handshake)
        engine=create_engine(f'postgresql+psycopg://fixture:fixture@/fixture?host={endpoint}&sslmode=disable&connect_timeout=2',poolclass=QueuePool,pool_size=1,max_overflow=0)
        run=RunContext('unified-answer',repository=MemoryRuns(),profile=replace(profile('unified-answer'),maxElapsedMs=50,attemptTimeoutMs=50))
        start=time.monotonic()
        try:
            with self.assertRaises(Exception) as raised:
                with budget_connection(engine,run.budget):pass
            elapsed=time.monotonic()-start
            print(f'{self._testMethodName}: elapsed_ms={elapsed*1000:.2f}; accepted={accepted.is_set()}; first_sql={query_seen.is_set()}; exception={type(raised.exception).__name__}:{raised.exception}',flush=True)
            self.assertTrue(accepted.is_set())
            if handshake:self.assertTrue(query_seen.is_set(),'must reach actual first SQL wait')
            self.assertLess(elapsed,.15,'50ms deadline must bound libpq connection and first SQL waits')
            self.assertIsInstance(raised.exception,RuntimeFailure)
            self.assertEqual(engine.pool.checkedout(),0)
        finally:
            stop.set();thread.join(1);engine.dispose()
            self.assertFalse(thread.is_alive(),'test endpoint must not leak a thread')

    def rollback_server(self):
        import struct
        from threading import Event,Thread
        endpoint,listener=self.wire_listener(2)
        stop=Event();rollback_seen=Event();queries=[]
        def read(connection,size):
            result=b''
            while len(result)<size:
                chunk=connection.recv(size-len(result))
                if not chunk:raise EOFError
                result+=chunk
            return result
        def message(kind,payload):return kind+struct.pack('!I',len(payload)+4)+payload
        def serve():
            stalled=False
            try:
                while not stop.is_set():
                    connection,_=listener.accept()
                    try:
                        with connection:
                            connection.settimeout(.5)
                            length=struct.unpack('!I',read(connection,4))[0];read(connection,length-4)
                            connection.sendall(message(b'R',struct.pack('!I',0))+message(b'S',b'client_encoding\x00UTF8\x00')+
                                message(b'S',b'server_version\x0016.0\x00')+message(b'S',b'integer_datetimes\x00on\x00')+message(b'Z',b'I'))
                            body_seen=False
                            while not stop.is_set():
                                kind=read(connection,1);length=struct.unpack('!I',read(connection,4))[0];payload=read(connection,length-4)
                                if kind==b'X':break
                                if kind!=b'Q':raise ValueError('fixture expects simple queries')
                                sql=payload.rstrip(b'\x00').decode();queries.append(sql)
                                body_seen=body_seen or sql=='SELECT 1'
                                rollback=sql=='ROLLBACK'
                                if rollback and body_seen and not stalled:
                                    stalled=True;rollback_seen.set();stop.wait(.25)
                                tag='ROLLBACK' if rollback else 'SELECT 1' if sql=='SELECT 1' else 'BEGIN' if sql=='BEGIN' else 'SET'
                                connection.sendall(message(b'C',tag.encode()+b'\x00')+message(b'Z',b'I' if rollback else b'T'))
                    except (EOFError,TimeoutError,OSError):pass
            except (TimeoutError,OSError):pass
            finally:listener.close()
        thread=Thread(target=serve,name='repair-runtime-rollback-endpoint');thread.start()
        return endpoint,stop,thread,rollback_seen,queries

    def assert_rollback_bounded(self,body_error=False):
        from sqlalchemy import text
        from app.db_budget import budget_connection,RecordingBudget
        endpoint,stop,thread,rollback_seen,queries=self.rollback_server()
        engine=create_engine(f'postgresql+psycopg://fixture:fixture@/fixture?host={endpoint}&sslmode=disable',poolclass=QueuePool,pool_size=1,max_overflow=0)
        engine.dialect.initialize=lambda connection:None
        original=ValueError('body failure must survive rollback timeout')
        error=None;started=time.monotonic()
        try:
            try:
                with budget_connection(engine,RecordingBudget(100)) as connection:
                    connection.execute(text('SELECT 1'))
                    if body_error:raise original
            except Exception as exc:error=exc
            elapsed=time.monotonic()-started
            print(f'{self._testMethodName}: elapsed_ms={elapsed*1000:.2f}; rollback_seen={rollback_seen.is_set()}; exception={type(error).__name__}:{error}',flush=True)
            self.assertTrue(rollback_seen.is_set(),'must reach actual cleanup ROLLBACK')
            self.assertLess(elapsed,.20,'cleanup rollback must share the100ms deadline')
            if body_error:self.assertIs(error,original)
            else:
                self.assertIsInstance(error,RuntimeFailure)
                self.assertEqual(str(error),'deadline_exceeded')
            self.assertEqual(engine.pool.checkedout(),0)
            # A timed-out checkin invalidates its socket; a later request can
            # acquire a fresh connection from the same bounded one-slot pool.
            with budget_connection(engine,RecordingBudget(1000)) as recovered:
                recovered.execute(text('SELECT 1'))
            self.assertEqual(engine.pool.checkedout(),0)
        finally:
            stop.set();engine.dispose();thread.join(1)
            self.assertFalse(thread.is_alive(),'controlled endpoint thread must be joined')

    def test_psycopg_cleanup_rollback_shares_deadline(self):self.assert_rollback_bounded()
    def test_psycopg_cleanup_timeout_preserves_body_exception(self):self.assert_rollback_bounded(True)

    def test_psycopg_initial_connect_has_subsecond_deadline(self):self.assert_stalled_pg_bounded(False)
    def test_psycopg_first_sql_has_subsecond_deadline(self):self.assert_stalled_pg_bounded(True)


if __name__=='__main__':unittest.main(verbosity=2)
