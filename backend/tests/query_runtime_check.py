"""Request limits overlay a parent ledger, including retries and transport admission."""
from dataclasses import replace
import unittest
from app.runtime.executor import RunContext
from app.runtime.budget import load_profile
from app.runtime.contracts import RuntimeFailure
from tests.model_runtime_support import MemoryRuns

class LocalLimits(unittest.TestCase):
    def setup_run(self,**limits):
        clock=[0.];runs=MemoryRuns()
        parent=replace(load_profile('readonly-agent',True),maxInputTokens=32768,maxTotalTokens=40960,maxRetries=1)
        run=RunContext('readonly-agent',profile=parent,repository=runs,clock=lambda:clock[0],sleep=lambda n:clock.__setitem__(0,clock[0]+n),external_enabled=True)
        local=replace(parent,profileId='unified-test',maxInputTokens=8192,maxOutputTokens=0,maxOutputTokensPerCall=0,maxTotalTokens=8192,
                      maxModelCalls=2,maxProviderInvocations=3,maxToolCalls=1,maxRetries=1,maxElapsedMs=15000,**limits)
        return run,local,clock,runs
    def test_parent_larger_retry_local_admission(self):
        run,local,clock,runs=self.setup_run();calls=[]
        def perform(attempt):
            attempt.dispatch();calls.append(attempt.token.attemptId)
            raise RuntimeFailure('provider_server_error',temporary=True)
        with run.limit_scope(local),self.assertRaisesRegex(RuntimeFailure,'budget_exceeded'):
            run.execute('query_embedding','fake','fake',{'q':'x'*14990},True,perform,output_tokens=0)
        self.assertEqual(len(calls),1);self.assertEqual(run.budget.calls,1)
        self.assertGreater(run.budget.consumed[0],4900);self.assertEqual(len(runs.rows),1);self.assertFalse(run.finished)
    def test_parent_smaller_still_enforced(self):
        run,local,clock,runs=self.setup_run();run.budget.profile=replace(run.profile,maxInputTokens=10,maxTotalTokens=10)
        with run.limit_scope(local),self.assertRaisesRegex(RuntimeFailure,'budget_exceeded'):
            run.execute('query_embedding','fake','fake',{'q':'x'*60},True,lambda a:self.fail('not admitted'),output_tokens=0)
        self.assertEqual(run.budget.invocations,0)
    def test_first_attempt_local_cap(self):
        run,local,clock,runs=self.setup_run()
        local=replace(local,maxInputTokens=1000,maxTotalTokens=1000)
        with run.limit_scope(local),self.assertRaisesRegex(RuntimeFailure,'budget_exceeded'):
            run.execute('query_embedding','fake','fake',{'q':'x'*6000},True,lambda a:self.fail('not admitted'),output_tokens=0)
    def test_local_deadline_and_transport_recheck(self):
        run,local,clock,runs=self.setup_run()
        def perform(attempt):clock[0]=15.1;attempt.dispatch();self.fail('expired dispatch')
        with run.limit_scope(local),self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):
            run.execute('query_embedding','fake','fake',{'q':'x'},True,perform,output_tokens=0)
        self.assertEqual(run.budget.calls,0);self.assertEqual(run.budget.summary()['pendingAttempts'],0)
        self.assertGreater(run.budget.remaining(),0)
    def test_local_request_retry_and_tool_caps(self):
        run,local,clock,runs=self.setup_run()
        local=replace(local,maxRequestBytes=100,maxRetries=0)
        with run.limit_scope(local):
            with self.assertRaisesRegex(RuntimeFailure,'context_limit'):run.execute('tool','t',None,{'x':'x'*101},False,lambda a:1)
            run.execute('tool','t',None,{},False,lambda a:1)
            with self.assertRaisesRegex(RuntimeFailure,'budget_exceeded'):run.execute('tool','t',None,{},False,lambda a:1)
            with self.assertRaisesRegex(RuntimeFailure,'provider_server_error'):
                run.execute('embed','fake','fake',{},True,lambda a:(_ for _ in ()).throw(RuntimeFailure('provider_server_error',temporary=True)),output_tokens=0)
        self.assertEqual(run.budget.invocations,1)
    def test_scope_settlement_preserves_parent_usage(self):
        run,local,clock,runs=self.setup_run()
        with run.limit_scope(local) as scope:
            token=run.budget.reserve('embedding',100,0,True);run.budget.dispatch(token)
        from app.runtime.contracts import Usage
        run.budget.settle(token,Usage(inputTokens=120,totalTokens=120))
        self.assertEqual(run.budget.consumed[0],120);self.assertEqual(scope.consumed[0],120)
    def test_scoped_concurrency_and_nested_deadline(self):
        run,local,clock,runs=self.setup_run()
        from app.runtime.contracts import Usage
        with run.limit_scope(local):
            first=run.budget.reserve('embedding',1,0,True)
            with self.assertRaisesRegex(RuntimeFailure,'budget_exceeded'):run.budget.reserve('embedding',1,0,True)
            run.budget.settle(first,Usage())
            clock[0]=14.9
            with run.limit_scope(local):
                clock[0]=15.1
                with self.assertRaisesRegex(RuntimeFailure,'deadline_exceeded'):run.budget.check()
    def test_sibling_request_scopes_share_parent_concurrency(self):
        from contextvars import Context
        from app.runtime.contracts import Usage
        run,local,clock,runs=self.setup_run();contexts=[Context(),Context()];scopes=[run.limit_scope(local),run.limit_scope(local)]
        for ctx,scope in zip(contexts,scopes):ctx.run(scope.__enter__)
        try:
            token=contexts[0].run(run.budget.reserve,'query_embedding',1,0,True)
            with self.assertRaisesRegex(RuntimeFailure,'budget_exceeded'):contexts[1].run(run.budget.reserve,'query_embedding',1,0,True)
            self.assertEqual(len(run.budget.pending),1)
            run.budget.settle(token,Usage())
        finally:
            for ctx,scope in zip(contexts,scopes):ctx.run(scope.__exit__,None,None,None)
