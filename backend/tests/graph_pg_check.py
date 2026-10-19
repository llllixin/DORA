"""Real PG graph races; exact disposable database guard before every mutation."""
import json,os,subprocess,sys,unittest
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from threading import Event
from tempfile import TemporaryDirectory
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch
from sqlalchemy import text,select,func,event
from app import db
from app.repository import Repository
from app.seed import run_seed
from app.rag.source import KnowledgeSource
from app.graph.service import GraphService,BUILD_KEY
from app.graph.source import SourceReader
from app.graph.contracts import Budget,GraphError,GraphRequest,GraphLimits
from app.graph.models import GraphEntity,GraphBuildBatch
from app.models import EvidenceSnapshot
from tests.graph_test_support import open_case
from tests.evidence_test_support import raw_inputs


def require_disposable(env=None):
    env=os.environ if env is None else env
    value=env.get('DATABASE_URL','');u=urlsplit(value)
    if not (u.scheme=='postgresql+psycopg' and u.hostname=='127.0.0.1' and u.port==55459
            and u.username=='dora_a09' and u.path=='/dora_a09' and not u.query and not u.fragment):
        raise ValueError('explicit disposable dora_a09 role/database on 127.0.0.1:55459 required')
    return value


class GraphPostgres(unittest.TestCase):
    def setUp(self):
        require_disposable()
        with db.get_engine().begin() as c:
            c.execute(text('DROP SCHEMA public CASCADE'));c.execute(text('CREATE SCHEMA public'))
        db.init_db();run_seed();self.repo=Repository();self.opened=open_case(self.repo)
        self.folder=TemporaryDirectory(prefix='dora-a09-pg-');self.path=Path(self.folder.name)/'documents.json';self.path.write_text('[]')
        self.source=KnowledgeSource(self.path);self.service=GraphService(db.get_engine(),self.source)
    def tearDown(self):self.folder.cleanup()
    def count(self,model):
        with db.make_session() as s:return s.scalar(select(func.count()).select_from(model))
    def child(self,code):
        return subprocess.Popen([sys.executable,'-c',code,str(self.path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy())
    def test_two_process_sync_reuses_one_successful_batch(self):
        code='from tests.graph_pg_check import require_disposable;require_disposable();import sys,json;from app.graph.service import GraphService;from app.rag.source import KnowledgeSource;print(json.dumps(GraphService(source=KnowledgeSource(sys.argv[1])).sync()),flush=True)'
        processes=[self.child(code),self.child(code)]
        try:
            values=[]
            for child in processes:
                out,err=child.communicate(timeout=20);self.assertEqual(child.returncode,0,err);values.append(json.loads(out.splitlines()[-1]))
            self.assertEqual(values[0]['batchId'],values[1]['batchId']);self.assertEqual(sum(not v['unchanged'] for v in values),1)
            self.assertEqual(self.count(GraphBuildBatch),1)
        finally:
            for child in processes:
                if child.poll() is None:child.kill();child.communicate()
    def test_repeatable_read_does_not_mix_new_binding_with_old_snapshot(self):
        captured,release=Event(),Event();original=SourceReader._rows
        def held(reader,session,model,*a,**kw):
            result=original(reader,session,model,*a,**kw)
            if model is EvidenceSnapshot:captured.set();self.assertTrue(release.wait(5))
            return result
        with patch.object(SourceReader,'_rows',held),ThreadPoolExecutor(1) as pool:
            future=pool.submit(self.service.reader.capture,Budget());self.assertTrue(captured.wait(3))
            try:
                self.repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(self.repo)
            finally:release.set()
            view=future.result(6)
        self.assertEqual(len(view['snapshots']),1);self.assertEqual(len(view['bindings']),1)
        self.assertEqual(len(self.service.reader.capture(Budget())['snapshots']),2)
    def test_source_commit_after_projection_is_rejected_and_old_head_survives(self):
        from app.graph import service as module
        first=self.service.sync();at,release=Event(),Event();original=module.project
        def held(*a,**kw):
            value=original(*a,**kw);at.set();self.assertTrue(release.wait(5));return value
        with patch.object(module,'project',held),ThreadPoolExecutor(1) as pool:
            future=pool.submit(self.service.sync);self.assertTrue(at.wait(3))
            try:self.repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(self.repo)
            finally:release.set()
            with self.assertRaises(GraphError) as caught:future.result(6)
        self.assertEqual(caught.exception.code,'source_changed');self.assertEqual(self.service.status()['batchId'],first['batchId'])
    def test_scope_first_commit_blocks_source_writer_without_deadlock(self):
        locked,release,writer=Event(),Event(),Event();original=SourceReader.lock_sources
        def held(*a,**kw):
            original(*a,**kw);locked.set();self.assertTrue(release.wait(5))
        def update():writer.set();self.repo.upsert_series(raw_inputs(margin=17)['rows'])
        with patch.object(SourceReader,'lock_sources',held),ThreadPoolExecutor(2) as pool:
            build=pool.submit(self.service.sync);self.assertTrue(locked.wait(3));write=pool.submit(update);self.assertTrue(writer.wait(2))
            try:
                with self.assertRaises(TimeoutError):write.result(.1)
            finally:release.set()
            self.assertTrue(build.result(6)['batchId']);write.result(6)
    def test_advisory_wait_deadline_and_process_death_release(self):
        code=f'from tests.graph_pg_check import require_disposable;require_disposable();import sys;from app import db;from sqlalchemy import text;c=db.get_engine().connect();c.execute(text("SELECT pg_advisory_lock({BUILD_KEY})"));c.commit();print("locked",flush=True);sys.stdin.readline()'
        child=self.child(code)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            with self.assertRaises(GraphError) as error:self.service.sync(budget=Budget(120))
            self.assertEqual(error.exception.code,'graph_deadline')
            child.kill();child.communicate(timeout=5)
            self.assertTrue(self.service.sync()['batchId'])
        finally:
            if child.poll() is None:child.kill();child.communicate()
    def test_actual_flush_then_deadline_rolls_back_graph_and_head(self):
        clock=[0.0];budget=Budget(10000,clock=lambda:clock[0])
        def expire(conn,cursor,statement,*args):
            if statement.startswith('INSERT INTO graph_state'):clock[0]=11.0
        event.listen(db.get_engine(),'after_cursor_execute',expire)
        try:
            with self.assertRaises(GraphError) as error:self.service.sync(budget=budget)
            self.assertEqual(error.exception.code,'graph_deadline')
        finally:event.remove(db.get_engine(),'after_cursor_execute',expire)
        self.assertEqual(self.count(GraphBuildBatch),0);self.assertEqual(self.count(GraphEntity),0)
        first=self.service.sync()
        self.repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(self.repo);second=self.service.sync()
        self.assertNotEqual(first['batchId'],second['batchId'])
        with self.assertRaises(GraphError) as error:self.service.sync(expected_head=first['batchId'])
        self.assertEqual(error.exception.code,'head_changed')

    def test_publication_and_deletion_wait_for_graph_source_rows(self):
        from tests.graph_lifecycle_check import GraphLifecycle
        from app.wiki.candidates import CandidateService
        cid,candidate=GraphLifecycle().lesson(self.repo);svc=CandidateService()
        svc.review(candidate['candidate_id'],actor='test:reviewer',reason='concurrency fixture',decision='approve',base_version=0)
        original=SourceReader.lock_sources
        operations=[lambda:svc.publish(candidate['candidate_id'],path=self.path),lambda:self.repo.delete_action_case(cid)]
        for operation in operations:
            locked,release,started=Event(),Event(),Event()
            def held(*a,**kw):
                original(*a,**kw);locked.set();self.assertTrue(release.wait(5))
            def write():started.set();return operation()
            with patch.object(SourceReader,'lock_sources',held),ThreadPoolExecutor(2) as pool:
                build=pool.submit(self.service.sync);self.assertTrue(locked.wait(3))
                writer=pool.submit(write);self.assertTrue(started.wait(2))
                try:
                    with self.assertRaises(TimeoutError):writer.result(.1)
                finally:release.set()
                self.assertTrue(build.result(6)['batchId']);writer.result(6)
            self.assertEqual(self.service.status()['sourceState'],'pending')

    def test_source_and_file_lock_waits_share_build_deadline(self):
        import time
        from app.models import BusinessRevision
        from app.business_version import SCOPE_ID
        with db.make_session() as locker,ThreadPoolExecutor(1) as pool:
            locker.scalar(select(BusinessRevision).where(BusinessRevision.scope_id==SCOPE_ID).with_for_update())
            started=time.monotonic();future=pool.submit(self.service.sync,budget=Budget(150))
            try:
                with self.assertRaises(GraphError):future.result(3)
                self.assertLess(time.monotonic()-started,2)
            finally:locker.rollback()
        code='from tests.graph_pg_check import require_disposable;require_disposable();import sys,fcntl;from pathlib import Path;p=Path(sys.argv[1]);f=p.with_suffix(p.suffix+".lock").open("a");fcntl.flock(f,fcntl.LOCK_EX);print("locked",flush=True);sys.stdin.readline()'
        child=self.child(code)
        try:
            self.assertEqual(child.stdout.readline().strip(),'locked')
            with self.assertRaises(GraphError) as error:self.service.sync(budget=Budget(120))
            self.assertEqual(error.exception.code,'graph_deadline')
        finally:
            child.kill();child.communicate(timeout=5)
        self.assertEqual(self.count(GraphBuildBatch),0);self.assertTrue(self.service.sync()['batchId'])

    def test_reading_keeps_one_batch_while_another_build_switches_head(self):
        first=self.service.sync()
        with db.make_session() as s:root=next(r.data['id'] for r in s.scalars(select(GraphEntity)) if r.data['type']=='ActionCase')
        request=GraphRequest(entityId=root,includeSimulated=True)
        before=self.service.neighborhood(request);captured,release=Event(),Event();original=SourceReader.for_batch
        def held(*a,**kw):
            value=original(*a,**kw);captured.set();self.assertTrue(release.wait(5));return value
        with patch.object(SourceReader,'for_batch',held),ThreadPoolExecutor(1) as pool:
            reading=pool.submit(self.service.neighborhood,request);self.assertTrue(captured.wait(3))
            try:
                self.repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(self.repo)
                second=self.service.sync()
            finally:release.set()
            value=reading.result(6)
        self.assertNotEqual(second['batchId'],first['batchId']);self.assertEqual(value['batchId'],first['batchId'])
        self.assertEqual(value['nodes'],before['nodes']);self.assertEqual(value['relations'],before['relations'])

    def test_faults_at_each_graph_write_stage_leave_previous_head_intact(self):
        from app.graph.migrations import TABLES
        first=self.service.sync();counts=[self.count(model) for model in TABLES]
        self.repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(self.repo)
        for prefix in ('INSERT INTO graph_entity','INSERT INTO graph_relation_evidence','INSERT INTO graph_build_batch',
                       'INSERT INTO graph_build_member','UPDATE graph_state'):
            def fail(conn,cursor,statement,*a):
                if statement.startswith(prefix):raise RuntimeError('graph write stage fault')
            with self.subTest(stage=prefix):
                event.listen(db.get_engine(),'before_cursor_execute',fail)
                try:
                    with self.assertRaises(RuntimeError):self.service.sync()
                finally:event.remove(db.get_engine(),'before_cursor_execute',fail)
                self.assertEqual([self.count(model) for model in TABLES],counts)
                self.assertEqual(self.service.status()['batchId'],first['batchId'])

    def test_build_limit_and_sample_reset_preserve_old_batch_reads(self):
        from dataclasses import replace
        limited=GraphService(db.get_engine(),self.source,limits=replace(GraphLimits(),maxSnapshots=1));first=limited.sync()
        with db.make_session() as s:root=next(r.data['id'] for r in s.scalars(select(GraphEntity)) if r.data['type']=='ActionCase')
        request=GraphRequest(entityId=root,mode='historical',batchId=first['batchId'],includeSimulated=True)
        before=limited.neighborhood(request);run_seed(reset_watch_events=True)
        self.repo.upsert_series(raw_inputs(margin=17)['rows']);open_case(self.repo)
        with self.assertRaises(GraphError) as error:limited.sync()
        self.assertEqual(error.exception.code,'build_input_limit')
        after=limited.neighborhood(request)
        self.assertEqual(after['nodes'],before['nodes']);self.assertEqual(after['relations'],before['relations'])
        edge=next(e for e in after['relations'] if e['type']=='opened_from')
        self.assertTrue(limited.evidence(edge['id'],first['batchId'],include_simulated=True)['evidence'])
        self.assertEqual(limited.status()['batchId'],first['batchId'])


if __name__=='__main__':unittest.main()
