"""Real PG concurrency; refuses every database except the dedicated A05 one."""
import json,os,subprocess,sys,time,unittest
from concurrent.futures import ThreadPoolExecutor,TimeoutError
from threading import Event
from unittest.mock import patch
from urllib.parse import urlsplit
from sqlalchemy import select,func,text
from app import db
from app.repository import Repository
from app.models import BusinessRevision,WatchTarget,EvidenceSnapshot,EvidenceBinding
from app.business_version import SCOPE_ID
from app.evidence.repository import EvidenceRepository
from app.evidence.contracts import EvidenceError
from app.evidence.action import create_case_captured
from app.watch.evaluator import evaluate_one
from tests.evidence_test_support import raw_inputs


def require_disposable(env=None):
    env=os.environ if env is None else env
    value=env.get('DATABASE_URL','');u=urlsplit(value)
    if not (u.scheme=='postgresql+psycopg' and u.hostname=='127.0.0.1' and u.port==55457 and u.username=='dora_a05' and u.path=='/dora_a05' and not u.query and not u.fragment):
        raise ValueError('explicit isolated dora_a05 database at 127.0.0.1:55457 required')
    return value


class EvidencePostgresChecks(unittest.TestCase):
    def test_pause_must_recheck_terminal_state_after_capture(self):
        target=self.target();wrote,release=Event(),Event();original=Repository.add_watch_event
        def held(tx,*a,**kw):
            result=original(tx,*a,**kw);wrote.set();self.assertTrue(release.wait(4));return result
        with patch.object(Repository,'add_watch_event',held),ThreadPoolExecutor(2) as pool:
            evaluating=pool.submit(evaluate_one,Repository(),target);self.assertTrue(wrote.wait(3))
            pausing=pool.submit(Repository().set_watch_status,target['id'],'paused')
            try:
                with self.assertRaises(TimeoutError):pausing.result(.15)
            finally:release.set()
            self.assertEqual(evaluating.result(4)['kind'],'escalate')
            with self.assertRaises(ValueError):pausing.result(4)
        self.assertEqual(self.repo.get_watch_target(target['id'])['status'],'escalated')
    def setUp(self):
        require_disposable()
        from app.seed import run_seed
        run_seed();self.repo=Repository()
        self.original_cases={c['id'] for c in self.repo.list_action_cases()}
        self.original_targets={t['id'] for t in self.repo.list_watch_targets()}
    def tearDown(self):
        for case in self.repo.list_action_cases():
            if case['id'] not in self.original_cases:self.repo.delete_action_case(case['id'])
        for target in self.repo.list_watch_targets():
            if target['id'] not in self.original_targets:self.repo.delete_watch_target(target['id'])
    def target(self):return self.repo.create_watch_target('PG capture',dict(metric_key='margin',condition=dict(type='below',ref=100)))
    def count(self,model):
        with db.make_session() as s:return s.scalar(select(func.count()).select_from(model))
    def test_update_during_watch_does_not_mix_versions(self):
        from app.evidence import service
        target=self.target();frozen_at,release,writer=Event(),Event(),Event();old=self.repo.read_business_inputs().business_version
        original=service.freeze_business_inputs
        def freeze(*a,**kw):
            result=original(*a,**kw);frozen_at.set();self.assertTrue(release.wait(5));return result
        def update():
            writer.set()
            with Repository().business_transaction(source_mode='uploaded') as tx:tx.upsert_series(raw_inputs(margin=99)['rows'])
        with patch.object(service,'freeze_business_inputs',freeze),ThreadPoolExecutor(2) as pool:
            evaluating=pool.submit(evaluate_one,Repository(),target);self.assertTrue(frozen_at.wait(3));updating=pool.submit(update);self.assertTrue(writer.wait(3))
            try:
                with self.assertRaises(TimeoutError):updating.result(.15)
            finally:release.set()
            out=evaluating.result(5);updating.result(5)
        with db.make_session() as s:
            store=EvidenceRepository(s);binding=store.get_binding(out['event']['bindingId']);snapshot=store.get_snapshot(binding['snapshotId'])
        self.assertEqual(snapshot['factVersion']['generation'],old['generation']);self.assertNotEqual(snapshot['factVersion']['dataRevision'],self.repo.read_business_inputs().business_version['dataRevision'])
        self.assertNotEqual(out['event']['values']['cur'],99)
    def test_pause_delete_capture_are_serialized(self):
        target=self.target();before=self.count(EvidenceSnapshot)
        with db.make_session() as locker,ThreadPoolExecutor(1) as pool:
            row=locker.scalar(select(WatchTarget).where(WatchTarget.id==target['id']).with_for_update())
            future=pool.submit(evaluate_one,Repository(),target)
            try:
                with self.assertRaises(TimeoutError):future.result(.15)
            finally:row.status='paused';locker.commit()
            self.assertFalse(future.result(5)['hit'])
        self.assertEqual(self.count(EvidenceSnapshot),before);self.assertEqual(self.repo.list_watch_events(target['id']),[])
        self.repo.set_watch_status(target['id'],'watching');out=evaluate_one(self.repo,target);self.repo.delete_watch_target(target['id'])
        with db.make_session() as s:self.assertEqual(EvidenceRepository(s).get_binding(out['event']['bindingId'])['sourceStatus'],'deleted')
    def test_concurrent_process_opening_is_idempotent(self):
        revision=self.repo.read_business_inputs().business_version['revision']
        code="import json,sys; from app.repository import Repository; from app.evidence.action import create_case_captured; print(json.dumps(create_case_captured(Repository(),insight_type_id='p1',expected_revision=sys.argv[1])))"
        children=[subprocess.Popen([sys.executable,'-c',code,revision],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=os.environ.copy()) for _ in range(2)]
        outputs=[]
        for child in children:
            stdout,stderr=child.communicate(timeout=20);self.assertEqual(child.returncode,0,stderr);outputs.append(json.loads(stdout))
        self.assertEqual(outputs[0]['case']['id'],outputs[1]['case']['id']);self.assertEqual(sum(x['created'] for x in outputs),1)
    def test_step_verify_and_capture_lock_order(self):
        # Existing row-lock race injects a held step write and checks verify waits,
        # then checks rollback, resolved freeze and idempotent old-schema migration.
        from tests.action_atomic_check import main
        main()
    def test_scope_lock_deadline_rolls_back_capture(self):
        revision=self.repo.read_business_inputs().business_version['revision'];before=self.count(EvidenceBinding)
        with db.make_session() as locker,ThreadPoolExecutor(1) as pool:
            locker.scalar(select(BusinessRevision).where(BusinessRevision.scope_id==SCOPE_ID).with_for_update())
            start=time.monotonic();future=pool.submit(create_case_captured,Repository(),insight_type_id='p1',expected_revision=revision)
            with self.assertRaises(EvidenceError) as e:future.result(5)
            self.assertEqual(e.exception.code,'evidence_capture_timeout');self.assertLess(time.monotonic()-start,4)
            locker.rollback()
        self.assertEqual(self.count(EvidenceBinding),before)
    def test_statement_deadline_and_flush_fault_roll_back(self):
        from app.evidence.service import capture_transaction,persist_capture
        before=self.count(EvidenceSnapshot)
        with self.assertRaises(EvidenceError) as e:
            with capture_transaction(self.repo) as (tx,frozen,deadline):
                persist_capture(tx,frozen,deadline);deadline.prepare_session(tx._session);tx._session.execute(text('SELECT pg_sleep(2.1)'))
        self.assertEqual(e.exception.code,'evidence_capture_timeout');self.assertEqual(self.count(EvidenceSnapshot),before)
    def test_reset_delete_capture_serialization(self):
        from app.seed import run_seed
        target=self.target();out=evaluate_one(self.repo,target);binding_id=out['event']['bindingId']
        with ThreadPoolExecutor(2) as pool:
            reset=pool.submit(run_seed,reset_watch_events=True);deleted=pool.submit(Repository().delete_watch_target,target['id'])
            reset.result(5);self.assertTrue(deleted.result(5))
        with db.make_session() as s:self.assertEqual(EvidenceRepository(s).get_binding(binding_id)['sourceStatus'],'deleted')


if __name__=='__main__':unittest.main()
