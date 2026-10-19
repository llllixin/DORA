import unittest
from dataclasses import replace
from app.query.service import QueryService
from app.query.contracts import QuerySearchRequest,QueryAnswerRequest,ReadPolicy,QueryConflict,QueryUnavailable
from app.query.read_view import QueryReadViewReader
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.rag.embeddings import HashEmbeddingProvider
from app.runtime.executor import RunContext
from app.runtime.contracts import RuntimeFailure
from tests.query_test_support import query_fixture

class Integration(unittest.TestCase):
    def service(self,f):
        reader=QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now)
        return QueryService(reader,policy=ReadPolicy(),ontology=Ontology.load(),embedding_provider=HashEmbeddingProvider(),run_repository=f.runs)
    def test_search_and_metric_execute_once_with_one_capture(self):
        with query_fixture() as f:
            f.indexer.rebuild();s=self.service(f);calls=[];capture=s.reader.capture
            s.reader.capture=lambda *a,**kw:(calls.append(1),capture(*a,**kw))[1]
            p=classify_query('利润率是什么，最新全国是多少？',s.ontology,on_date=f.now().date())
            result=s.execute(p,QueryAnswerRequest(question=p.query).options(),run_context=RunContext('unified-answer',repository=f.runs))
            self.assertEqual(len(calls),1);self.assertEqual([e['tool'] for e in result['toolExecutions']],['search_knowledge','query_metric'])
            self.assertTrue(result['businessVersion']);self.assertTrue(result['evidence'])
    def test_parent_run_is_not_finished_or_rebudgeted(self):
        with query_fixture() as f:
            s=self.service(f);r=RunContext('readonly-agent',repository=f.runs)
            r.budget.profile=replace(r.profile,maxToolCalls=1)
            before=len(f.runs.rows)
            value=r.execute('tool','tool',None,{},False,lambda a:s.metric('margin',None,20,run_context=r,tool_reserved=True))
            self.assertEqual(value['rows'][0]['value'],12);self.assertEqual(r.budget.tool_invocations,1)
            self.assertFalse(r.finished);self.assertEqual(len(f.runs.rows),before)
    def test_data_revision_mismatch_before_embedding(self):self.precondition('expectedDataRevision','expected_data_revision_changed')
    def test_source_revision_mismatch_before_embedding(self):self.precondition('expectedSourceRevision','expected_source_revision_changed')
    def precondition(self,field,reason):
        with query_fixture() as f:
            f.indexer.rebuild();s=self.service(f);calls=[]
            s.embedding_provider.embed=lambda *a,**kw:calls.append(1)
            req=QueryAnswerRequest(question='利润率是什么，最新全国是多少？',**{field:'wrong'})
            with self.assertRaises(QueryConflict) as error:s.answer(req)
            self.assertEqual(error.exception.code,reason);self.assertIsNotNone(error.exception.run_id);self.assertEqual(calls,[])
    def test_matching_preconditions_succeed(self):
        with query_fixture() as f:
            f.indexer.rebuild();s=self.service(f)
            first=s.answer(QueryAnswerRequest(question='利润率是什么，最新全国是多少？'))
            result=s.answer(QueryAnswerRequest(question='利润率是什么，最新全国是多少？',expectedDataRevision=first['businessVersion']['dataRevision'],expectedSourceRevision=first['sourceRevision']))
            self.assertEqual(result['status'],'answered')
    def test_second_tool_deadline_or_quota_stops_no_late_value(self):
        with query_fixture() as f:
            s=self.service(f);r=RunContext('unified-answer',repository=f.runs);r.budget.profile=replace(r.profile,maxToolCalls=1)
            p=classify_query('利润率是什么，最新全国是多少？',s.ontology,on_date=f.now().date())
            result=s.execute(p,QueryAnswerRequest(question=p.query).options(),run_context=r)
            self.assertEqual(len(result['toolExecutions']),2);self.assertEqual(result['toolExecutions'][-1]['status'],'limited')
            self.assertFalse(any(e['sourceKind']=='business' for e in result['evidence']))
    def test_global_evidence_limit_reserves_business_slot(self):
        with query_fixture() as f:
            f.indexer.rebuild();s=self.service(f)
            result=s.answer(QueryAnswerRequest(question='利润率是什么，最新全国是多少？',topK=10))
            self.assertLessEqual(len(result['evidence']),10);self.assertTrue(any(e['sourceKind']=='business' for e in result['evidence']))
    def test_failure_report_has_known_versions(self):
        with query_fixture() as f:
            s=self.service(f);r=RunContext('unified-answer',repository=f.runs);r.budget.profile=replace(r.profile,maxToolCalls=1)
            p=classify_query('利润率是什么，最新全国是多少？',s.ontology,on_date=f.now().date())
            value=s.execute(p,QueryAnswerRequest(question=p.query).options(),run_context=r)
            self.assertEqual(value['businessVersion']['dataRevision'][:8],'data-v1:')
    def test_large_unicode_and_parent_smaller_caps(self):
        from tests.query_runtime_check import LocalLimits
        LocalLimits('test_parent_smaller_still_enforced').test_parent_smaller_still_enforced()
