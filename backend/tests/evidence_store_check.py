import importlib
import unittest
from copy import deepcopy
from sqlalchemy import create_engine,text,select
from sqlalchemy.orm import Session
from app import models
from app.evidence.contracts import build_snapshot,EvidenceError
from tests.evidence_test_support import frozen_inputs,evidence_fixture


class EvidenceStoreChecks(unittest.TestCase):
    def test_migration_fault_blocks_capture_but_not_business_and_recovers(self):
        from app.evidence.migrations import init_evidence,require_evidence_ready
        from app.evidence.action import create_case_captured
        from sqlalchemy import event
        with evidence_fixture() as (repo,engine):
            before=repo.read_business_inputs().business_version
            with engine.begin() as c:c.execute(text('ALTER TABLE action_case DROP COLUMN history_instance_id'))
            def fail(conn,cursor,statement,*args):
                if statement.startswith('ALTER TABLE action_case ADD COLUMN'):raise RuntimeError('DDL fault')
            event.listen(engine,'before_cursor_execute',fail)
            try:
                with self.assertRaises(EvidenceError):init_evidence(engine)
                with self.assertRaises(EvidenceError):require_evidence_ready(engine)
                self.assertEqual(repo.read_business_inputs().business_version,before)
                with self.assertRaises(EvidenceError):create_case_captured(repo,insight_type_id='p1',expected_revision=before['revision'])
            finally:event.remove(engine,'before_cursor_execute',fail)
            init_evidence(engine);init_evidence(engine);require_evidence_ready(engine)
            self.assertTrue(create_case_captured(repo,insight_type_id='p1',expected_revision=before['revision'])['created'])
    def api(self):
        self.assertTrue(hasattr(models,'EvidenceSnapshot'),'history persistence not implemented')
        return importlib.import_module('app.evidence.repository')

    def test_repeated_capture_retains_first_timestamp(self):
        m=self.api()
        with evidence_fixture() as (repo,engine),Session(engine) as s:
            store=m.EvidenceRepository(s);p=build_snapshot(repo.read_business_inputs())
            a=store.put_snapshot(p,captured_at='first');b=store.put_snapshot(p,captured_at='later')
            s.commit();self.assertEqual(b['capturedAt'],'first');self.assertEqual(a,b)
            self.assertEqual(len(s.scalars(select(models.EvidenceSnapshot)).all()),1)
            corrupt=deepcopy(p);corrupt['payload']['rawSeries'][0]['value']=0
            with self.assertRaises(EvidenceError):store.put_snapshot(corrupt,captured_at='invalid')

    def test_old_schema_migration_is_idempotent_and_fail_closed(self):
        self.api();from app.evidence.migrations import init_evidence,require_evidence_ready
        engine=create_engine('sqlite://')
        try:
            with engine.begin() as c:
                for name in ['action_case','watch_target','watch_event']:c.execute(text(f'CREATE TABLE {name} (id VARCHAR(32) PRIMARY KEY)'))
            init_evidence(engine);init_evidence(engine);require_evidence_ready(engine)
            with engine.connect() as c:self.assertEqual(c.execute(text('SELECT count(*) FROM evidence_snapshot')).scalar(),0)
            bad=create_engine('sqlite://')
            try:
                with self.assertRaises(EvidenceError):require_evidence_ready(bad)
            finally:bad.dispose()
        finally:engine.dispose()

    def test_deadline_rejects_before_commit(self):
        self.api();from app.evidence.service import capture_transaction
        from app.evidence.deadline import CaptureDeadline
        with evidence_fixture() as (repo,engine):
            now=[0.0];d=CaptureDeadline(clock=lambda:now[0])
            with self.assertRaises(EvidenceError) as e:
                with capture_transaction(repo,deadline=d) as (tx,frozen,deadline):
                    importlib.import_module('app.evidence.repository').EvidenceRepository(tx._session).put_snapshot(build_snapshot(frozen),captured_at='one')
                    now[0]=3
            self.assertEqual(e.exception.code,'evidence_capture_timeout')
            with Session(engine) as s:self.assertEqual(len(s.scalars(select(models.EvidenceSnapshot)).all()),0)


if __name__=='__main__':unittest.main()
