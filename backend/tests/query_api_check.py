import unittest
from dataclasses import replace
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.query.router import router,get_query_service,get_run_repository
from app.query.service import default_service
from app.query.evidence import read_run_evidence
from app.agent.tools import readonly_tools,execute_tool
from app.runtime.executor import RunContext
from tests.query_test_support import query_fixture

class API(unittest.TestCase):
    def client(self,f):
        app=FastAPI();app.include_router(router);s=default_service(f.runs);s.reader.now=f.now
        app.dependency_overrides[get_query_service]=lambda:s
        app.dependency_overrides[get_run_repository]=lambda:f.runs
        return TestClient(app)
    def test_http_actual_current_tool_and_version(self):
        with query_fixture([]) as f:
            c=self.client(f);r=c.post('/api/query/answer',json={'question':'最新全国利润率是多少？'})
            self.assertEqual(r.status_code,200,r.text);v=r.json()
            self.assertEqual(v['toolExecutions'][0]['tool'],'query_metric');self.assertEqual(v['status'],'answered')
            self.assertTrue(v['businessVersion']['dataRevision']);self.assertEqual(v['evidence'][0]['data']['rows'][0]['value'],12)
    def test_http_409_422_503_run_id_and_healthy_partial(self):
        with query_fixture([]) as f:
            c=self.client(f)
            for field in ('expectedDataRevision','expectedSourceRevision'):
                r=c.post('/api/query/answer',json={'question':'利润率是什么，最新全国是多少？',field:'wrong'})
                self.assertEqual(r.status_code,409,r.text);self.assertTrue(r.json()['detail']['runId'])
            r=c.post('/api/query/answer',json={'question':'利润率是什么？','expectedDataRevision':'wrong'})
            self.assertEqual(r.status_code,422)
            self.assertEqual(c.post('/api/query/search',json={'query':'利润率','topK':True}).status_code,422)
            from app.rag.migration import _ready
            _ready[f.engine]=False
            r=c.post('/api/query/answer',json={'question':'利润率是什么，最新全国是多少？'})
            self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['status'],'partial')
            r=c.post('/api/query/answer',json={'question':'利润率是什么？'})
            self.assertEqual(r.status_code,503,r.text);self.assertTrue(r.json()['detail']['runId'])
    def test_readonly_evidence_get_404_409(self):
        with query_fixture([]) as f:
            c=self.client(f);v=c.post('/api/query/answer',json={'question':'最新全国利润率是多少？'}).json()
            url=v['citations'][0]['href'];r=c.get(url);self.assertEqual(r.status_code,200,r.text)
            f.runs.rows[v['runId']]['output']['evidence'][0]['data']['rows'][0]['value']=99
            self.assertEqual(c.get(url).status_code,409)
            self.assertEqual(c.get('/api/query/runs/absent/evidence/absent').status_code,404)
    def test_agent_parent_tool_and_model_budget_single_ledger(self):
        from unittest.mock import patch
        with query_fixture() as f:
            f.indexer.rebuild();s=default_service(f.runs);s.reader.now=f.now
            r=RunContext('readonly-agent',repository=f.runs);tools=readonly_tools();spec=tools['search_knowledge']
            args=spec.validate({'query':'利润率','top_k':3});before=len(f.runs.rows)
            with patch('app.query.service.default_service',return_value=s):
                result=r.execute('tool','local-tool','search_knowledge',args,False,lambda a:execute_tool(spec,f.runs,args,run_context=r))
            self.assertEqual(r.budget.tool_invocations,1);self.assertFalse(r.finished);self.assertEqual(len(f.runs.rows),before)
            self.assertEqual(result['runId'],r.run_id);self.assertTrue(result['references'])
            r.emit({'type':'tool_result','result':result})
            e=result['evidence'][0];self.assertEqual(read_run_evidence(f.runs,r.run_id,e['evidenceId']),e)
            self.assertEqual(result['references'][0]['entry_type'],'wiki')
    def test_two_arg_custom_tool_executes_once_and_typeerror_not_retried(self):
        calls=[];spec=readonly_tools()['query_metric'];run=RunContext('readonly-agent')
        def broken(repo,args):calls.append(1);raise TypeError('internal error')
        with self.assertRaisesRegex(TypeError,'internal error'):execute_tool(replace(spec,execute=broken),None,{},run_context=run)
        self.assertEqual(calls,[1])
    def test_replaced_execute_is_honored(self):
        spec=replace(readonly_tools()['query_metric'],execute=lambda repo,args:{'custom':True})
        self.assertEqual(execute_tool(spec,None,{},run_context=RunContext('readonly-agent')),{'custom':True})
    def test_legacy_agent_reference_projection(self):self.test_agent_parent_tool_and_model_budget_single_ledger()
    def test_evidence_get_independent_of_provider_configuration(self):
        from unittest.mock import patch
        with query_fixture([]) as f:
            service=default_service(f.runs);service.reader.now=f.now
            value=service.answer(__import__('app.query.contracts',fromlist=['QueryAnswerRequest']).QueryAnswerRequest(question='最新全国利润率是多少？'))
            app=FastAPI();app.include_router(router)
            def forbidden():raise ValueError('invalid provider configuration must not affect history')
            app.dependency_overrides[get_query_service]=forbidden
            with patch('app.repository.Repository',return_value=f.runs):
                response=TestClient(app,raise_server_exceptions=False).get(value['citations'][0]['href'])
            self.assertEqual(response.status_code,200,response.text)
    def test_agent_metric_still_excludes_seeded_sample(self):
        from unittest.mock import patch
        with query_fixture([],source_mode='sample') as f:
            s=default_service(f.runs);spec=readonly_tools()['query_metric'];r=RunContext('readonly-agent',repository=f.runs)
            with patch('app.query.service.default_service',return_value=s):
                value=execute_tool(spec,f.runs,spec.validate({'metric_key':'margin'}),run_context=r)
            self.assertEqual(value['count'],0);self.assertEqual(value['reasonCode'],'simulated_source_excluded')
    def test_final_agent_legacy_projection_respects_response_cap(self):
        from sqlalchemy.orm import Session
        from app.models import KnowledgeArchive
        from app.agent.tools import _search_knowledge
        from unittest.mock import patch
        import json
        with query_fixture([]) as f:
            with Session(f.engine) as session:
                for n in range(10):session.add(KnowledgeArchive(entry_type='problem',source_id=str(n),code='code',title='利润率'+'中'*297,content='利润率复核。'*200,note='',created_at=''))
                session.commit()
            service=default_service(f.runs);service.reader.now=f.now
            with patch('app.query.service.default_service',return_value=service):
                result=_search_knowledge(f.runs,{'query':'利润率','types':[],'top_k':10,'sourceKinds':['archive']})
            self.assertLessEqual(len(json.dumps(result,ensure_ascii=False).encode()),65536)
            self.assertEqual({e['evidenceId'] for e in result['evidence']},{e['evidenceId'] for e in result['references']})
            for e in result['evidence']:self.assertEqual(read_run_evidence(f.runs,result['runId'],e['evidenceId']),e)
