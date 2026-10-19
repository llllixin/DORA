"""Independent A07 fixture evaluation; original 40-question profiles stay frozen."""
from __future__ import annotations
from contextlib import contextmanager
import hashlib,json,os
from pathlib import Path
import unittest
from sqlalchemy.orm import Session
from app.query.contracts import QueryAnswerRequest,ReadPolicy
from app.query.service import QueryService
from app.query.read_view import QueryReadViewReader
from app.query.rendering import validate_claims
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.rag.embeddings import HashEmbeddingProvider
from app.models import ActionCase,KnowledgeArchive
from app.wiki.candidates import capture
from tests.query_test_support import query_fixture,change_directory

ROOT=Path(__file__).resolve().parents[2]
CHANGE=change_directory()
QUESTIONS=CHANGE/'artifacts/questions.candidate.json'

@contextmanager
def scenario_fixture(name,definitions):
    base=definitions['uploaded-relative-and-reported'];config=definitions.get(name,{})
    rows=[]
    for key,field in [('margin','marginRows'),('east_orders','eastOrdersRows'),('returns','returnsRows')]:
        for row in config.get(field,base[field]):rows.append({'metric_key':key,**row})
    with query_fixture(metric_rows=rows,source_mode=config.get('businessSourceMode','uploaded')) as f:
        f.indexer.rebuild()
        with Session(f.engine) as s:
            case=ActionCase(id='a07-synthetic-record',status='resolved',origin='demo' if name=='simulated-archive-explicit' else 'engine',created_at='2026-10-16T00:00:00',updated_at='2026-10-16T00:00:00')
            archive=KnowledgeArchive(entry_type='problem',source_id=case.id,code='A07-FIXTURE',title=config.get('title',base['record']['title']),content=base['record']['content'],note='无企业效果验证。',created_at='2026-10-16T00:00:00')
            s.add_all([case,archive]);s.flush();capture(s,archive,case);s.commit()
        service=QueryService(QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now),policy=ReadPolicy(),ontology=Ontology.load(),embedding_provider=HashEmbeddingProvider(),run_repository=f.runs)
        yield service

def evaluate_query(service,scenarios,*,fixture_factory=None):
    results=[]
    for q in scenarios:
        def evaluate(s):
            response=s.answer(QueryAnswerRequest(question=q['question'],includeSimulated=q['includeSimulated']))
            assert response['route']==q['expectedRoute'],(q['id'],'route',response['route'])
            assert response['status']==q['expectedStatus'],(q['id'],'status',response['status'],response.get('reasonCode'))
            plan=classify_query(q['question'],s.ontology,on_date=s.reader.now().date())
            validate_claims(response['claims'],response['evidence'],plan=plan)
            assert response['usage']['externalModelCalls']==0 and response['usage']['totalTokens'] is None
            if q['expectedRoute'] in ('clarify','policy'):assert not response['toolExecutions']
            if q['expectedRoute']=='current' and q['id']!='a07-q10':assert response['toolExecutions'][0]['tool']=='query_metric'
            if q['id']=='a07-q05':assert response['evidence'][0]['data']['metricKey']=='east_orders'
            if q['id']=='a07-q13':assert any(c['text'].startswith('【模拟】') for c in response['claims'])
            if q['id']=='a07-q04':assert response['reasonCode']=='unverified_today'
            if q['id']=='a07-q09':assert response['reasonCode']=='unsupported_time_range' and not response['evidence']
            return {'id':q['id'],'passed':True,'route':response['route'],'status':response['status'],'runId':response['runId'],
                    'tools':response['toolExecutions'],'evidenceCount':len(response['evidence']),'claimCount':len(response['claims']),'response':response}
        if fixture_factory:
            with fixture_factory(q['fixture']) as s:results.append(evaluate(s))
        else:results.append(evaluate(service))
    return {'profile':'a07-v1','fixtureOnly':True,'passed':all(r['passed'] for r in results),'results':results}

class Evaluation(unittest.TestCase):
    def test_gate_rejects_user_database_before_any_work(self):
        from tests.query_gate import validate_environment
        valid={'DATABASE_URL':'postgresql+psycopg://dora_a07:dora_a07@127.0.0.1:55477/dora_a07','DORA_API_BASE':'http://127.0.0.1:8077/api'}
        self.assertEqual(validate_environment(valid)[1],8077)
        for key,value in [('DATABASE_URL','postgresql+psycopg://dora:dora@127.0.0.1:5432/dora'),('DATABASE_URL','postgresql+psycopg://dora_a07:x@remote:55477/dora_a07'),('DORA_API_BASE','http://remote:8077/api')]:
            with self.assertRaises((ValueError,RuntimeError)):validate_environment({**valid,key:value})
    def test_scenarios_keep_original_judgments_and_exact_status(self):
        raw=json.loads(QUESTIONS.read_text());self.assertEqual(len(raw['questions']),17)
        result=evaluate_query(None,raw['questions'],fixture_factory=lambda name:scenario_fixture(name,raw['fixtureDefinitions']))
        self.assertTrue(result['passed']);self.assertEqual(len(result['results']),17)
        out=ROOT/'output/a07-verification';out.mkdir(parents=True,exist_ok=True)
        (out/'scenarios.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    def test_missing_runtime_evidence_not_complete(self):
        import importlib.util,tempfile
        spec=importlib.util.spec_from_file_location('a07_execution_check',CHANGE/'scripts/check_execution.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as folder,self.assertRaises(AssertionError):module.verify_execution(Path(folder))
    def test_active_and_archived_artifact_resolution(self):
        from tests.query_test_support import change_directory
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);active=root/'openspec/changes/unified-readonly-query';active.mkdir(parents=True)
            self.assertEqual(change_directory(root),active)
            archived=active.parent/'archive/2026-10-16-unified-readonly-query';archived.parent.mkdir();active.rename(archived)
            self.assertEqual(change_directory(root),archived)
            (root/'AGENT.md').write_text('fixture root')
            script=archived/'scripts/check_execution.py';script.parent.mkdir();script.write_text('')
            import importlib.util
            spec=importlib.util.spec_from_file_location('a07_execution_resolver',CHANGE/'scripts/check_execution.py')
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(module.repository_root(script),root.resolve())
