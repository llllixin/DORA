"""A03 temporary SQLite transaction/cache checks; PG concurrency has its own gate."""
from copy import deepcopy
import os
import tempfile
from pathlib import Path
from threading import Event, Thread
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from app import db
from app.models import Base, VersionedReasoning
from app.repository import Repository
from app.engine.engine import run_engine, engine_evidence
from app.reasoning.cache import refresh
from app.reasoning.provider import ReasoningResult, TemplateProvider
from app.seed import run_seed


class BusinessStore(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"DORA_REASONING_PROVIDER": "template", "DORA_LLM_API_KEY": "", "DORA_MODEL_EXTERNAL_ENABLED": "false"})
        self.environment.start()
        self.tmp = tempfile.TemporaryDirectory(prefix="dora-a03-")
        self.old_engine = db._engine
        db._engine = create_engine("sqlite:///" + str(Path(self.tmp.name) / "test.sqlite"))
        Base.metadata.create_all(db._engine)
        self.repo = Repository()

    def tearDown(self):
        db._engine.dispose(); db._engine = self.old_engine; self.tmp.cleanup(); self.environment.stop()

    def require_version(self):
        self.assertTrue(hasattr(self.repo, "read_business_inputs"), "A03 repository version API missing")
        run_seed()
        return self.repo.read_business_inputs().business_version

    def test_direct_writes_generation_sources_and_aba(self):
        first = self.require_version()
        self.assertEqual(first["sourceMode"], "sample")
        self.repo.upsert_cluster_stores([dict(store="华东高客单01", region="华北", aov=3450)])
        second = self.repo.read_business_inputs().business_version
        self.assertGreater(second["generation"], first["generation"])
        self.assertNotEqual(second["dataRevision"], first["dataRevision"])
        self.assertEqual(second["provenanceStatus"], "incomplete")
        run_seed()
        third = self.repo.read_business_inputs().business_version
        self.assertEqual(first["sourceEpoch"], third["sourceEpoch"])
        self.assertGreater(third["generation"], second["generation"])
        self.assertNotEqual(first["revision"], third["revision"])
        self.repo.upsert_rules([dict(key="margin.target", value="19", value_type="float")])
        self.assertNotEqual(third["ruleVersion"], self.repo.read_business_inputs().business_version["ruleVersion"])

    def test_atomic_transaction_rollback_and_distinct_events(self):
        first = self.require_version()
        try:
            with self.repo.business_transaction(source_mode="uploaded") as tx:
                tx.delete_all_series(); tx.delete_all_updates()
                raise ValueError("injected event failure")
        except ValueError:
            pass
        self.assertEqual(first, self.repo.read_business_inputs().business_version)
        self.repo.upsert_data_update(dict(updated_at="same-time", rows_added=1, total_rows=1, metrics=["margin"]))
        one = self.repo.get_latest_update()
        self.repo.upsert_data_update(dict(updated_at="same-time", rows_added=1, total_rows=1, metrics=["margin"]))
        two = self.repo.get_latest_update()
        self.assertNotEqual(one["eventId"], two["eventId"])

    def test_frozen_engine_and_evidence_share_inputs(self):
        self.require_version()
        frozen = self.repo.read_business_inputs()
        first = run_engine(frozen)
        rows = self.repo.get_series("margin")
        self.repo.replace_series(["margin"], [dict(metric_key="margin", **{**row, "value": 17}) for row in rows])
        second = run_engine(frozen)
        self.assertEqual(first, second)
        p1 = next(i for i in second["insights"] if i["id"] == "p1")
        self.assertEqual(p1["chart"]["series"][0]["values"][-1], second["snapshot"]["margin"]["current"])
        evidence = engine_evidence("p1", frozen)
        self.assertEqual(evidence["businessVersion"], second["businessVersion"])
        self.assertEqual(evidence["occurrenceId"], p1["occurrenceId"])

    def test_late_explanation_discarded_and_current_cache_preserved(self):
        self.require_version()
        old = run_engine(self.repo)
        entered, release = Event(), Event()
        result = []

        class Delayed(TemplateProvider):
            def explain(self, context):
                entered.set()
                if not release.wait(5): raise RuntimeError("missing release")
                return super().explain(context)

        p1 = next(i for i in old["insights"] if i["id"] == "p1")
        worker = Thread(target=lambda: result.append(refresh(self.repo, [p1], old["snapshot"], Delayed())))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.repo.upsert_rules([dict(key="margin.target", value="19", value_type="float")])
            current = run_engine(self.repo)
            new_p1 = next(i for i in current["insights"] if i["id"] == "p1")
            written = refresh(self.repo, [new_p1], current["snapshot"], TemplateProvider())
            self.assertEqual(written["updated"], ["p1"])
        finally:
            release.set(); worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0]["discarded"], ["p1"])
        self.assertEqual(result[0]["updated"], [])
        self.assertEqual(result[0]["status"], "stale")
        read = next(i for i in run_engine(self.repo)["insights"] if i["id"] == "p1")
        self.assertIn("generatedAt", read)
        self.assertEqual(read["businessVersion"], current["businessVersion"])

    def test_legacy_cache_and_bad_numeric_output_ignored(self):
        self.require_version()
        baseline = run_engine(self.repo)
        p1 = next(i for i in baseline["insights"] if i["id"] == "p1")
        self.repo.upsert_reasoning("p1", {"old": True}, "llm", "old")
        self.assertNotIn("generatedAt", next(i for i in run_engine(self.repo)["insights"] if i["id"] == "p1"))

        class BadNumeric(TemplateProvider):
            def explain(self, context):
                result = super().explain(context)
                result.semantics["causeA"]["value"] = "999%"
                return result

        result = refresh(self.repo, [p1], baseline["snapshot"], BadNumeric())
        self.assertEqual(result["updated"], [])
        self.assertEqual(result["fallback"], ["p1"])

    def test_migration_idempotent_and_no_history_backfill(self):
        first = self.require_version()
        before = self.repo.get_action_case("p1")
        db.init_db(); db.init_db()
        self.assertEqual(first, self.repo.read_business_inputs().business_version)
        self.assertEqual(before, self.repo.get_action_case("p1"))
        self.assertNotIn("snapshotId", before)

    def test_keyword_writers(self):
        self.require_version()
        self.repo.upsert_series(items=[dict(metric_key="margin", label="W1", dimension="全国", value=17, unit="%")])
        self.repo.replace_series(metric_keys=["margin"], items=[dict(metric_key="margin", label="W2", dimension="全国", value=16, unit="%")])

    def test_sample_reset_removes_foreign_cluster(self):
        self.require_version()
        self.repo.upsert_cluster_stores([dict(store="extra-store", region="华北", aov=777)])
        run_seed()
        self.assertNotIn("extra-store", [row["store"] for row in self.repo.get_cluster_stores()])

    def test_model_change_during_generation_and_unversioned_no_calls(self):
        self.require_version()
        os.environ["DORA_REASONING_PROVIDER"] = "llm"
        os.environ["DORA_LLM_MODEL"] = "old-model"
        result = run_engine(self.repo)
        p1 = next(i for i in result["insights"] if i["id"] == "p1")

        class ChangeModel(TemplateProvider):
            kind = "llm"
            def explain(self, context):
                os.environ["DORA_LLM_MODEL"] = "new-model"
                return super().explain(context)

        out = refresh(self.repo, [p1], result["snapshot"], ChangeModel())
        self.assertEqual(out["discarded"], ["p1"])
        self.assertEqual(out["updated"], [])
        self.assertEqual(self.repo.count_rows("versioned_reasoning"), 0)
        calls = []
        class Counting(TemplateProvider):
            def explain(self, context):
                calls.append(True)
                return super().explain(context)
        unversioned = {k: v for k, v in result["snapshot"].items() if k != "businessVersion"}
        out = refresh(self.repo, [p1], unversioned, Counting())
        self.assertEqual(out["status"], "unversioned")
        self.assertEqual(calls, [])
        # A genuine legacy adapter also lacks the new run-record methods.
        class LegacyAdapter:
            pass
        legacy = refresh(LegacyAdapter(), [p1], unversioned, Counting())
        self.assertEqual(legacy["status"], "unversioned")
        self.assertEqual(legacy["fallback"], ["p1"])
        self.assertEqual(calls, [])

    def test_business_read_does_not_commit_borrowed_action(self):
        self.require_version()
        before = self.repo.get_action_case("p1")
        with self.assertRaises(RuntimeError):
            with self.repo.action_transaction("p1") as tx:
                tx.set_action_case_status("p1", "running")
                tx.read_business_inputs()
                raise RuntimeError("abort parent")
        self.assertEqual(before, self.repo.get_action_case("p1"))

    def test_exact_cache_metadata_and_same_key_upsert(self):
        self.require_version()
        result = run_engine(self.repo)
        p1 = next(i for i in result["insights"] if i["id"] == "p1")
        for _ in range(2):
            self.assertEqual(refresh(self.repo, [p1], result["snapshot"], TemplateProvider())["updated"], ["p1"])
        self.assertEqual(self.repo.count_rows("versioned_reasoning"), 1)
        with db.make_session() as session:
            row = session.execute(select(VersionedReasoning)).scalar_one()
            row.business_version = {**row.business_version, "scopeId": "other-scope"}
            session.commit()
        self.assertNotIn("generatedAt", next(i for i in run_engine(self.repo)["insights"] if i["id"] == "p1"))
        with db.make_session() as session:
            row = session.execute(select(VersionedReasoning)).scalar_one()
            row.business_version = result["businessVersion"]
            row.input_hash = "wrong-input"
            session.commit()
        self.assertNotIn("generatedAt", next(i for i in run_engine(self.repo)["insights"] if i["id"] == "p1"))


if __name__ == "__main__":
    unittest.main()
