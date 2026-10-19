"""A03 real FastAPI handlers with a disposable SQLite database, plus singleflight."""
from concurrent.futures import ThreadPoolExecutor
import importlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from app import db
from app.main import app
from app.repository import Repository
from app.seed import run_seed


class BusinessAPI(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"DORA_REASONING_PROVIDER": "template", "DORA_LLM_API_KEY": "", "DORA_MODEL_EXTERNAL_ENABLED": "false"})
        self.environment.start()
        self.tmp = tempfile.TemporaryDirectory(prefix="dora-a03-api-")
        self.old = db._engine
        db._engine = create_engine("sqlite:///" + str(Path(self.tmp.name) / "test.sqlite"))
        db.init_db()
        self.client = TestClient(app, raise_server_exceptions=False)

    def tearDown(self):
        db._engine.dispose(); db._engine = self.old; self.tmp.cleanup(); self.environment.stop()

    def test_current_version_empty_and_details(self):
        response = self.client.get("/api/business/version")
        self.assertEqual(response.status_code, 200)
        version = response.json()
        self.assertEqual(version["versionStatus"], "complete")
        self.assertEqual(self.client.get("/api/insights?type=all").json(), [])
        empty = self.client.post("/api/reason/refresh").json()
        self.assertEqual(empty["updated"], [])
        self.assertEqual(empty["status"], "completed")
        run_seed()
        insight = self.client.get("/api/insights/p1").json()
        self.assertEqual(insight["insightTypeId"], "p1")
        self.assertIn("occurrenceId", insight)
        evidence = self.client.get("/api/evidence/p1", params={"revision": insight["businessVersion"]["revision"]})
        self.assertEqual(evidence.status_code, 200)
        self.assertEqual(evidence.json()["businessVersion"], insight["businessVersion"])

    def test_upload_mapped_revision_conflict_and_legacy_fields(self):
        run_seed()
        before = self.client.get("/api/insights/p1").json()
        csv = b"metric_key,label,value,dimension,unit\nmargin,2026-10-01,17,\xe5\x85\xa8\xe5\x9b\xbd,%\nmargin,2026-10-02,16,\xe5\x85\xa8\xe5\x9b\xbd,%\nmargin,2026-10-03,15,\xe5\x85\xa8\xe5\x9b\xbd,%\n"
        upload = self.client.post("/api/datasets", files={"file": ("new.csv", csv)})
        self.assertEqual(upload.status_code, 200, upload.text)
        body = upload.json()
        self.assertTrue({"ok", "name", "rows", "affectedMetrics", "updated", "businessVersion"} <= body.keys())
        self.assertNotEqual(body["businessVersion"]["dataRevision"], before["businessVersion"]["dataRevision"])
        for path in ["/api/evidence/p1", "/api/insights/p1"]:
            conflict = self.client.get(path, params={"revision": before["businessVersion"]["revision"]})
            self.assertEqual(conflict.status_code, 409, conflict.text)
            self.assertEqual(conflict.json()["detail"]["code"], "revision_conflict")
        mapped = self.client.post("/api/datasets/mapped", files={"file": ("mapped.csv", b"day,value\nW1,17\nW2,16\nW3,15\n")},
                                  data={"mapping": json.dumps(dict(metric_key="margin", label_column="day", value_column="value"))})
        self.assertEqual(mapped.status_code, 200, mapped.text)
        self.assertIn("businessVersion", mapped.json())
        current = self.client.get("/api/datasets/current").json()
        self.assertEqual(current["businessVersion"], mapped.json()["businessVersion"])
        self.assertIn("eventId", current["latest"])
        refreshed = self.client.post("/api/reason/refresh").json()
        self.assertTrue({"ok", "updated", "fallback", "provider", "discarded", "status", "businessVersion"} <= refreshed.keys())

    def test_missing_version_schema_is_503(self):
        with db.get_engine().begin() as connection:
            connection.execute(text("DROP TABLE business_revision"))
        self.assertEqual(self.client.get("/api/insights?type=all").status_code, 503)
        self.assertEqual(self.client.get("/api/business/version").status_code, 503)

    def test_revision_conflict_before_missing_insight(self):
        old = Repository().read_business_inputs().business_version["revision"]
        run_seed()
        response = self.client.get("/api/insights/nonexistent", params={"revision": old})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get("/api/insights/nonexistent").status_code, 404)

    def test_partial_migration_failure_blocks_existing_scope_and_writes(self):
        before = Repository().read_business_inputs().business_version
        with patch("app.db._backfill_watch_escalation", side_effect=RuntimeError("injected critical migration")):
            with self.assertRaises(RuntimeError): db.init_db()
        self.assertEqual(self.client.get("/api/business/version").status_code, 503)
        self.assertEqual(self.client.get("/api/engine/run").status_code, 503)
        from app.repository import DataSourceUnavailableError
        with self.assertRaises(DataSourceUnavailableError):
            Repository().upsert_rules([dict(key="margin.target", value="19", value_type="float")])
        db.init_db()
        self.assertEqual(Repository().read_business_inputs().business_version, before)

    def test_mapped_failure_rolls_back_and_scope_is_server_owned(self):
        run_seed()
        before = self.client.get("/api/datasets/current").json()
        other = self.client.get("/api/business/version", params={"scopeId": "other-scope"}).json()
        self.assertEqual(other["scopeId"], "dora:default")
        with patch.object(Repository, "upsert_data_update", side_effect=RuntimeError("injected event")):
            response = self.client.post("/api/datasets/mapped", files={"file": ("mapped.csv", b"day,value\nW1,17\nW2,16\nW3,15\n")},
                data={"mapping": json.dumps(dict(metric_key="margin", label_column="day", value_column="value"))})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(before, self.client.get("/api/datasets/current").json())

    def test_new_http_version_progresses_while_old_refresh_waits(self):
        from app.reasoning.provider import TemplateProvider
        run_seed()
        entered, release = Event(), Event()

        class Delayed(TemplateProvider):
            def explain(self, context, *, run_context=None):
                if not entered.is_set():
                    entered.set()
                    if not release.wait(5): raise RuntimeError("missing release")
                return super().explain(context, run_context=run_context)

        with patch("app.routers.resolve_provider", side_effect=Delayed), ThreadPoolExecutor(2) as pool:
            old = pool.submit(self.client.post, "/api/reason/refresh")
            try:
                self.assertTrue(entered.wait(5))
                Repository().upsert_rules([dict(key="margin.target", value="19", value_type="float")])
                new = pool.submit(self.client.post, "/api/reason/refresh")
                new_response = new.result(5)
                self.assertEqual(new_response.status_code, 200)
                self.assertEqual(new_response.json()["status"], "completed")
                self.assertFalse(old.done())
            finally:
                release.set()
            old_response = old.result(5)
        self.assertEqual(old_response.status_code, 200)
        self.assertEqual(old_response.json()["status"], "stale")
        self.assertIn("p1", old_response.json()["discarded"])


class Flights(unittest.TestCase):
    def test_version_partition_and_waiter_owns_result(self):
        self.assertIsNotNone(importlib.util.find_spec("app.reasoning.singleflight"), "A03 singleflight missing")
        SingleFlight = importlib.import_module("app.reasoning.singleflight").SingleFlight
        flights = SingleFlight()
        entered, release, joined, let_waiter_continue = Event(), Event(), Event(), Event()
        calls = []
        old = {"version": "old"}

        def generate_old():
            calls.append("old"); entered.set()
            if not release.wait(5): raise RuntimeError("missing release")
            return old

        def join_hook():
            joined.set()
            if not let_waiter_continue.wait(5): raise RuntimeError("missing waiter release")

        with ThreadPoolExecutor(3) as pool:
            first = pool.submit(flights.run, "V1", generate_old)
            self.assertTrue(entered.wait(5))
            waiter = pool.submit(flights.run, "V1", lambda: calls.append("unexpected"), on_join=join_hook)
            try:
                self.assertTrue(joined.wait(5))
                self.assertEqual(flights.run("V2", lambda: {"version": "new"}), {"version": "new"})
                self.assertFalse(first.done())
                release.set(); self.assertIs(first.result(5), old)
                self.assertEqual(flights.run("V1", lambda: {"version": "next"}), {"version": "next"})
            finally:
                release.set(); let_waiter_continue.set()
            self.assertIs(waiter.result(5), old)
        self.assertEqual(calls, ["old"])


if __name__ == "__main__":
    unittest.main()
