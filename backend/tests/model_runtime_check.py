"""A04 deterministic unit checks: fake clock/transport, no database or real model."""
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import patch
from urllib.error import HTTPError

from app.runtime.contracts import normalize_usage, aggregate_usage, RuntimeFailure
from app.runtime.budget import RunBudget, load_profile
from app.runtime.executor import RunContext
from tests.model_runtime_support import MemoryRuns, Response


class Clock:
    def __init__(self): self.value = 0.0
    def __call__(self): return self.value
    def sleep(self, seconds): self.value += seconds


class RuntimeCases(unittest.TestCase):
    def test_slow_dispatch_audit_cannot_send_after_deadline(self):
        clock = Clock()
        class SlowAudit(MemoryRuns):
            def append_agent_run_event(self, key, event):
                if event['type'] in ('model_dispatch_preparing', 'model_dispatch'):
                    clock.sleep(.02)
                return super().append_agent_run_event(key, event)
        repo = SlowAudit()
        run = RunContext('rag-search', external=True, repository=repo, clock=clock, external_enabled=True,
                         profile=replace(load_profile('rag-search', True), maxElapsedMs=10, attemptTimeoutMs=10))
        with patch('urllib.request.urlopen', return_value=Response(b'{}')) as transport:
            with self.assertRaisesRegex(RuntimeFailure, 'deadline_exceeded'):
                run.execute('query_embedding', 'mock', 'm', {}, True,
                            lambda a: a.post_json('https://mock.invalid', 'mock-key', {}, 'embeddings'), output_tokens=0)
        transport.assert_not_called()
        result = run.finish({}, 'limited')
        self.assertEqual(result['usage']['externalModelCalls'], 0)
        self.assertEqual(result['budget']['externalModelCalls'], 0)
        self.assertEqual(result['budget']['consumedTotalAdmission'], 0)
        self.assertEqual(result['budget']['pendingAttempts'], 0)
        self.assertFalse(any(e['type'] == 'model_dispatch' for e in repo.get_agent_run(run.run_id)['events']))

    def test_timeout_recomputed_after_dispatch_audit(self):
        clock = Clock()
        class SlowAudit(MemoryRuns):
            def append_agent_run_event(self, key, event):
                if event['type'] in ('model_dispatch_preparing', 'model_dispatch'):
                    clock.sleep(.005)
                return super().append_agent_run_event(key, event)
        run = RunContext('rag-search', external=True, repository=SlowAudit(), clock=clock, external_enabled=True,
                         profile=replace(load_profile('rag-search', True), maxElapsedMs=20, attemptTimeoutMs=20))
        sends = []
        def transport(request, timeout):
            sends.append((clock(), timeout))
            return Response(b'{}')
        with patch('urllib.request.urlopen', side_effect=transport):
            run.execute('query_embedding', 'mock', 'm', {}, True,
                        lambda a: a.post_json('https://mock.invalid', 'mock-key', {}, 'embeddings'), output_tokens=0)
        self.assertEqual(len(sends), 1)
        self.assertAlmostEqual(sends[0][0], .005)
        self.assertAlmostEqual(sends[0][1], .015)
        self.assertEqual(sum(e['type'] == 'model_dispatch' for e in run.events), 1)
        self.assertEqual(run.diagnostics()['usage']['externalModelCalls'], 1)

    def test_sent_transport_failure_still_has_one_dispatch(self):
        run = RunContext('rag-search', external=True, repository=MemoryRuns(), external_enabled=True,
                         profile=replace(load_profile('rag-search', True), maxRetries=0))
        with patch('urllib.request.urlopen', side_effect=TimeoutError('mock timeout')) as transport:
            with self.assertRaisesRegex(RuntimeFailure, 'provider_timeout'):
                run.execute('query_embedding', 'mock', 'm', {}, True,
                            lambda a: a.post_json('https://mock.invalid', 'mock-key', {}, 'embeddings'), output_tokens=0)
        self.assertEqual(transport.call_count, 1)
        result = run.finish({}, 'limited')
        self.assertEqual(result['usage']['externalModelCalls'], 1)
        self.assertEqual(result['budget']['externalModelCalls'], 1)
        self.assertGreater(result['budget']['consumedTotalAdmission'], 0)
        self.assertEqual(sum(e['type'] == 'model_dispatch' for e in run.events), 1)

    def test_usage_protocols_and_details(self):
        raw = {'input_tokens': 120, 'output_tokens': 40, 'total_tokens': 160,
               'input_tokens_details': {'cached_tokens': 50}, 'output_tokens_details': {'reasoning_tokens': 15}}
        usage = normalize_usage(raw, 'responses')
        self.assertEqual((usage.inputTokens, usage.outputTokens, usage.totalTokens), (120, 40, 160))
        self.assertEqual(usage.measurementStatus, 'measured')
        chat = normalize_usage({'prompt_tokens': 90, 'completion_tokens': 30, 'total_tokens': 120}, 'chat-completions')
        self.assertEqual(chat.totalTokens, 120)
        embed = normalize_usage({'prompt_tokens': 80, 'total_tokens': 80}, 'embeddings')
        self.assertIsNone(embed.outputTokens)
        self.assertEqual(embed.totalTokens, 80)

    def test_unknown_invalid_partial_total(self):
        invalid = normalize_usage({'input_tokens': True, 'output_tokens': -1, 'total_tokens': float('nan')}, 'responses')
        self.assertIsNone(invalid.totalTokens)
        self.assertTrue(invalid.diagnostics)
        partial = normalize_usage({'input_tokens': 12, 'output_tokens': 3}, 'responses')
        self.assertIsNone(partial.totalTokens)
        inconsistent = normalize_usage({'input_tokens': 12, 'output_tokens': 3, 'total_tokens': 20}, 'responses')
        self.assertEqual(inconsistent.totalTokens, 20)
        self.assertIn('inconsistent_total', inconsistent.diagnostics)

    def test_aggregate_unknown_does_not_become_zero(self):
        a = normalize_usage({'input_tokens': 120, 'output_tokens': 40, 'total_tokens': 160}, 'responses')
        total = aggregate_usage([a, normalize_usage(None, 'responses')], 30)
        self.assertIsNone(total['totalTokens'])
        self.assertEqual(total['knownTokenSubtotal'], 160)
        self.assertEqual(total['externalModelCalls'], 2)
        self.assertEqual(total['unknownUsageAttempts'], 1)
        offline = aggregate_usage([normalize_usage(None, 'offline', external_calls=0)], 2)
        self.assertEqual(offline['measurementStatus'], 'unknown')
        self.assertEqual(offline['externalModelCalls'], 0)
        self.assertIsNone(offline['totalTokens'])
        self.assertIsNone(offline['costAmount'])

    def test_profiles_invalid(self):
        p = load_profile('rag-answer', True)
        for kwargs in [{'maxModelCalls': True}, {'attemptTimeoutMs': -1}, {'maxTotalTokens': float('inf')},
                       {'maxOutputTokensPerCall': p.maxOutputTokens + 1}]:
            with self.assertRaises(ValueError): replace(p, **kwargs)

    def test_parallel_last_reservation(self):
        p = replace(load_profile('rag-answer', True), maxModelCalls=1)
        b = RunBudget(p)
        barrier = threading.Barrier(2)
        def reserve(_):
            barrier.wait()
            try: return b.reserve('answer', 10, 2, True)
            except RuntimeFailure: return None
        with ThreadPoolExecutor(2) as pool: results = list(pool.map(reserve, range(2)))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_dispatch_failure_keeps_budget_and_settle_idempotent(self):
        p = replace(load_profile('rag-answer', True), maxModelCalls=1)
        b = RunBudget(p)
        token = b.reserve('answer', 10, 2, True)
        b.dispatch(token)
        u = normalize_usage(None, 'responses')
        b.settle(token, u)
        b.settle(token, u)
        self.assertEqual(b.summary()['externalModelCalls'], 1)
        with self.assertRaises(RuntimeFailure): b.reserve('answer', 10, 2, True)

    def test_undispatched_release_and_overrun(self):
        p = replace(load_profile('rag-answer', True), maxModelCalls=2, maxInputTokens=20,
                    maxOutputTokens=2, maxOutputTokensPerCall=2, maxTotalTokens=22)
        b = RunBudget(p)
        t = b.reserve('answer', 10, 1, True)
        b.settle(t, normalize_usage(None, 'offline', external_calls=0))
        t = b.reserve('answer', 10, 1, True); b.dispatch(t)
        b.settle(t, normalize_usage({'input_tokens': 30, 'output_tokens': 2, 'total_tokens': 32}, 'responses'))
        self.assertTrue(b.summary()['overrun'])
        with self.assertRaises(RuntimeFailure): b.reserve('answer', 1, 1, True)

    def test_retry_accounting_and_wait(self):
        clock = Clock(); run = RunContext('rag-answer', external=True, clock=clock, sleep=clock.sleep, external_enabled=True)
        calls = []
        def perform(attempt):
            attempt.dispatch(); calls.append(attempt.timeout)
            if len(calls) == 1: raise HTTPError('mock', 429, 'rate', {'Retry-After': '1'}, None)
            attempt.capture_usage({'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}, 'responses')
            return 'ok'
        self.assertEqual(run.execute('answer', 'mock', 'mock-model', {'input': 'abc'}, True, perform), 'ok')
        self.assertEqual(run.diagnostics()['usage']['externalModelCalls'], 2)
        self.assertIsNone(run.diagnostics()['usage']['totalTokens'])
        self.assertEqual(clock.value, 1.0)

    def test_auth_no_retry_and_offline_gate(self):
        run = RunContext('rag-answer', external=True, external_enabled=True)
        def denied(attempt): attempt.dispatch(); raise HTTPError('mock', 401, 'secret', None, None)
        with self.assertRaises(RuntimeFailure): run.execute('answer', 'mock', 'm', {}, True, denied)
        self.assertEqual(run.diagnostics()['usage']['externalModelCalls'], 1)
        closed = RunContext('rag-answer', external=True, external_enabled=False)
        with self.assertRaises(RuntimeFailure): closed.execute('answer', 'mock', 'm', {}, True, denied)
        self.assertEqual(closed.diagnostics()['usage']['externalModelCalls'], 0)
        self.assertNotIn('secret', json.dumps(run.events))

    def test_deadline_late_usage_preserved(self):
        clock = Clock(); run = RunContext('rag-answer', external=True, clock=clock, sleep=clock.sleep, external_enabled=True,
                profile=replace(load_profile('rag-answer', True), maxElapsedMs=10, attemptTimeoutMs=10))
        def late(attempt):
            self.assertLessEqual(attempt.timeout, .01)
            attempt.dispatch(); clock.sleep(.02)
            attempt.capture_usage({'usage': {'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5}}, 'responses')
            return 'late'
        with self.assertRaises(RuntimeFailure): run.execute('answer', 'mock', 'm', {}, True, late)
        self.assertEqual(run.diagnostics()['usage']['totalTokens'], 5)
        self.assertGreater(run.diagnostics()['budget']['deadlineOverrunMs'], 0)

    def test_size_and_retry_deadline(self):
        run = RunContext('rag-answer', external=True, external_enabled=True,
                profile=replace(load_profile('rag-answer', True), maxRequestBytes=5))
        with self.assertRaises(RuntimeFailure): run.execute('answer', 'mock', 'm', {'input': 'oversize'}, True, lambda a: None)
        self.assertEqual(run.diagnostics()['usage']['externalModelCalls'], 0)
        clock = Clock(); run = RunContext('rag-answer', external=True, external_enabled=True, clock=clock, sleep=clock.sleep,
                profile=replace(load_profile('rag-answer', True), maxElapsedMs=100, attemptTimeoutMs=100))
        def rate(a): a.dispatch(); raise HTTPError('mock', 429, 'rate', {'Retry-After': '1'}, None)
        with self.assertRaises(RuntimeFailure): run.execute('answer', 'mock', 'm', {}, True, rate)
        self.assertEqual(run.diagnostics()['usage']['externalModelCalls'], 1)

    def test_builtin_adapters_capture_usage_and_caps(self):
        from app.rag.answer import OpenAIAnswerProvider
        from app.rag.embeddings import OpenAIEmbeddingProvider
        response = {'model': 'returned-model', 'id': 'mock-response', 'output_text': json.dumps({'answer': '依据', 'citations': ['c1']}),
                    'usage': {'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12}}
        def transport(request, timeout):
            self.assertGreater(timeout, 0)
            self.assertLessEqual(timeout, 10)
            self.assertEqual(json.loads(request.data)['max_output_tokens'], 2048)
            return Response(json.dumps(response).encode())
        run = RunContext('rag-answer', external=True, external_enabled=True)
        with patch('urllib.request.urlopen', side_effect=transport):
            result = OpenAIAnswerProvider('mock-key', model='requested-model').answer('问', [{'chunk_id':'c1','title':'题','content':'依据'}], run_context=run)
        self.assertEqual(result['answer'], '依据')
        self.assertEqual(run.diagnostics()['usage']['totalTokens'], 12)
        self.assertEqual(run.events[-1]['responseModel'], 'returned-model')
        run = RunContext('rag-search', external=True, external_enabled=True)
        with patch('urllib.request.urlopen', return_value=Response(json.dumps({'data':[{'index':0,'embedding':[.1]*32}],
             'usage': {'prompt_tokens':5,'total_tokens':5}}).encode())):
            OpenAIEmbeddingProvider('mock-key', dimensions=32).embed(['x'], run_context=run)
        self.assertEqual(run.diagnostics()['usage']['totalTokens'], 5)
        self.assertIsNone(run.diagnostics()['usage']['outputTokens'])

    def test_provider_invalid_response_keeps_usage_no_retry(self):
        from app.rag.answer import OpenAIAnswerProvider
        run = RunContext('rag-answer', external=True, external_enabled=True)
        with patch('urllib.request.urlopen', return_value=Response(json.dumps({'output_text':'bad-json',
             'usage':{'input_tokens':7,'output_tokens':3,'total_tokens':10}}).encode())) as transport:
            with self.assertRaises(RuntimeFailure): OpenAIAnswerProvider('mock-key').answer('问', [], run_context=run)
            self.assertEqual(transport.call_count, 1)
        self.assertEqual(run.diagnostics()['usage']['totalTokens'], 10)

    def test_direct_external_call_cannot_bypass_and_local_usage(self):
        from app.rag.answer import OpenAIAnswerProvider, TemplateAnswerProvider
        repo = MemoryRuns()
        with patch('app.runtime.records.default_repository', return_value=repo), patch.dict('os.environ', {'DORA_MODEL_EXTERNAL_ENABLED':'false'}), patch('urllib.request.urlopen') as transport:
            with self.assertRaises(RuntimeFailure): OpenAIAnswerProvider('mock-key').answer('问', [])
            transport.assert_not_called()
            TemplateAnswerProvider().answer('问', [])
        self.assertTrue(all(row['status'] != 'running' for row in repo.rows.values()))
        self.assertEqual(list(repo.rows.values())[-1]['output']['usage']['externalModelCalls'], 0)

    def test_unknown_adapter_denied(self):
        from app.runtime.executor import invoke_provider
        class Unknown:
            def answer(self, *args): raise AssertionError('must not execute')
        with self.assertRaises(RuntimeFailure): invoke_provider(Unknown(), 'answer', ('q', []), RunContext('rag-answer'), 'answer')

    def test_late_http_body_usage_preserved(self):
        from app.rag.answer import OpenAIAnswerProvider
        clock = Clock(); run = RunContext('rag-answer', external=True, external_enabled=True, clock=clock,
                profile=replace(load_profile('rag-answer', True), maxElapsedMs=10, attemptTimeoutMs=10))
        class Late(Response):
            def read(self, size):
                content = super().read(size)
                clock.sleep(.02)
                return content
        body = {'output_text':json.dumps({'answer':'迟到','citations':[]}), 'usage':{'input_tokens':1,'output_tokens':2,'total_tokens':3}}
        with patch('urllib.request.urlopen', return_value=Late(json.dumps(body).encode())):
            with self.assertRaises(RuntimeFailure): OpenAIAnswerProvider('mock-key').answer('q', [], run_context=run)
        self.assertEqual(run.diagnostics()['usage']['totalTokens'], 3)

    def test_pending_reservation_invalidated_by_actual_usage(self):
        p=replace(load_profile('rag-answer',True),maxInputTokens=300,maxOutputTokens=0,maxConcurrency=2,
                  maxOutputTokensPerCall=0,maxTotalTokens=300)
        budget=RunBudget(p)
        first=budget.reserve('answer',100,0,True); second=budget.reserve('answer',100,0,True)
        budget.dispatch(first)
        budget.settle(first,normalize_usage({'input_tokens':250,'output_tokens':0,'total_tokens':250},'responses'))
        with self.assertRaises(RuntimeFailure):budget.dispatch(second)
        self.assertEqual(budget.summary()['externalModelCalls'],1)

    def test_signature_is_not_runtime_trust(self):
        from app.runtime.executor import invoke_provider
        calls=[]
        class Unmanaged:
            external=True
            def answer(self,q,context,*,run_context=None):calls.append(q);return 'bypassed'
        run=RunContext('rag-answer',external=True,external_enabled=False)
        with self.assertRaises(RuntimeFailure):invoke_provider(Unmanaged(),'answer',('q',[]),run,'answer')
        self.assertEqual(calls,[])
        clock=Clock()
        class Local:
            external=False
            def answer(self,q,context,*,run_context=None):clock.sleep(100);return 'late'
        run=RunContext('rag-answer',clock=clock)
        with self.assertRaises(RuntimeFailure):invoke_provider(Local(),'answer',('q',[]),run,'answer')

    def test_finish_cannot_publish_between_settlement_and_accounting(self):
        repo=MemoryRuns();run=RunContext('rag-answer',external=True,repository=repo,external_enabled=True)
        settled=threading.Event();release=threading.Event();finish_done=threading.Event();outputs=[];errors=[]
        original=run.budget.settle
        def pause(*args):
            original(*args);settled.set()
            if not release.wait(3):raise AssertionError('release timeout')
        def perform(a):a.dispatch();return 'ok'
        def finish():
            try:outputs.append(run.finish({}))
            except RuntimeFailure as exc:errors.append(exc.category)
            finally:finish_done.set()
        with patch.object(run.budget,'settle',side_effect=pause):
            worker=threading.Thread(target=lambda:run.execute('answer','mock','m',{},True,perform))
            worker.start();self.assertTrue(settled.wait(3))
            finisher=threading.Thread(target=finish);finisher.start()
            finish_done.wait(.05);release.set();worker.join(3);finisher.join(3)
        self.assertFalse(worker.is_alive() or finisher.is_alive())
        if outputs:self.assertEqual(outputs[0]['usage']['externalModelCalls'],1)
        else:self.assertEqual(errors,['attempts_in_flight']);run.finish({})
        stored=repo.get_agent_run(run.run_id)
        self.assertEqual(stored['output']['usage']['externalModelCalls'],1)
        self.assertEqual(stored['events'][-1]['type'],'model_run_finished')

    def test_envelope_metadata_is_recorded(self):
        from app.runtime.contracts import ProviderEnvelope
        run=RunContext('rag-answer')
        run.execute('answer','local','requested',{},False,lambda a:ProviderEnvelope('ok',
            requestedModel='requested',responseModel='actual',responseId='id123',adapterVersion='custom-v2'))
        event=run.events[-1]
        self.assertEqual((event['responseModel'],event['responseId'],event['adapterVersion']),('actual','id123','custom-v2'))

    def test_transport_timeout_uses_remaining_at_dispatch(self):
        clock=Clock();run=RunContext('rag-answer',external=True,external_enabled=True,clock=clock)
        def transport(request,timeout):
            self.assertLessEqual(timeout,1)
            return Response(b'{}')
        def perform(a):clock.sleep(29);return a.post_json('https://mock.invalid','mock-key',{},'responses')
        with patch('urllib.request.urlopen',side_effect=transport):run.execute('answer','mock','m',{},True,perform)

    def test_chat_adapter_usage_numeric_lock_and_output_cap(self):
        from app.reasoning.llm import LLMProvider
        from app.reasoning.provider import ReasoningContext
        from app.reasoning import policy
        baseline={'causeA':{'name':'a','value':'18%'},'causeB':{'name':'b','value':'2%'},'next':['a','b','c']}
        generated={'causeA':{'name':'模型文案','value':'999%'},'causeB':{'name':'定位','value':'999%'},'next':['查成本','查口径','复核']}
        body={'model':'mock-actual','id':'mock-chat','choices':[{'message':{'content':json.dumps(generated)}}],
              'usage':{'prompt_tokens':11,'completion_tokens':5,'total_tokens':16}}
        def transport(request,timeout):
            self.assertEqual(json.loads(request.data)['max_tokens'],1024)
            return Response(json.dumps(body).encode())
        policy.breaker.reset_for_tests()
        with patch.dict('os.environ',{'DORA_LLM_API_KEY':'mock-key','DORA_LLM_BASE_URL':'https://mock.invalid/v1','DORA_LLM_MODEL':'mock-model'}),\
             patch('app.reasoning.llm.template_semantics',return_value=baseline),patch('urllib.request.urlopen',side_effect=transport):
            run=RunContext('reasoning-refresh',external=True,external_enabled=True)
            value=LLMProvider().explain(ReasoningContext('p1','problem','18%','1%','x',[],'q'),run_context=run)
        self.assertEqual(value.semantics['causeA']['value'],'18%')
        self.assertEqual(run.diagnostics()['usage']['totalTokens'],16)
        self.assertEqual(run.events[-1]['responseModel'],'mock-actual')


if __name__ == '__main__': unittest.main(verbosity=2)
