"""A01 consumer acceptance, with only database/model boundaries replaced."""
import unittest

from app.rag.answer import TemplateAnswerProvider
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.ontology import Ontology
from app.rag.retrieval import HybridRetriever
from app.rag.service import RagService
from app.rag.evaluation import evaluate
from app.rag.contracts import load_eval_set
from tests.ontology_test_support import FileChunks, RunStore
from app.watch.parser import parse_watch_text
from app.runtime.executor import RunContext


class NoEmbedding(HashEmbeddingProvider):
    def embed(self, texts):
        raise AssertionError("semantic guard must stop before embedding")


class NoAnswer(TemplateAnswerProvider):
    def answer(self, question, context):
        raise AssertionError("semantic guard must stop before answer generation")


class NoChunks:
    def active_chunks(self, knowledge_types=None):
        raise AssertionError("semantic guard must stop before reading old alias metadata")


class MemoryRuns:
    def __init__(self):
        self.events = []
        self.output = None

    def create_agent_run(self, **kwargs):
        return {"id": "test-run"}

    def append_agent_run_event(self, run_id, event):
        self.events.append(event)
        return {"id": run_id, "events": self.events}

    def finish_agent_run(self, run_id, status, output):
        self.output = output
        return {"id": run_id, "status": status, "output": output}
        return {'id':run_id, 'status':status, 'output':output}


class IntegrationChecks(unittest.TestCase):
    def setUp(self):
        # Keep these semantic checks offline after runtime event recording was added.
        from unittest.mock import patch
        runtime = patch("app.runtime.records.default_repository", side_effect=MemoryRuns)
        runtime.start()
        self.addCleanup(runtime.stop)

    def service(self):
        return RagService(NoChunks(), MemoryRuns(), NoEmbedding(), NoAnswer(), Ontology.load())

    def test_clarification_blocks_providers_and_old_metadata(self):
        for query in ["今天毛利率是多少", "退款率定义", "全国退货率", "新品SKU指标是什么", "高价值门店定义", "最新华南订单量"]:
            with self.subTest(query=query):
                result = self.service().answer(query)
                self.assertEqual(result["status"], "clarification_required")
                self.assertEqual(result["citations"], [])
                self.assertEqual(result["retrieval"]["hits"], [])
                self.assertTrue(result["semantics"]["ambiguities"])

    def test_search_guard_is_in_retriever(self):
        retriever = HybridRetriever(NoChunks(), NoEmbedding(), Ontology.load())
        result = retriever.search("毛利率", run_context=RunContext('rag-search'))
        self.assertTrue(result["empty"])
        self.assertEqual(result["normalized"]["semanticStatus"], "clarification_required")

    def test_current_metric_hints_have_physical_scope(self):
        for query, key, dimension in [("今天全国利润率", "margin", "全国"), ("最新华东订单量", "east_orders", "华东"), ("当前门店08退货率", "returns", "门店08"), ("当前供应商B价格", "supplier_price", "供应商B")]:
            with self.subTest(query=query):
                out = self.service().answer(query)
                self.assertEqual(out["status"], "tool_required")
                self.assertEqual(out["tool"], "query_metric")
                self.assertEqual(out["tool_args"], {"metric_key": key, "dimension": dimension})
                self.assertEqual(out["citations"], [])

    def test_collection_cannot_fabricate_metric_tool(self):
        out = self.service().answer("当前门店集群")
        self.assertEqual(out["status"], "abstained")
        self.assertEqual(out["reasonCode"], "tool_unavailable")
        self.assertNotIn("tool", out)

    def test_metric_cannot_silently_discard_collection_request(self):
        for query in ["当前订单量和门店集群", "当前高客单门店占比和高客单门店"]:
            with self.subTest(query=query):
                out = self.service().answer(query)
                self.assertEqual(out["status"], "clarification_required")
                self.assertNotIn("tool", out)
        self.assertFalse(parse_watch_text("关注订单量和门店集群，连续三天下降")["ok"])

    def test_new_watch_inputs_keep_condition_and_frequency(self):
        result = parse_watch_text("帮我关注华东订单量，如果连续三天下降就提醒我")
        self.assertTrue(result["ok"])
        self.assertEqual(result["intent"]["metric_key"], "east_orders")
        self.assertEqual(result["intent"]["dimension"], "华东")
        self.assertEqual(result["intent"]["label"], "华东订单量")
        self.assertEqual(result["intent"]["condition"]["days"], 3)
        result = parse_watch_text("关注利润率，跌破18%就提醒我，每天 09:00 检查")
        self.assertTrue(result["ok"])
        self.assertEqual(result["intent"]["condition"]["ref"], 18.0)
        self.assertFalse(result["intent"]["condition_defaulted"])
        self.assertEqual(result["intent"]["frequency"], "daily 09:00")

    def test_watch_rejects_wrong_equivalence(self):
        for query in ["关注华东销售额，连续三天下降", "关注毛利，跌破18%", "关注大额订单占比", "关注新品增长", "关注华南订单量"]:
            with self.subTest(query=query):
                out = parse_watch_text(query)
                self.assertFalse(out["ok"])
                self.assertIsNone(out["intent"])
                self.assertTrue(out["unsupported"])

    def test_versioned_evaluation_keeps_legacy_result(self):
        embedding = HashEmbeddingProvider(256)
        service = RagService(FileChunks(embedding), RunStore(), embedding, TemplateAnswerProvider(), Ontology.load())
        modern = evaluate(service, "ontology-v2")
        legacy = evaluate(service, "legacy-v1")
        self.assertTrue(modern["passed"], modern["metrics"])
        self.assertFalse(legacy["passed"])
        self.assertEqual({row["id"] for row in modern["intentionalChanges"]}, {"q07", "q08"})
        original = {row["id"]: row for row in load_eval_set()}
        self.assertEqual(original["q07"]["expected_status"], "answered")
        self.assertEqual(original["q08"]["expected_status"], "answered")


if __name__ == "__main__":
    unittest.main()
