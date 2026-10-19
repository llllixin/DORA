"""Imports must fit the downstream view and immutable evidence before commit."""
from datetime import date,timedelta
import asyncio,io,json,unittest
from sqlalchemy.orm import Session
from app.models import BusinessRevision
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from app.main import app
from app.ingest import parse_dataset,preview_rows
from app.evidence.contracts import build_snapshot
from tests.evidence_test_support import evidence_fixture

class CapacityRepairChecks(unittest.TestCase):
    def csv(self,count,dimension='全国'):
        return ('metric_key,label,dimension,value,unit\n'+''.join('margin,%s,%s,12,%%\n'%((date(1990,1,1)+timedelta(days=n)).isoformat(),dimension) for n in range(count))).encode()
    def test_372kb_legal_csv_rejected_atomically(self):
        with evidence_fixture() as (repo,engine):
            before=repo.read_business_inputs();content=self.csv(12000)
            self.assertLess(len(content),400000)
            response=TestClient(app).post('/api/datasets',files={'file':('large.csv',content)})
            self.assertEqual(response.status_code,413,response.text)
            self.assertEqual(repo.read_business_inputs().export_inputs(),before.export_inputs())
            self.assertEqual(repo.read_business_inputs().business_version,before.business_version)
    def test_below_row_cap_but_evidence_too_large_rolls_back(self):
        with evidence_fixture() as (repo,engine):
            before=repo.read_business_inputs()
            response=TestClient(app).post('/api/datasets',files={'file':('large.csv',self.csv(7000,'中'*32))})
            self.assertEqual(response.status_code,413,response.text)
            self.assertEqual(repo.read_business_inputs().business_version,before.business_version)
            self.assertEqual(repo.read_business_inputs().export_inputs(),before.export_inputs())
    def test_supported_import_builds_complete_snapshot_and_query(self):
        with evidence_fixture() as (repo,engine):
            client=TestClient(app)
            response=client.post('/api/datasets',files={'file':('small.csv',self.csv(30))})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(build_snapshot(repo.read_business_inputs())['snapshotId'])
            response=client.post('/api/query/answer',json={'question':'最新全国利润率是多少？'})
            self.assertEqual(response.status_code,200,response.text)
            self.assertNotEqual(response.json()['status'],'limited',response.text)
    def test_upload_reads_are_bounded(self):
        from app.routers import preview_dataset,MAX_UPLOAD
        class Observed(UploadFile):
            async def read(self,size=-1):
                self.requested=size
                return await super().read(size)
        upload=Observed(filename='small.csv',file=io.BytesIO(self.csv(1)))
        asyncio.run(preview_dataset(upload))
        self.assertEqual(upload.requested,MAX_UPLOAD+1)
    def test_preview_stops_before_invalid_later_csv_row(self):
        content=self.csv(10)+b'margin,bad,'+b'x'*200000+b',12,%\n'
        self.assertEqual(len(preview_rows(content,'preview.csv')['sampleRows']),10)
    def test_final_generation_byte_is_included_in_capacity_admission(self):
        from app.ingest import IngestCapacityError
        with evidence_fixture() as (repo,engine):
            with Session(engine) as s:s.get(BusinessRevision,'dora:default').generation=9;s.commit()
            before=repo.read_business_inputs()
            items=parse_dataset('boundary.csv',self.csv(7677))
            items[1000]['unit']='%xxxxx'
            with self.assertRaises(IngestCapacityError):repo.import_dataset(items,{'updated_at':'fixture'})
            self.assertEqual(repo.read_business_inputs().business_version,before.business_version)
            self.assertEqual(repo.read_business_inputs().export_inputs(),before.export_inputs())

if __name__=='__main__':unittest.main()
