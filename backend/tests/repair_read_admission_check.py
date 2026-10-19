"""Oversized database payloads must be rejected before ORM materialization."""
from datetime import date
import unittest
from sqlalchemy import event
from sqlalchemy.orm import Session
from app.models import KnowledgeArchive,KnowledgeCandidate,ActionCase,BusinessRevision,RagDocument,RagIndexProjection,RagIndexBatch
from app.query.read_view import QueryReadViewReader,CaptureBudget
from app.query.contracts import ReadLimits
from app.query.routing import classify_query
from app.rag.ontology import Ontology
from app.runtime.executor import RunContext
from app.runtime.contracts import RuntimeFailure
from tests.query_test_support import query_fixture

class ReadAdmissionRepairChecks(unittest.TestCase):
    def capture_without_loading(self,f,model,question):
        loaded=[]
        def loaded_row(row,context):loaded.append(row)
        event.listen(model,'load',loaded_row)
        try:
            plan=classify_query(question,Ontology.load(),on_date=date(2026,10,16))
            with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):
                QueryReadViewReader(f.engine,f.source,now=f.now).capture(plan,run_context=RunContext('unified-answer'))
        finally:event.remove(model,'load',loaded_row)
        self.assertEqual(loaded,[],'oversized payload entered Python before admission')
    def test_archive_body(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                s.add(KnowledgeArchive(entry_type='lesson',source_id='big',title='利润率',content='大'*1048576));s.commit()
            self.capture_without_loading(f,KnowledgeArchive,'利润率有哪些历史处理记录？')
    def test_action_body(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:s.add(ActionCase(id='big',archive='x'*3145728));s.commit()
            self.capture_without_loading(f,ActionCase,'利润率有哪些历史处理记录？')
    def test_business_manifest(self):
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                s.get(BusinessRevision,'dora:default').source_manifest={'large':'x'*3145728};s.commit()
            self.capture_without_loading(f,BusinessRevision,'最新全国利润率是多少？')
    def test_index_bodies(self):
        for model,field in ((RagDocument,'source_snapshot'),(RagIndexProjection,'chunks_json'),(RagIndexBatch,'manifest_json')):
            with self.subTest(model=model.__name__),query_fixture() as f:
                f.indexer.rebuild()
                with Session(f.engine) as s:
                    row=s.query(model).first();setattr(row,field,{'large':'x'*3145728});s.commit()
                self.capture_without_loading(f,model,'利润率是什么？')
    def test_batch_bytes_are_charged_before_document_admission(self):
        with query_fixture() as f:
            f.indexer.rebuild()
            with Session(f.engine) as s:
                batch=s.query(RagIndexBatch).first()
                batch.manifest_json={**batch.manifest_json,'padding':'x'*1200000}
                row=s.query(RagDocument).first()
                row.source_snapshot={**row.source_snapshot,'padding':'x'*1200000}
                s.commit()
            self.capture_without_loading(f,RagDocument,'利润率是什么？')
    def test_origin_rows_are_admitted_and_charged_sequentially(self):
        from app.rag.index_store import RagIndexStore
        with query_fixture([]) as f:
            with Session(f.engine) as s:
                s.add(ActionCase(id='origin',status='resolved',archive='x'*1400000))
                s.add(KnowledgeArchive(entry_type='problem',source_id='origin',content='x'*200000))
                s.add(KnowledgeCandidate(candidate_id='c-origin',entry_type='problem',source_id='origin',source_payload_hash='f'*64,
                    revision=1,payload={'padding':'x'*600000},evidence_level='reported',status='reviewed',review_events=[],created_at=''))
                s.commit()
            loaded=[]
            def observe(row,context):loaded.append(row)
            event.listen(KnowledgeArchive,'load',observe)
            budget=CaptureBudget(ReadLimits(),RunContext('unified-answer').budget)
            try:
                with self.assertRaisesRegex(RuntimeFailure,'read_view_limit'):
                    RagIndexStore().read_snapshot(documents=[{'governance':{'origin':{'candidate_id':'c-origin'}}}],consume_row=budget.consume,admit_rows=budget.admit)
            finally:event.remove(KnowledgeArchive,'load',observe)
            self.assertEqual(loaded,[],'archive must be refused after accounting for the admitted case')

if __name__=='__main__':unittest.main()
