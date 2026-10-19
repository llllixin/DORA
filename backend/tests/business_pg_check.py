"""A03 genuine PostgreSQL read-view/lock/process/rollback checks; disposable DB only."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from copy import deepcopy
import json
import os
from threading import Event, get_ident
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from sqlalchemy import event, select
from app import db
from app.business_version import reasoning_input_hash
from app.engine.engine import run_engine
from app.repository import Repository
from app.seed import run_seed


def require_disposable():
    url = urlsplit(os.environ.get("DATABASE_URL", ""))
    if not (url.scheme == "postgresql+psycopg" and url.hostname == "127.0.0.1" and url.port
            and url.username == "dora_a03" and url.path == "/dora_a03"):
        raise RuntimeError("A03 checks require explicit local disposable dora_a03 database")


class PostgreSQLVersions(unittest.TestCase):
    def setUp(self):
        require_disposable()
        run_seed()
        self.repo = Repository()

    def test_repeatable_read_while_writer_commits_between_tables(self):
        before = self.repo.read_business_inputs()
        started, done = Event(), Event()
        reader_thread = get_ident()
        interleaved = [False]
        errors = []

        def writer():
            if not started.wait(5): return
            try:
                Repository().upsert_cluster_stores([dict(store="华东高客单01", region="华北", aov=999)])
            except Exception as exc: errors.append(exc)
            finally: done.set()

        def after_select(connection, cursor, statement, params, context, many):
            if get_ident() == reader_thread and "FROM metric_series" in statement and not interleaved[0]:
                interleaved[0] = True
                self.assertEqual(connection.get_isolation_level(), "REPEATABLE READ")
                started.set()
                self.assertTrue(done.wait(5), "writer could not commit during reader view")

        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(writer)
            event.listen(db.get_engine(), "after_cursor_execute", after_select)
            try: frozen = self.repo.read_business_inputs()
            finally:
                event.remove(db.get_engine(), "after_cursor_execute", after_select)
                started.set()
            future.result(5)
        self.assertFalse(errors)
        self.assertTrue(interleaved[0])
        self.assertEqual(before.get_cluster_stores(), frozen.get_cluster_stores())
        self.assertEqual(before.business_version, frozen.business_version)
        self.assertNotEqual(frozen.business_version, self.repo.read_business_inputs().business_version)

    def test_scope_lock_blocks_old_cache_until_upload_commits(self):
        old = run_engine(self.repo)
        p1 = next(i for i in old["insights"] if i["id"] == "p1")
        began = Event()

        def old_write():
            began.set()
            return Repository().commit_reasoning_if_current(old["businessVersion"], "p1",
                reasoning_input_hash(p1, old["snapshot"]), p1["semantics"], "template", "fixture")

        with ThreadPoolExecutor(1) as pool:
            with self.repo.business_transaction() as tx:
                tx.upsert_rules([dict(key="margin.target", value="19", value_type="float")])
                future = pool.submit(old_write)
                self.assertTrue(began.wait(5))
                with self.assertRaises(TimeoutError): future.result(.2)
            self.assertEqual(future.result(5), "discarded")
        self.assertEqual(self.repo.count_rows("versioned_reasoning"), 0)

    def test_separate_process_old_commit_rejected(self):
        old = run_engine(self.repo)
        p1 = next(i for i in old["insights"] if i["id"] == "p1")
        payload = dict(version=old["businessVersion"], inputHash=reasoning_input_hash(p1, old["snapshot"]), semantics=p1["semantics"])
        code = """import json,sys
from app.repository import Repository
p=json.loads(sys.stdin.readline())
print('ready',flush=True)
print(Repository().commit_reasoning_if_current(p['version'],'p1',p['inputHash'],p['semantics'],'template','fixture'),flush=True)
"""
        child = None
        try:
            with self.repo.business_transaction() as tx:
                tx.upsert_rules([dict(key="margin.target", value="19", value_type="float")])
                child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                child.stdin.write(json.dumps(payload) + "\n"); child.stdin.flush()
                self.assertEqual(child.stdout.readline().strip(), "ready")
                self.assertIsNone(child.poll())
            out, errors = child.communicate(timeout=8)
            self.assertEqual(child.returncode, 0, errors)
            self.assertEqual(out.strip(), "discarded")
        finally:
            if child is not None and child.poll() is None: child.kill(); child.wait()

    def test_upload_failure_rolls_back_data_log_generation_and_cache(self):
        from app.reasoning.cache import refresh
        from app.reasoning.provider import TemplateProvider
        result = run_engine(self.repo)
        p1 = next(i for i in result["insights"] if i["id"] == "p1")
        self.assertEqual(refresh(self.repo, [p1], result["snapshot"], TemplateProvider())["updated"], ["p1"])
        before = self.repo.read_business_inputs().business_version
        count = self.repo.count_rows("data_update_log")
        with patch.object(Repository, "upsert_data_update", side_effect=RuntimeError("injected event failure")):
            with self.assertRaises(RuntimeError):
                self.repo.import_dataset([dict(metric_key="margin", label="W1", value=1, dimension="全国", unit="%")], {"updated_at": "fixture"})
        self.assertEqual(self.repo.read_business_inputs().business_version, before)
        self.assertEqual(self.repo.count_rows("data_update_log"), count)
        self.assertEqual(self.repo.count_rows("versioned_reasoning"), 1)

    def test_separate_process_same_version_commit_is_accepted(self):
        result = run_engine(self.repo)
        p1 = next(i for i in result["insights"] if i["id"] == "p1")
        payload = dict(version=result["businessVersion"], inputHash=reasoning_input_hash(p1, result["snapshot"]), semantics=p1["semantics"])
        code = """import json,sys
from app.repository import Repository
p=json.load(sys.stdin)
print(Repository().commit_reasoning_if_current(p['version'],'p1',p['inputHash'],p['semantics'],'template','fixture'))
"""
        child = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), capture_output=True, text=True, timeout=10)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.strip(), "updated")
        self.assertEqual(self.repo.count_rows("versioned_reasoning"), 1)


if __name__ == "__main__":
    unittest.main()
