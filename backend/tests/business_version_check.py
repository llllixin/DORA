"""A03 pure version/identity/frozen-input checks; no DB or network."""
from copy import deepcopy
import importlib
import importlib.util
from types import SimpleNamespace
import unittest
from unittest.mock import patch


def raw_inputs():
    return dict(scopeId="dora:default", sourceEpoch="test-epoch", generation=1,
                rows=[dict(metric_key="margin", label="W1", dimension="全国", unit="%", value=18.0)],
                clusters=[dict(store="s1", region="华东", aov=20.0)],
                event=dict(eventId=1, updated="same-time", rows_added=1, total_rows=1, metrics=["margin"]),
                rules={"margin.target": 18.5}, ruleRows=[dict(key="margin.target", value="18.5", value_type="float")],
                sourceManifest={"metric:margin": "sample", "cluster": "sample", "rules": "sample", "event": "sample"})


class BusinessVersions(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec("app.business_version"), "A03 version module is missing")
        return importlib.import_module("app.business_version")

    def test_canonical_order_numbers_and_nonfinite(self):
        m = self.module()
        self.assertEqual(m.canonical_hash({"b": 1.0, "a": -0.0}), m.canonical_hash({"a": 0, "b": 1}))
        for value in [float("nan"), float("inf"), float("-inf")]:
            with self.assertRaises(ValueError):
                m.canonical_hash({"bad": value})

    def test_complete_components_and_occurrence(self):
        m = self.module()
        raw = raw_inputs()
        base = m.build_version(raw)
        self.assertEqual(base["scopeId"], "dora:default")
        self.assertEqual(base["versionStatus"], "complete")
        self.assertEqual(base["provenanceStatus"], "simulated")
        self.assertEqual(m.build_version(deepcopy(raw)), base)
        for field, value in [("value", 17), ("label", "W2"), ("dimension", "门店X"), ("unit", "元")]:
            changed = deepcopy(raw); changed["rows"][0][field] = value
            self.assertNotEqual(m.build_version(changed)["dataRevision"], base["dataRevision"])
        historical = deepcopy(raw)
        historical["rows"].append({**historical["rows"][0], "label": "W2"})
        historical_version = m.build_version(historical)
        historical["rows"][0]["value"] = 10
        self.assertNotEqual(m.build_version(historical)["dataRevision"], historical_version["dataRevision"])
        changed = deepcopy(raw); changed["clusters"][0]["aov"] = 25
        self.assertNotEqual(m.build_version(changed)["dataRevision"], base["dataRevision"])
        changed = deepcopy(raw); changed["event"]["eventId"] = 2
        self.assertNotEqual(m.build_version(changed)["revision"], base["revision"])
        changed = deepcopy(raw); changed["rules"]["margin.target"] = 20
        self.assertNotEqual(m.build_version(changed)["ruleVersion"], base["ruleVersion"])
        changed = deepcopy(raw); changed["generation"] = 3
        self.assertNotEqual(m.occurrence_id(base, "p1"), m.occurrence_id(m.build_version(changed), "p1"))
        profile = {**m.reasoning_profile(), "model": "different"}
        other = m.build_version(raw, profile=profile)
        self.assertNotEqual(other["revision"], base["revision"])
        self.assertEqual(m.occurrence_id(other, "p1"), m.occurrence_id(base, "p1"))

    def test_frozen_rows_and_legacy_source(self):
        m = self.module()
        raw = raw_inputs(); raw["sourceManifest"] = {}
        version = m.build_version(raw)
        self.assertEqual(version["provenanceStatus"], "incomplete")
        frozen = m.FrozenBusiness(raw, version)
        raw["rows"][0]["value"] = 123
        rows = frozen.get_series("margin"); rows[0]["value"] = 999
        self.assertEqual(frozen.get_series("margin")[0]["value"], 18)
        version["generation"] = 99
        self.assertEqual(frozen.business_version["generation"], 1)

    def test_implementation_ontology_row_ids_and_source_changes(self):
        m = self.module()
        raw = raw_inputs(); base = m.build_version(raw)
        raw["rows"][0]["rowId"] = 999
        self.assertEqual(base, m.build_version(raw))
        raw["ruleImplementation"] = "new-release"
        self.assertNotEqual(base["ruleVersion"], m.build_version(raw)["ruleVersion"])
        raw["ontologyIdentity"] = "new-ontology:content-hash"
        self.assertNotEqual(base["ontologyVersion"], m.build_version(raw)["ontologyVersion"])
        raw["sourceManifest"]["metric:margin"] = "uploaded"
        other = m.build_version(raw)
        self.assertEqual(other["sourceMode"], "mixed")
        self.assertEqual(other["provenanceStatus"], "incomplete")

    def test_release_hash_includes_defaults_and_constants(self):
        m = self.module()
        def load(text):
            scope = {"__name__": "test_rule_release"}
            exec(compile(text, "same-release.py", "exec"), scope)
            return SimpleNamespace(**scope)
        first = load("THRESHOLD = 1\ndef breach(value, *, inclusive=True):\n    return value <= THRESHOLD if inclusive else value < THRESHOLD\n")
        changed_default = load("THRESHOLD = 1\ndef breach(value, *, inclusive=False):\n    return value <= THRESHOLD if inclusive else value < THRESHOLD\n")
        changed_constant = load("THRESHOLD = 2\ndef breach(value, *, inclusive=True):\n    return value <= THRESHOLD if inclusive else value < THRESHOLD\n")
        hashes = []
        try:
            for release in [first, changed_default, changed_constant]:
                m.loaded_code_hash.cache_clear()
                with patch.object(m.importlib, "import_module", return_value=release):
                    hashes.append(m.loaded_code_hash("test_rule_release"))
            self.assertEqual(len(set(hashes)), 3)
        finally:
            m.loaded_code_hash.cache_clear()

    def test_provider_profile_uses_captured_model_and_cap(self):
        m = self.module()
        from app.reasoning import llm
        with patch.dict(llm.os.environ, {"DORA_REASONING_PROVIDER": "llm", "DORA_LLM_MODEL": "old-model"}):
            original = m.reasoning_profile
            def change_after_capture(*args, **kwargs):
                llm.os.environ["DORA_LLM_MODEL"] = "new-model"
                return original(*args, **kwargs)
            with patch.object(m, "reasoning_profile", side_effect=change_after_capture):
                provider = llm.LLMProvider()
            self.assertEqual(provider._config()[2], "old-model")
            self.assertEqual(provider.profile["model"], "old-model")
            self.assertEqual(provider.profile["maxOutputTokens"], provider.budget_profile.maxOutputTokensPerCall)
            exposed = provider.profile
            exposed["model"] = "mutated-by-reader"
            self.assertEqual(provider.profile["model"], "old-model")

    def test_defaults_and_every_generation_profile_component(self):
        m = self.module()
        from app.engine.engine import RULE_DEFAULTS
        raw = raw_inputs(); base = m.build_version(raw)
        with patch.dict(RULE_DEFAULTS, {"margin.target": 21}):
            self.assertNotEqual(base["ruleVersion"], m.build_version(raw)["ruleVersion"])
        profile = m.reasoning_profile()
        for key in ["provider", "model", "endpointId", "promptHash", "templateHash", "providerHash", "temperature", "maxOutputTokens"]:
            changed = {**profile, key: "changed"}
            self.assertNotEqual(base["revision"], m.build_version(raw, changed)["revision"])


if __name__ == "__main__":
    unittest.main()
