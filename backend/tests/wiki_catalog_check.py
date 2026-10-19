"""Bounded metadata catalog checks; private SQLite fixtures only."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from app.rag.contracts import load_documents
from tests.query_test_support import query_fixture


class CatalogChecks(unittest.TestCase):
    def api(self, fixture):
        from app.wiki.catalog_store import CatalogStore
        from app.wiki.router import router, get_catalog_store
        app = FastAPI(); app.include_router(router, prefix='/api')
        app.dependency_overrides[get_catalog_store] = lambda: CatalogStore(fixture.engine, fixture.source, now=fixture.now)
        return TestClient(app)

    def test_metadata_pagination(self):
        from app.wiki.catalog import build_catalog, CatalogOptions
        from app.wiki.catalog_store import CatalogStore
        with query_fixture() as f:
            snapshot = CatalogStore(f.engine, f.source, now=f.now).capture()
            first = build_catalog(snapshot, CatalogOptions())
            self.assertEqual(len(first['cards']), 20)
            self.assertTrue(first['hasMore'])
            second = build_catalog(snapshot, CatalogOptions(offset=20, expected_revision=first['catalogRevision']))
            ids = [r['id'] for r in first['cards'] + second['cards']]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(first['cards'], sorted(first['cards'], key=lambda r:(r['title'],r['id'],r['version'])))
            for card in first['cards']:
                self.assertNotIn('content', card); self.assertNotIn('wikiCard', card)
            filtered = build_catalog(snapshot, CatalogOptions(q='MARGIN'))
            self.assertEqual(filtered['total'],2)
            exact=build_catalog(snapshot,CatalogOptions(q='metric-margin'))
            self.assertEqual(exact['total'],1)
            self.assertEqual(exact['cards'][0]['version'],3)
            empty = build_catalog(snapshot, CatalogOptions(offset=10000,expected_revision=first['catalogRevision']))
            self.assertEqual(empty['cards'], []); self.assertFalse(empty['hasMore'])
            with self.api(f) as client:
                for query in ('pageSize=26','offset=-1','knowledgeType=bogus','offset=20','q='+'a'*301):
                    self.assertEqual(client.get('/api/wiki/catalog?'+query).status_code,422)
                self.assertEqual(client.get('/api/wiki/catalog?pageSize=25').status_code,200)

    def test_catalog_revision_tracks_eligibility(self):
        from app.wiki.catalog import build_catalog, CatalogOptions, CatalogError
        from app.wiki.catalog_store import CatalogStore
        with query_fixture() as f:
            snap = CatalogStore(f.engine,f.source,now=f.now).capture()
            before = build_catalog(snap,CatalogOptions())
            for changed in (replace(snap,business_date=snap.business_date.replace(day=17)),
                            replace(snap,origins={'missing':{'available':False,'revision':2,'source_hash':'changed'}}),
                            replace(snap,manifest={**snap.manifest,'barriers':{before['cards'][0]['id']:1}})):
                after = build_catalog(changed,CatalogOptions())
                self.assertEqual(before['sourceRevision'],after['sourceRevision'])
                self.assertNotEqual(before['catalogRevision'],after['catalogRevision'])
                with self.assertRaises(CatalogError) as caught:
                    build_catalog(changed,CatalogOptions(offset=20,expected_revision=before['catalogRevision']))
                self.assertEqual(caught.exception.status_code,409)
            with self.assertRaises(CatalogError):
                build_catalog(snap,CatalogOptions(q='different',offset=20,expected_revision=before['catalogRevision']))

    def test_actual_expiry_and_simulation_policy(self):
        from app.wiki.catalog import CatalogOptions,build_catalog
        from app.wiki.catalog_store import CatalogStore
        from tests.wiki_check import draft,reviewed
        raw=draft();raw['valid_from']='2026-01-01';raw['valid_to']='2026-10-16'
        with query_fixture([reviewed(raw)]) as f:
            reader=CatalogStore(f.engine,f.source,now=f.now);snap=reader.capture()
            before=build_catalog(snap,CatalogOptions())
            after=build_catalog(replace(snap,business_date=snap.business_date.replace(day=17)),CatalogOptions())
            self.assertEqual(before['total'],1);self.assertEqual(after['total'],0)
            self.assertNotEqual(before['catalogRevision'],after['catalogRevision'])
        raw=draft();raw['valid_from']='2026-01-01';raw['source_type']='simulated';raw['governance']['evidence_level']='simulated'
        with query_fixture([reviewed(raw)]) as f:
            snap=CatalogStore(f.engine,f.source,now=f.now).capture()
            self.assertEqual(build_catalog(snap,CatalogOptions())['total'],0)
            included=build_catalog(snap,CatalogOptions(include_simulated=True))
            self.assertEqual(included['total'],1);self.assertEqual(included['cards'][0]['evidenceLevel'],'simulated')

    def test_pending_index_still_reads_healthy_source(self):
        with query_fixture() as f, self.api(f) as client:
            packet=client.get('/api/wiki/catalog').json()
            self.assertEqual(packet['indexStatus'],'pending')
            self.assertGreater(packet['total'],0)
            self.assertEqual(packet['cards'][0]['currentEligibility'],'eligible')

    def test_no_projection_or_source_snapshot_payload_read(self):
        from app.wiki.catalog_store import CatalogStore
        statements=[]
        with query_fixture() as f:
            def observed(conn,cursor,statement,parameters,context,many):statements.append(statement.lower())
            event.listen(f.engine,'before_cursor_execute',observed)
            try:CatalogStore(f.engine,f.source,now=f.now).capture()
            finally:event.remove(f.engine,'before_cursor_execute',observed)
        fetched=[s for s in statements if s.lstrip().startswith('select') and 'pragma' not in s]
        self.assertFalse(any('chunks_json' in s or 'source_snapshot' in s for s in fetched))
        self.assertFalse(any(s.lstrip().startswith(('insert','update','delete','create','alter')) for s in statements))

    def test_catalog_source_and_budget_failures(self):
        from app.wiki.catalog import CatalogError
        from app.wiki.catalog_store import CatalogStore, CatalogBudget
        with query_fixture() as f:
            with f.engine.begin() as conn:conn.execute(text('DROP TABLE rag_index_state'))
            with self.api(f) as client:self.assertEqual(client.get('/api/wiki/catalog').status_code,503)
        for row in ({'text':'a'*2097153},):
            with self.assertRaises(CatalogError):CatalogBudget().consume('wiki',row)
        budget=CatalogBudget()
        for _ in range(10000):budget.consume('wiki',{})
        with self.assertRaises(CatalogError):budget.consume('wiki',{})
        with query_fixture() as f:
            budget=CatalogBudget(seconds=0)
            with self.assertRaises(CatalogError):CatalogStore(f.engine,f.source,now=f.now).capture(budget=budget)
            class Changing(CatalogStore):
                def after_database(self):f.write_source([])
            with self.assertRaises(CatalogError) as caught:Changing(f.engine,f.source,now=f.now).capture()
            self.assertEqual(caught.exception.status_code,409)

    def test_immutable_version_and_legacy_admission(self):
        from sqlalchemy.orm import Session
        from app.models import RagDocument
        from app.wiki.catalog import CatalogError
        from app.wiki.catalog_store import CatalogStore
        with query_fixture() as f:
            doc=f.source.snapshot().documents[0]
            with Session(f.engine) as session:
                session.add(RagDocument(pk=doc['id']+'@'+str(doc['version']),document_id=doc['id'],version=doc['version'],
                    title=doc['title'],knowledge_type=doc['knowledge_type'],status=doc['status'],content=doc['content'],
                    content_hash='0'*64,source_version_hash='0'*64));session.commit()
            with self.assertRaises(CatalogError) as conflict:CatalogStore(f.engine,f.source,now=f.now).capture()
            self.assertEqual(conflict.exception.status_code,409)
            with f.engine.begin() as conn:
                conn.execute(text("UPDATE rag_document SET source_version_hash=NULL,content='rewritten'"))
            with self.assertRaises(CatalogError) as legacy_conflict:CatalogStore(f.engine,f.source,now=f.now).capture()
            self.assertEqual(legacy_conflict.exception.status_code,409)
            with f.engine.begin() as conn:
                conn.execute(text("UPDATE rag_document SET source_version_hash=NULL,content=:huge"),{'huge':'z'*2097153})
            with self.assertRaisesRegex(CatalogError,'catalog_input_limit'):CatalogStore(f.engine,f.source,now=f.now).capture()

    def test_pool_acquisition_and_connection_failure_are_bounded(self):
        import tempfile,time
        from sqlalchemy import create_engine
        from app.wiki.catalog import CatalogError
        from app.wiki.catalog_store import CatalogStore,CatalogBudget
        with query_fixture([]) as f, tempfile.TemporaryDirectory() as directory:
            engine=create_engine('sqlite:///'+directory+'/pool.db',pool_size=1,max_overflow=0,pool_timeout=30)
            try:
                with engine.connect():
                    start=time.monotonic()
                    with self.assertRaises(CatalogError):CatalogStore(engine,f.source,now=f.now).capture(budget=CatalogBudget(.08))
                    self.assertLess(time.monotonic()-start,.5)
            finally:engine.dispose()
            broken=create_engine('sqlite:///'+directory+'/missing/db.sqlite')
            try:
                with self.assertRaisesRegex(CatalogError,'catalog_database_unavailable'):
                    CatalogStore(broken,f.source,now=f.now).capture()
            finally:broken.dispose()

    def test_origin_deletion_hides_reviewed_document_and_changes_revision(self):
        from sqlalchemy.orm import Session
        from app.models import ActionCase,KnowledgeArchive,KnowledgeCandidate
        from app.wiki.candidates import capture
        from app.wiki.contracts import approve
        from app.wiki.catalog import CatalogOptions,build_catalog
        from app.wiki.catalog_store import CatalogStore
        with query_fixture([]) as f:
            with Session(f.engine) as session:
                case=ActionCase(id='catalog-case',status='resolved',origin='engine',created_at='2026-01-01')
                archive=KnowledgeArchive(entry_type='resolution',source_id='catalog-case',code='C',title='Reported case',content='report',note='unverified',created_at='2026-01-01')
                session.add_all([case,archive]);session.flush();candidate,_=capture(session,archive,case)
                candidate.payload=approve(candidate.payload,actor='test:catalog',reason='report only',base_version=0)
                candidate.status='reviewed';candidate_id=candidate.candidate_id;doc=deepcopy(candidate.payload);session.commit()
            f.write_source([doc]);reader=CatalogStore(f.engine,f.source)
            before=build_catalog(reader.capture(),CatalogOptions());self.assertEqual(before['total'],1)
            with Session(f.engine) as session:
                candidate=session.get(KnowledgeCandidate,candidate_id)
                candidate.review_events=[{'eventType':'source_deleted'}];session.commit()
            after=build_catalog(reader.capture(),CatalogOptions())
            self.assertEqual(after['total'],0)
            self.assertEqual(before['sourceRevision'],after['sourceRevision'])
            self.assertNotEqual(before['catalogRevision'],after['catalogRevision'])

    def test_invalid_barrier_fails_closed(self):
        from app.wiki.catalog import CatalogOptions,CatalogError,build_catalog
        from app.wiki.catalog_store import CatalogStore
        with query_fixture() as f:
            snap=CatalogStore(f.engine,f.source,now=f.now).capture()
            broken=replace(snap,manifest={**snap.manifest,'barriers':{'metric-margin':-1}})
            with self.assertRaises(CatalogError):build_catalog(broken,CatalogOptions())

if __name__=='__main__':unittest.main()
