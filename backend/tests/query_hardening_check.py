"""Adversarial query boundaries discovered while integrating Tasks 2–7."""
from __future__ import annotations
import unittest,json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import text,event
from sqlalchemy.orm import Session
from app.query.contracts import *
from app.query.service import QueryService
from app.query.read_view import QueryReadViewReader,CaptureBudget
from app.query.routing import classify_query
from app.query.evidence import read_run_evidence
from app.query.sources import archive_evidence,FrozenWikiRepository
from app.rag.ontology import Ontology
from app.rag.embeddings import HashEmbeddingProvider
from app.runtime.executor import RunContext
from app.runtime.contracts import RuntimeFailure,ProviderEnvelope
from app.runtime.budget import load_profile
from tests.query_test_support import query_fixture
from app.models import ActionCase,KnowledgeArchive,KnowledgeCandidate,BusinessRevision
from app.wiki.candidates import capture,mark_source_removed

class Hardening(unittest.TestCase):
    def service(self,f,provider=None):return QueryService(QueryReadViewReader(f.engine,f.source,ReadPolicy(),now=f.now),policy=ReadPolicy(),ontology=Ontology.load(),embedding_provider=provider or HashEmbeddingProvider(),run_repository=f.runs)
    def test_logical_partial_but_sql_view_failure_503(self):
        with query_fixture([]) as f:
            s=self.service(f);count=[];capture=s.reader.capture
            s.reader.capture=lambda *a,**kw:(count.append(1),capture(*a,**kw))[1]
            with f.engine.begin() as c:c.execute(text('DROP TABLE metric_series'))
            with self.assertRaises(QueryUnavailable) as error:s.answer(QueryAnswerRequest(question='最新全国利润率是多少？'))
            self.assertEqual(error.exception.code,'data_source_unavailable');self.assertEqual(count,[1])
            self.assertEqual(f.runs.rows[error.exception.run_id]['status'],'failed')
    def test_read_limit_exact_utf8_edges(self):
        r=RunContext('unified-answer');b=CaptureBudget(ReadLimits(),r.budget)
        row={'text':'中'*699000};size=len(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
        b.bytes=2097152-size;b.consume('t',row);self.assertEqual(b.bytes,2097152)
        with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):b.consume('t',{})
        with query_fixture([]) as f:
            # A finite source limit is checked before parsing/index/model work.
            f.source.path.write_text(' '*2097153)
            result=self.service(f).answer(QueryAnswerRequest(question='利润率是什么？'))
            self.assertEqual((result['status'],result['reasonCode']),('limited','read_view_limit'))
            self.assertEqual(result['budget']['providerInvocations'],0)
    def test_slow_validation_audit_blocks_late_answer(self):
        with query_fixture([]) as f:
            s=self.service(f);clock=[0.];r=RunContext('unified-answer',repository=f.runs,clock=lambda:clock[0])
            original=r.emit
            def emit(e):
                original(e)
                if e.get('type')=='query_validated':clock[0]=31
            r.emit=emit
            result=s.answer(QueryAnswerRequest(question='最新全国利润率是多少？'),run_context=r)
            self.assertEqual(result['status'],'limited');self.assertFalse(result['claims']);self.assertFalse(result['ok']);self.assertFalse(r.finished)
    def test_large_unicode_context_cap_and_whole_support(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                for n in range(10):s.add(KnowledgeArchive(entry_type='problem',source_id=str(n),code='',title='利润率处理记录',content='利润率复核。'*500,note='',created_at=''))
                s.commit()
            service=self.service(f);r=RunContext('unified-answer',repository=f.runs)
            r.profile=replace(r.profile,maxContextChars=100,maxContextChunks=2);r.budget.profile=r.profile
            result=service.answer(QueryAnswerRequest(question='有没有利润率处理记录？',topK=10),run_context=r)
            self.assertLessEqual(sum(len(e['data'].get('text','')) for e in result['evidence']),100)
            self.assertLessEqual(len(result['evidence']),2)
            self.assertNotEqual(result['status'],'answered')
    def test_business_unknown_not_promoted_and_mixed_metric_source(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                state=s.get(BusinessRevision,'dora:default');state.source_manifest={'metric:margin':'sample','metric:east_orders':'uploaded'};s.commit()
            service=self.service(f);result=service.answer(QueryAnswerRequest(question='最新全国利润率是多少？'))
            self.assertFalse(result['evidence']);self.assertEqual(result['reasonCode'],'simulated_source_excluded')
            with Session(f.engine) as s:state=s.get(BusinessRevision,'dora:default');state.source_manifest={};s.commit()
            result=service.answer(QueryAnswerRequest(question='最新全国利润率是多少？'))
            self.assertEqual(result['evidence'][0]['evidenceLevel'],'legacy_unknown');self.assertIn('来源未核验',result['answer'])
    def test_managed_deleted_and_reused_case_not_promoted(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                case=ActionCase(id='old',created_at='old',origin='engine',status='resolved')
                archive=KnowledgeArchive(entry_type='lesson',source_id='old',code='old',title='利润率处理记录',content='利润率排查。',note='',created_at='old')
                s.add_all([case,archive]);s.flush();candidate,_=capture(s,archive,case);mark_source_removed(s,['old']);s.commit()
            result=self.service(f).search(QuerySearchRequest(query='利润率',sourceKinds=['archive']))
            self.assertFalse(result['evidence'])
            with Session(f.engine) as s:
                case=s.get(ActionCase,'old');case.created_at='new';s.commit()
            result=self.service(f).search(QuerySearchRequest(query='利润率',sourceKinds=['archive']))
            self.assertFalse(result['evidence'])
    def test_all_archive_kinds_stay_unreviewed_record(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                for kind in ('problem','opportunity','change','lesson'):s.add(KnowledgeArchive(entry_type=kind,source_id=kind,code=kind,title='利润率处理记录',content='利润率排查。',note='',created_at=''))
                s.commit()
            result=self.service(f).search(QuerySearchRequest(query='利润率',sourceKinds=['archive'],topK=10))
            self.assertEqual(len(result['evidence']),4)
            self.assertTrue(all(e['knowledgeType']=='case' and e['approvalStatus']=='unreviewed_record' and e['archiveVersion'] is None for e in result['evidence']))
    def test_all_embedding_faults_have_specific_fallback(self):
        from app.query.sources import wiki_evidence
        with query_fixture() as f:
            f.indexer.rebuild();s=self.service(f)
            p=classify_query('利润率是什么？',s.ontology,on_date=f.now().date())
            view=s.reader.capture(p,run_context=RunContext('unified-answer'))
            for case,reason in [('short','invalid_vector'),('many','invalid_vector'),('nan','invalid_vector'),('dimension','invalid_vector'),('responseModel','embedding_profile_mismatch'),('profile','embedding_profile_mismatch')]:
                class Provider(HashEmbeddingProvider):
                    def embed(self,texts):
                        v=[0.]*self.dimensions
                        return {'short':[],'many':[v,v],'nan':[[float('nan')]*self.dimensions],'dimension':[[0.]]}.get(case,[v])
                provider=Provider();r=RunContext('unified-answer')
                if case=='profile':provider.model='wrong-space'
                if case=='responseModel':
                    original=r.execute
                    def execute(*args,**kw):
                        result=original(*args,**kw)
                        for e in r.events:
                            if e.get('type')=='model_attempt':e['responseModel']='wrong-response'
                        return result
                    r.execute=execute
                result=wiki_evidence(view,'利润率',QueryOptions(),ReadPolicy(),run_context=r,embedding_provider=provider)
                self.assertTrue(result['evidence'],case);self.assertEqual(result['fallbackReason'],reason,case)
    def test_one_request_date_anchor(self):
        with query_fixture([]) as f:
            s=self.service(f);calls=[];now=f.now()
            def ticking():calls.append(1);return now if len(calls)==1 else now.replace(day=17)
            s.reader.now=ticking
            value=s.answer(QueryAnswerRequest(question='今天全国利润率是多少？'))
            self.assertEqual(len(calls),1);self.assertTrue(value['readAt'].startswith('2026-10-16'))
    def test_parent_run_repeated_evidence_different_read_at(self):
        from app.query.contracts import seal_evidence
        with query_fixture([]) as f:
            r=RunContext('readonly-agent',repository=f.runs)
            e=seal_evidence({'sourceKind':'archive','data':{'text':'利润率排查。'},'readAt':'one'})
            for stamp in ('one','two'):r.emit({'type':'tool_result','result':{'contractVersion':CONTRACT_VERSION,'evidence':[{**e,'readAt':stamp}]}})
            self.assertEqual(read_run_evidence(f.runs,r.run_id,e['evidenceId'])['readAt'],'one')
    def test_ambiguous_input_rows_require_clarification(self):
        rows=[dict(metric_key='margin',label=label,value=1,dimension='全国',unit='%') for label in ('W1','2026-10-16')]
        with query_fixture([],metric_rows=rows) as f:
            result=self.service(f).answer(QueryAnswerRequest(question='最新全国利润率是多少？'))
            self.assertEqual(result['status'],'clarification_required');self.assertEqual(result['reasonCode'],'incomparable_periods')
            self.assertFalse(result['evidence'])
    def test_explicit_historical_windows_do_not_read_latest(self):
        with query_fixture([]) as f:
            service=self.service(f)
            for phrase in ('2025年','2025-10-16','上月','上个月','W2','最近7天','近7天','明天','昨日','9月份','Q2'):
                value=service.answer(QueryAnswerRequest(question=phrase+'全国利润率是多少？'))
                self.assertEqual((value['status'],value['reasonCode']),('abstained','unsupported_time_range'),phrase)
                self.assertFalse(value['evidence'],phrase)
    def test_business_revision_unready_is_503_not_empty(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:s.query(BusinessRevision).delete();s.commit()
            with self.assertRaises(QueryUnavailable) as error:self.service(f).answer(QueryAnswerRequest(question='最新全国利润率是多少？'))
            self.assertEqual(error.exception.code,'required_sources_unavailable');self.assertTrue(error.exception.run_id)
    def test_corrupt_wiki_503_and_healthy_business_partial(self):
        from app.models import RagIndexProjection
        with query_fixture() as f:
            f.indexer.rebuild()
            with Session(f.engine) as session:
                for row in session.query(RagIndexProjection):row.chunks_json=[]
                session.commit()
            service=self.service(f)
            with self.assertRaises(QueryUnavailable):service.answer(QueryAnswerRequest(question='利润率是什么？'))
            value=service.answer(QueryAnswerRequest(question='利润率是什么，最新全国是多少？'))
            self.assertEqual(value['status'],'partial');self.assertIn('definition',value['missingParts'])
            wiki=next(s for s in value['sourceStates'] if s['sourceKind']=='wiki')
            self.assertEqual((wiki['state'],wiki['reasonCode']),('unavailable','index_corrupt'))
            self.assertTrue(any(e['sourceKind']=='business' for e in value['evidence']))
    def test_immutable_wiki_conflict_preserves_409(self):
        with query_fixture() as f:
            f.indexer.rebuild()
            from app.rag.contracts import load_documents
            docs=load_documents(f.source.path)
            for d in docs:
                if d['id']=='metric-margin' and d.get('schema_version')==2:
                    from app.wiki.contracts import approve
                    d['aliases'].append('same-version-changed-fixture')
                    replacement=approve(d,actor='fixture',reason='valid reviewed payload, deliberately reused version',base_version=d['version']-1)
                    d.clear();d.update(replacement)
            f.write_source(docs)
            with self.assertRaises(QueryConflict) as error:self.service(f).answer(QueryAnswerRequest(question='利润率是什么？'))
            self.assertEqual(error.exception.code,'document_version_conflict')
    def test_origin_candidate_and_available_rows_count_toward_capture_budget(self):
        from app.rag.index_store import RagIndexStore
        with query_fixture([]) as f:
            with Session(f.engine) as session:
                session.add(KnowledgeCandidate(candidate_id='large-origin',entry_type='problem',source_id='old',source_payload_hash='f'*64,revision=1,payload={'text':'中'*800000},evidence_level='reported',status='draft',review_events=[{'eventType':'source_deleted'}],created_at=''))
                session.commit()
            r=RunContext('unified-answer');budget=CaptureBudget(ReadLimits(),r.budget)
            docs=[{'governance':{'origin':{'candidate_id':'large-origin'}}}]
            with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):
                RagIndexStore().read_snapshot(documents=docs,consume_row=budget.consume)
            self.assertEqual(r.budget.invocations,0)
    def test_origin_available_case_and_archive_rows_are_bounded(self):
        from app.rag.index_store import RagIndexStore
        for large_table in ('case','archive'):
            with query_fixture([]) as f:
                with Session(f.engine) as session:
                    session.add(ActionCase(id='origin',status='resolved',origin='engine',created_at='same',archive='中'*800000 if large_table=='case' else ''))
                    session.add(KnowledgeArchive(entry_type='problem',source_id='origin',code='',title='记录',content='中'*800000 if large_table=='archive' else '记录',note='',created_at='same'))
                    session.add(KnowledgeCandidate(candidate_id='origin-candidate',entry_type='problem',source_id='origin',source_payload_hash='f'*64,revision=1,payload={},evidence_level='reported',status='reviewed',review_events=[],created_at=''))
                    session.commit()
                run=RunContext('unified-answer');budget=CaptureBudget(ReadLimits(),run.budget)
                with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):
                    RagIndexStore().read_snapshot(documents=[{'governance':{'origin':{'candidate_id':'origin-candidate'}}}],consume_row=budget.consume)
                self.assertGreaterEqual(budget.rows,2)
