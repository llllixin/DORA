"""A01 pure contract/semantic acceptance; no database or model requests."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from app.rag.contracts import RagContractError, load_documents
from app.rag.ontology import Ontology

FIXTURES = Path(__file__).parent / "fixtures"


def candidate():
    return json.loads((FIXTURES / "ontology-v2.candidate.json").read_text())


def approved():
    raw = candidate()
    raw.update(reviewStatus="reviewed", ontologyVersion="dora-ontology-v2")
    return raw


class OntologyChecks(unittest.TestCase):
    def test_frozen_semantics(self):
        ontology = Ontology.from_dict(approved())
        cases = json.loads((FIXTURES / "ontology-semantic-cases.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"], query=case["query"]):
                out = ontology.resolve(case["query"], case["purpose"])
                self.assertEqual(out["semanticStatus"], case["expectedStatus"])
                self.assertEqual(set(out["conceptIds"]), set(case["expectedConceptIds"]))
                binding = out["metricBinding"]
                self.assertEqual(binding["metricKey"] if binding else None, case["expectedMetricKey"])
                self.assertEqual(binding["dimension"] if binding else None, case["expectedDimension"])

    def test_invalid_contracts_are_rejected(self):
        variants = []
        raw = approved(); raw["concepts"].append(deepcopy(raw["concepts"][0])); variants.append(raw)
        raw = approved(); raw["concepts"][1]["aliases"].append("利润占比"); variants.append(raw)
        raw = approved(); raw["relations"][0]["to"] = "region.east"; variants.append(raw)
        raw = approved(); raw["relations"][0]["sourceRefs"] = []; variants.append(raw)
        raw = approved(); raw["relations"][0]["from"] = "missing.id"; variants.append(raw)
        raw = approved(); raw["relations"][2]["from"], raw["relations"][2]["to"] = "metric.orders", "metric.east_orders"; variants.append(raw)
        raw = approved(); raw["relationTypes"][1]["symmetric"] = True; variants.append(raw)
        raw = approved(); raw["concepts"][0]["type"] = "InsightOccurrence"; variants.append(raw)
        raw = approved(); raw["concepts"][0]["metricBinding"]["metricKey"] = "store_cluster"; variants.append(raw)
        raw = approved(); raw["concepts"][0]["metricBinding"]["dimension"] = False; variants.append(raw)
        raw = approved(); raw["concepts"][0]["metricBinding"]["sourceUnit"] = ""; variants.append(raw)
        raw = approved(); raw["concepts"][0]["unexpected"] = True; variants.append(raw)
        raw = approved(); raw["dimensionPatterns"][0]["pattern"] = "["; variants.append(raw)
        raw = approved(); raw["schemaVersion"] = "999"; variants.append(raw)
        for index, raw in enumerate(variants):
            with self.subTest(invalid=index), self.assertRaises(RagContractError):
                Ontology.from_dict(raw)

    def test_candidate_is_not_loaded_as_published(self):
        with self.assertRaises(RagContractError):
            Ontology.from_dict(candidate())
        ontology = Ontology.from_dict(candidate(), allow_candidate=True)
        self.assertEqual(ontology.resolve("华东订单量", "metric")["metricBinding"]["metricKey"], "east_orders")

    def test_one_hop_direction_and_disabled_expansion(self):
        ontology = Ontology.from_dict(approved())
        east = ontology.expand("华东订单量")
        self.assertIn("metric.orders", east["related_concept_ids"])
        self.assertNotIn("metric.east_orders", ontology.expand("全国订单量")["related_concept_ids"])
        # Revenue -> margin is one hop; supplier_price needs a second hop and must not appear.
        related = ontology.expand("营收")["related_concept_ids"]
        self.assertIn("metric.margin", related)
        self.assertNotIn("metric.supplier_price", related)
        exact = ontology.expand("毛利率", enable_expansion=False)
        self.assertEqual(exact["semanticStatus"], "clarification_required")
        self.assertEqual(exact["terms"], [])
        self.assertEqual(ontology.expand("营收", enable_expansion=False)["related_concept_ids"], [])

    def test_multiple_and_conflicting_dimension_values(self):
        ontology = Ontology.from_dict(approved())
        for query in ["华东全国订单量", "门店08和门店16退货率", "供应商B与供应商C价格", "全国利润率和营收", "华东订单量和利润率"]:
            with self.subTest(query=query):
                self.assertEqual(ontology.resolve(query, "metric")["semanticStatus"], "clarification_required")
        compared = ontology.resolve("华东订单与全国订单是什么关系？", "knowledge")
        self.assertEqual(compared["semanticStatus"], "resolved")
        self.assertIsNone(compared["metricBinding"])

    def test_default_published_content_is_pinned(self):
        ontology = Ontology.load()
        self.assertEqual(ontology.version, "dora-ontology-v2")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ontology.json"
            raw = approved(); raw["concepts"][0]["meaning"] = "tampered content"
            path.write_text(json.dumps(raw, ensure_ascii=False))
            with self.assertRaises(RagContractError):
                Ontology.load(path)

    def test_knowledge_publication_retains_old_versions(self):
        documents = {(d["id"], d["version"]): d for d in load_documents()}
        previous = json.loads((FIXTURES / "knowledge-v1-retention.json").read_text())
        for old in previous:
            with self.subTest(document=old["id"]):
                self.assertEqual(documents[(old["id"], 1)], old)
                new = documents[(old["id"], 2)]
                self.assertEqual(new["status"], "reviewed")
                self.assertEqual(new["source_type"], "project")
                self.assertNotIn("毛利率", new["aliases"])
                self.assertNotIn("退款率", new["aliases"])


if __name__ == "__main__":
    unittest.main()
