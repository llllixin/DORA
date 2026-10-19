"""A04 orchestration checks against explicit local fixtures and mock HTTP only."""
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch
from app.runtime.budget import load_profile
from app.runtime.contracts import RuntimeFailure
from app.runtime.executor import RunContext
from app.rag.answer import OpenAIAnswerProvider, TemplateAnswerProvider
from app.rag.embeddings import OpenAIEmbeddingProvider, HashEmbeddingProvider
from app.rag.service import RagService
from app.rag.indexer import RagIndexer
from app.rag.contracts import load_documents
from tests.model_runtime_check import Clock
from tests.model_runtime_support import MemoryRuns, Response


class Corpus:
    def __init__(self, provider=None):
        provider = provider or HashEmbeddingProvider()
        self.chunks = [{'chunk_id':'c1','document_id':'metric-margin','version':2,'title':'利润率口径',
            'content':'利润率是本项目利润率序列，当前经营数值必须读取业务工具。',
            'aliases':[],'concept_ids':['metric.margin'],'source_ref':'fixture:local',
            'embedding':[.1]*provider.dimensions,'embedding_provider':provider.kind,'embedding_model':provider.model}]
        self.imports = []
    def active_chunks(self, types=None): return deepcopy(self.chunks)
    def import_batch(self, prepared, *, commit_guard=None):
        if commit_guard is not None: commit_guard()
        self.imports.append(prepared)
        return {'imported':len(prepared)}


class OrchestrationCases(unittest.TestCase):
    def test_index_deadline_rolls_back_real_sqlite_batch(self):
        from sqlalchemy import event
        from app import db
        from tests.knowledge_index_support import temporary_index
        clock=Clock();runs=MemoryRuns()
        versions=[d for d in load_documents() if d['id']=='metric-margin']
        old,new=min(versions,key=lambda d:d['version']),max(versions,key=lambda d:d['version'])
        self.assertGreater(new['version'],old['version'])
        with temporary_index([old],runs=runs) as (repository,index,write):
            index.rebuild();before=repository.get_document(old['id'],old['version']);chunks_before=repository.active_chunks()
            write([old,new])
            def slow_write(conn,cursor,statement,parameters,context,executemany):
                if 'INSERT INTO rag_document' in statement:clock.sleep(.02)
            event.listen(db.get_engine(),'before_cursor_execute',slow_write)
            run=RunContext('rag-index',repository=runs,clock=clock,profile=replace(load_profile('rag-index',False),maxElapsedMs=10,attemptTimeoutMs=10))
            with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):index.rebuild(run_context=run)
            event.remove(db.get_engine(),'before_cursor_execute',slow_write)
            write([old])
            self.assertEqual(repository.count('documents'),1);self.assertIsNone(repository.get_document(new['id'],new['version']))
            self.assertEqual(repository.get_document(old['id'],old['version']),before);self.assertEqual(repository.active_chunks(),chunks_before)
            self.assertEqual(runs.get_agent_run(run.run_id)['status'],'limited')

    def test_agent_timeout_is_limited_and_invalid_decision_stays_failed(self):
        from app.agent.loop import run_readonly_agent
        class Broken:
            external = False
            def __init__(self, timeout): self.timeout = timeout
            def decide(self, *args):
                if self.timeout: raise RuntimeFailure('provider_timeout', temporary=True)
                return {'kind': 'not-an-AgentDecision'}
        for timeout, status, reason in [(True, 'limited', 'provider_timeout'), (False, 'failed', 'invalid_decision')]:
            with self.subTest(timeout=timeout):
                result = run_readonly_agent(MemoryRuns(), Broken(timeout), '检查终态')
                self.assertEqual(result['run']['status'], status)
                self.assertEqual(result['output']['reason'], reason)
                self.assertFalse(result['ok'])
                self.assertEqual(result['output']['usage']['externalModelCalls'], 0)

    def test_query_and_answer_share_last_call_template_fallback(self):
        embed = OpenAIEmbeddingProvider('mock-key', dimensions=32)
        repo = MemoryRuns(); run = RunContext('rag-answer', external=True, repository=repo, external_enabled=True,
                profile=replace(load_profile('rag-answer', True), maxModelCalls=1))
        service = RagService(Corpus(embed), repo, embed, OpenAIAnswerProvider('mock-key'))
        body = {'data':[{'index':0,'embedding':[.1]*32}], 'usage':{'prompt_tokens':3,'total_tokens':3}}
        with patch('urllib.request.urlopen', return_value=Response(json.dumps(body).encode())) as transport:
            result = service.answer('利润率口径是什么', run_context=run)
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(result['provider'], 'template')
        self.assertEqual(result['fallbackReason'], 'budget_exceeded')
        self.assertEqual(result['usage']['externalModelCalls'], 1)
        self.assertEqual(repo.get_agent_run(run.run_id)['status'], 'done')

    def test_embedding_failure_lexical_no_hash(self):
        embed = OpenAIEmbeddingProvider('mock-key', dimensions=32); repo = MemoryRuns()
        run = RunContext('rag-answer', external=True, repository=repo, external_enabled=False)
        with patch('urllib.request.urlopen') as transport, patch.object(HashEmbeddingProvider, 'embed', side_effect=AssertionError('hash fallback forbidden')):
            result = RagService(Corpus(embed), repo, embed, TemplateAnswerProvider()).answer('利润率口径是什么', run_context=run)
        transport.assert_not_called()
        self.assertEqual(result['retrieval']['hits'][0]['retrieval'], 'lexical')
        self.assertEqual(result['retrieval']['fallbackReason'], 'external_disabled')
        self.assertEqual(result['status'], 'answered')

    def test_bad_citation_and_number_cannot_publish_original(self):
        class Bad(TemplateAnswerProvider):
            def answer(self, question, context): return {'answer':'987654%', 'citations':['illegal']}
        result = RagService(Corpus(), MemoryRuns(), HashEmbeddingProvider(), Bad()).answer('利润率口径是什么')
        self.assertEqual(result['status'], 'answered')
        self.assertEqual(result['provider'], 'template')
        self.assertEqual(result['fallbackReason'], 'citation_not_in_context')
        self.assertNotIn('987654', result['answer'])
        self.assertEqual(result['citations'][0]['chunk_id'], 'c1')

    def test_index_failed_batch_does_not_import(self):
        from tests.knowledge_index_support import temporary_index
        class Broken(HashEmbeddingProvider):
            def embed(self,texts):raise RuntimeFailure('provider_timeout')
        repo=MemoryRuns();run=RunContext('rag-index',repository=repo)
        with temporary_index(load_documents()[:1],Broken(),repo) as (corpus,index,write):
            with self.assertRaises(RuntimeFailure):index.rebuild(run_context=run)
            self.assertEqual(corpus.count('documents'),0)
            self.assertIsNone(corpus.index_store.read_snapshot()['head'])
        self.assertEqual(repo.get_agent_run(run.run_id)['status'],'failed')

    def test_sensitive_live_and_clarification_use_zero_model(self):
        service = RagService(Corpus(), MemoryRuns(), HashEmbeddingProvider(), TemplateAnswerProvider())
        for text, expected in [('管理员密码是什么','abstained'),('最新利润率是多少','tool_required'),('今天毛利率是多少','clarification_required')]:
            result = service.answer(text)
            self.assertEqual(result['status'], expected)
            self.assertEqual(result['usage']['externalModelCalls'], 0)
            self.assertEqual(result['budget']['providerInvocations'], 0)

    def test_no_time_for_template_fallback(self):
        embed = HashEmbeddingProvider(); repo = MemoryRuns(); clock = Clock()
        run = RunContext('rag-answer', repository=repo, clock=clock,
                profile=replace(load_profile('rag-answer', False), maxElapsedMs=10, attemptTimeoutMs=10))
        class Late(TemplateAnswerProvider):
            def answer(self, q, context): clock.sleep(.02); return {'answer':'迟到','citations':['c1']}
        result = RagService(Corpus(), repo, embed, Late()).answer('利润率口径是什么', run_context=run)
        self.assertEqual(result['status'], 'limited')
        self.assertEqual(result['answer'], '')
        self.assertEqual(repo.get_agent_run(run.run_id)['status'], 'limited')

    def test_agent_late_final_not_success(self):
        from app.agent.loop import AgentDecision, run_readonly_agent
        clock = Clock(); repo = MemoryRuns(); run = RunContext('readonly-agent', repository=repo, clock=clock,
                profile=replace(load_profile('readonly-agent', False), maxElapsedMs=10, attemptTimeoutMs=10))
        class Late:
            external = False
            def decide(self, *args): clock.sleep(.02); return AgentDecision('final', answer='迟到')
        result = run_readonly_agent(repo, Late(), '问题', run_context=run)
        self.assertEqual(result['run']['status'], 'limited')
        self.assertFalse(any(e['type']=='answer' for e in result['run']['events']))

    def test_reasoning_late_result_not_written(self):
        from app.reasoning.cache import refresh
        from app.reasoning.provider import ReasoningResult
        clock = Clock(); repo = MemoryRuns(); repo.writes=[]
        from types import SimpleNamespace
        version = {'versionStatus':'complete', 'revision':'fixture-revision'}
        repo.read_business_inputs = lambda:SimpleNamespace(business_version=version)
        repo.commit_reasoning_if_current = lambda *args, **kwargs:repo.writes.append(args)
        run = RunContext('reasoning-refresh', repository=repo, clock=clock,
                profile=replace(load_profile('reasoning-refresh', False), maxElapsedMs=10, attemptTimeoutMs=10))
        class Late:
            external=False; kind='template'
            calls=0
            def explain(self, context): self.calls+=1; clock.sleep(.02); return ReasoningResult(semantics={'next':['late']})
        insight = dict(id='p1',type='problem',metric='18%',delta='1%',trigger='x',factors=[],question='q')
        provider=Late()
        result = refresh(repo, [insight], {'businessVersion':version}, provider=provider, run_context=run)
        self.assertEqual(result['updated'], [])
        self.assertEqual(result['fallback'], ['p1'])
        self.assertEqual(repo.writes, [])
        self.assertEqual(provider.calls, 1)

    def test_agent_four_decisions_three_tools_remain_usable(self):
        from app.agent.loop import AgentDecision, run_readonly_agent
        from app.agent.tools import readonly_tools
        class Script:
            external=False; calls=0
            def decide(self, *args):
                self.calls += 1
                return AgentDecision('final',answer='完成') if self.calls==4 else AgentDecision('tool',tool='query_metric',arguments={'metric_key':'margin'})
        tools=readonly_tools(); tools['query_metric']=replace(tools['query_metric'],execute=lambda r,a:{'count':0,'rows':[]})
        result=run_readonly_agent(MemoryRuns(),Script(),'查指标',tools=tools)
        self.assertEqual(result['run']['status'],'done')
        self.assertEqual(result['output']['tool_calls'],3)


if __name__ == '__main__': unittest.main(verbosity=2)
