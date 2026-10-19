"""F02/F07 regressions: disposable SQLite/files and offline provider parsing only."""
from contextlib import ExitStack
from copy import deepcopy
from datetime import date
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError

from app import db
from app.action import flow
from app.models import ActionCase, ActionStep, KnowledgeArchive, KnowledgeCandidate, RagIndexBatch, Base
from app.rag.embeddings import OpenAIEmbeddingProvider
from app.repository import Repository
from app.runtime.contracts import RuntimeFailure
from app.wiki.candidates import CandidateService
from app.wiki.contracts import approve, canonical_hash
from app.wiki.reader import read_cards
from tests.knowledge_index_support import temporary_index
from tests.wiki_check import reviewed


class EmbeddingIndicesChecks(unittest.TestCase):
    def setUp(self):
        self.provider = OpenAIEmbeddingProvider('offline-unused', dimensions=2)

    def test_unordered_response_keeps_each_vector_bound_to_its_input(self):
        rows = [{'index': 1, 'embedding': [0., 1.]}, {'index': 0, 'embedding': [1., 0.]}]
        self.assertEqual(self.provider._parse({'data': rows}, 2), [[1., 0.], [0., 1.]])

    def test_rejects_indices_that_do_not_identify_each_input_once(self):
        for indices in [(0, 0), (-1, 2), (0, 2), (0, None), (0, True), (False, 1), (0, 1.), (0, '1')]:
            rows = [{'embedding': [1., 0.]} if i is None else {'index': i, 'embedding': [1., 0.]} for i in indices]
            with self.subTest(indices=indices), self.assertRaisesRegex(RuntimeFailure, 'invalid_vector'):
                self.provider._parse({'data': rows}, 2)

    def test_malformed_response_schema_uses_invalid_vector(self):
        for raw in [None, [], {}, {'data': None}, {'data': {}}, {'data': 'wrong'}, {'data': [None]}, {'data': [7]}, {'data': [[]]}]:
            with self.subTest(raw=raw), self.assertRaisesRegex(RuntimeFailure, 'invalid_vector'):
                self.provider._parse(raw, 1)

    def test_rejects_wrong_count_dimensions_and_nonfinite_or_nonnumeric_values(self):
        for vectors in [[], [[1., 0.], [0., 1.]], [[1.]], [[True, 0.]], [['1', 0.]], [[float('nan'), 0.]], [[float('inf'), 0.]], [[10 ** 400, 0.]]]:
            rows = [{'index': i, 'embedding': v} for i, v in enumerate(vectors)]
            with self.subTest(vectors=vectors), self.assertRaisesRegex(RuntimeFailure, 'invalid_vector'):
                self.provider._parse({'data': rows}, 1)


class WikiOriginChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.rag, self.index, self.write = self.stack.enter_context(temporary_index([]))
        self.path = self.rag.source.path
        self.business = Repository()
        with db.make_session() as session:
            session.add(ActionCase(id='repair-origin', kind='problem', case_title='Original case', status='waiting_verify', origin='engine'))
            session.add(ActionStep(case_id='repair-origin', seq=0, title='Complete step', status='done'))
            session.commit()
        flow.verify(self.business, 'repair-origin', 'resolved', note='reported handling only')
        self.candidates = CandidateService()
        self.cid = self.candidates.list()[0]['candidate_id']
        self.candidates.review(self.cid, actor='test:repair', reason='offline review', decision='approve', base_version=0)
        self.candidates.publish(self.cid, self.path)
        self.document = read_cards(self.path)[0]
        self.document_id = self.document['id']

    def client(self):
        from app.wiki.router import router
        application = FastAPI()
        application.include_router(router, prefix='/api')
        self.stack.enter_context(patch('app.wiki.router.read_cards', side_effect=lambda **kwargs: read_cards(self.path, **kwargs)))
        return TestClient(application, raise_server_exceptions=False)

    def assert_hidden_with_history(self):
        self.assertEqual(read_cards(self.path), [])
        self.assertEqual(read_cards(self.path, document_id=self.document_id), [])
        self.assertEqual(len(read_cards(self.path, document_id=self.document_id, version=1)), 1)

    def test_deleted_origin_hidden_from_current_http_list_and_detail_history_retained(self):
        client = self.client()
        self.assertEqual(len(client.get('/api/wiki/cards').json()['cards']), 1)
        self.business.delete_action_case('repair-origin')
        self.assertEqual(client.get('/api/wiki/cards').json()['cards'], [])
        self.assertEqual(client.get('/api/wiki/cards/' + self.document_id).status_code, 404)
        history = client.get('/api/wiki/cards/' + self.document_id + '?version=1')
        self.assertEqual(history.status_code, 200)
        self.assertEqual(history.json()['card']['version'], 1)

    def test_archive_change_invalidates_origin(self):
        with db.make_session() as session:
            session.scalar(select(KnowledgeArchive)).content += ' changed after review'
            session.commit()
        self.assert_hidden_with_history()

    def test_case_must_still_be_resolved(self):
        with db.make_session() as session:
            session.get(ActionCase, 'repair-origin').status = 'waiting_verify'
            session.commit()
        self.assert_hidden_with_history()

    def test_missing_candidate_cannot_retain_approval(self):
        with db.make_session() as session:
            session.delete(session.get(KnowledgeCandidate, self.cid))
            session.commit()
        self.assert_hidden_with_history()

    def test_latest_candidate_revision_blocks_old_approval_after_source_reversion(self):
        with db.make_session() as session:
            archive = session.scalar(select(KnowledgeArchive))
            original = archive.content
            archive.content = original + ' changed'
            session.commit()
        self.assertEqual(self.candidates.collect()['created'], 1)
        with db.make_session() as session:
            session.scalar(select(KnowledgeArchive)).content = original
            session.commit()
        self.assertEqual(self.candidates.collect()['created'], 1)
        self.assert_hidden_with_history()

    def test_source_deleted_marker_prevents_identical_recreated_source_from_reviving(self):
        with db.make_session() as session:
            archive = session.scalar(select(KnowledgeArchive))
            fields = {c.name: getattr(archive, c.name) for c in archive.__table__.columns if c.name != 'id'}
            case_created_at = session.get(ActionCase, 'repair-origin').created_at
        self.business.delete_action_case('repair-origin')
        with db.make_session() as session:
            session.add(ActionCase(id='repair-origin', kind='problem', case_title='Original case', status='resolved', origin='engine', created_at=case_created_at))
            session.add(KnowledgeArchive(**fields))
            session.commit()
        self.assert_hidden_with_history()

    def test_origin_revision_and_source_hash_must_match_live_candidate(self):
        for key, value in [('revision', 2), ('source_hash', '0' * 64)]:
            document = deepcopy(self.document)
            document['governance']['origin'][key] = value
            document = approve(document, actor='test:repair', reason='offline mismatch fixture', base_version=0)
            self.write([document])
            with self.subTest(field=key):
                self.assert_hidden_with_history()

    def test_candidate_review_must_remain_available(self):
        with db.make_session() as session:
            session.get(KnowledgeCandidate, self.cid).status = 'retired'
            session.commit()
        self.assert_hidden_with_history()

    def test_history_instance_identity_must_still_match(self):
        with db.make_session() as session:
            row = session.get(KnowledgeCandidate, self.cid)
            payload = deepcopy(row.payload)
            origin = payload['governance']['origin']
            origin['snapshot']['history_refs'] = {'caseInstanceId': 'original-history'}
            row.source_payload_hash = origin['source_hash'] = canonical_hash(origin['snapshot'])
            row.payload = approve(payload, actor='test:repair', reason='offline history fixture', base_version=0)
            session.get(ActionCase, 'repair-origin').history_instance_id = 'original-history'
            session.commit()
            document = deepcopy(row.payload)
        self.write([document])
        self.assertEqual(len(read_cards(self.path)), 1)
        with db.make_session() as session:
            session.get(ActionCase, 'repair-origin').history_instance_id = 'different-history'
            session.commit()
        self.assert_hidden_with_history()

    def test_newest_effective_version_does_not_fall_back_to_older_eligible_origin(self):
        newest = deepcopy(self.document)
        newest['version'] = 2
        newest['governance']['origin']['revision'] = 999
        newest = approve(newest, actor='test:repair', reason='offline mismatch fixture', base_version=1)
        self.write([self.document, newest])
        self.assert_hidden_with_history()

    def test_valid_current_origin_is_readable_without_rag_tables(self):
        engine = db.get_engine()
        Base.metadata.drop_all(engine, tables=[t for t in Base.metadata.sorted_tables if t.name.startswith('rag_')])
        self.assertEqual(len(read_cards(self.path)), 1)
        self.assertEqual(self.client().get('/api/wiki/cards').status_code, 200)

    def test_current_origin_verification_failure_is_503_history_remains_readable(self):
        client = self.client()
        engine = db.get_engine()
        def fail_candidate(connection, cursor, statement, parameters, context, many):
            if statement.lstrip().upper().startswith('SELECT') and 'knowledge_candidate' in statement:
                raise OperationalError(statement, parameters, Exception('offline injected candidate read failure'))
        event.listen(engine, 'before_cursor_execute', fail_candidate)
        try:
            self.assertEqual(client.get('/api/wiki/cards').status_code, 503)
            self.assertEqual(client.get('/api/wiki/cards/' + self.document_id).status_code, 503)
            self.assertEqual(client.get('/api/wiki/cards/' + self.document_id + '?version=1').status_code, 200)
        finally:
            event.remove(engine, 'before_cursor_execute', fail_candidate)

    def test_unverifiable_existing_lifecycle_fails_closed_but_history_is_auditable(self):
        self.index.rebuild()
        with db.make_session() as session:
            session.scalar(select(RagIndexBatch)).manifest_json = {}
            session.commit()
        client = self.client()
        self.assertEqual(client.get('/api/wiki/cards').status_code, 503)
        self.assertEqual(client.get('/api/wiki/cards/' + self.document_id + '?version=1').status_code, 200)


class WikiLifecycleChecks(unittest.TestCase):
    def test_normal_44_cards_read_before_any_rag_migration(self):
        engine = create_engine('sqlite://')
        try:
            with patch.object(db, '_engine', engine):
                self.assertEqual(len(read_cards()), 44)
        finally:
            engine.dispose()

    def test_committed_removal_barrier_blocks_restored_old_version_but_allows_new_review(self):
        first = reviewed()
        first['version'] = 1
        with temporary_index([first]) as (rag, index, write):
            index.rebuild()
            write([])
            index.rebuild()
            write([first])
            self.assertEqual(read_cards(rag.source.path), [])
            self.assertEqual(len(read_cards(rag.source.path, document_id=first['id'], version=1)), 1)
            newer = reviewed(first, base=1)
            newer['version'] = 2
            write([first, newer])
            self.assertEqual([d['version'] for d in read_cards(rag.source.path)], [2])

    def test_expired_latest_review_blocks_fallback_but_future_and_draft_do_not(self):
        from app.wiki.reader import effective_documents
        first = reviewed()
        first['version'] = 1
        future = deepcopy(first)
        future.update(version=2, valid_from='2099-01-01')
        pending = deepcopy(first)
        pending.update(version=3, status='draft')
        self.assertEqual([d['version'] for d in effective_documents([first, future, pending], on_date=date(2026, 10, 18))], [1])
        expired = deepcopy(first)
        expired.update(version=4, valid_to='2026-10-17')
        self.assertEqual(effective_documents([first, future, pending, expired], on_date=date(2026, 10, 18)), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
