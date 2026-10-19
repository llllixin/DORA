"""P2 index deadline regressions using an explicitly disposable PostgreSQL DB."""
from copy import deepcopy
from dataclasses import replace
import os
import json
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from urllib.parse import urlsplit
from uuid import uuid4
from sqlalchemy import delete, event
from app import db
from app.models import RagChunk, RagDocument, RagIndexProjection
from app.rag.embeddings import HashEmbeddingProvider
from app.rag.indexer import RagIndexer
from app.rag.repository import RagRepository
from app.rag.source import KnowledgeSource
from app.rag.contracts import load_documents
from app.runtime.budget import load_profile
from app.runtime.contracts import RuntimeFailure
from app.runtime.executor import RunContext
from tests.model_runtime_check import Clock
from tests.model_runtime_support import MemoryRuns
from tests.wiki_check import draft, reviewed


class IndexDeadlinePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = urlsplit(os.environ.get('DATABASE_URL', ''))
        if not (url.scheme == 'postgresql+psycopg' and url.hostname == '127.0.0.1'
                and url.username == 'dora_a06' and url.path == '/dora_a06' and url.port):
            raise RuntimeError('explicit disposable loopback dora_a06 database required')
        db.init_db()

    def assert_rolls_back(self, phase):
        identity = 'p2-pg-' + uuid4().hex
        raw = draft(); raw['id'] = identity; raw['version'] = 1
        old = reviewed(raw)
        newer = deepcopy(raw); newer['version'] = 2; newer['title'] += ' revision two'
        newer = reviewed(newer, base=1)
        temp=TemporaryDirectory();source=Path(temp.name)/'documents.json';canonical=load_documents()
        source.write_text(json.dumps([*canonical,old],ensure_ascii=False))
        runs = MemoryRuns(); repository = RagRepository(source=KnowledgeSource(source))
        index = RagIndexer(repository, HashEmbeddingProvider(), runs)
        clock = Clock(); observed = []
        def slow_statement(conn, cursor, statement, parameters, context, executemany):
            upper = statement.upper()
            matches = ('INSERT INTO RAG_DOCUMENT' in upper if phase == 'insert'
                       else 'UPDATE RAG_INDEX_STATE' in upper)
            if matches:
                observed.append(phase); clock.sleep(.02)
        engine = db.get_engine()
        try:
            index.rebuild([old])
            before = repository.get_document(identity, 1)
            self.assertIsNotNone(before)
            self.assertTrue(before['active'])
            chunk_ids = {c['chunk_id'] for c in repository.active_chunks() if c['document_id'] == identity}
            counts = (repository.count('documents'), repository.count('chunks'))
            run = RunContext('rag-index', repository=runs, clock=clock,
                             profile=replace(load_profile('rag-index', False), maxElapsedMs=10, attemptTimeoutMs=10))
            event.listen(engine, 'before_cursor_execute', slow_statement)
            try:
                source.write_text(json.dumps([*canonical,old,newer],ensure_ascii=False))
                with self.assertRaisesRegex(RuntimeFailure, 'deadline_exceeded'):
                    index.rebuild([newer], run_context=run)
            finally:
                event.remove(engine, 'before_cursor_execute', slow_statement)
                source.write_text(json.dumps([*canonical,old],ensure_ascii=False))
            self.assertTrue(observed, 'the real SQL phase must be exercised')
            self.assertEqual(repository.get_document(identity, 1), before)
            self.assertIsNone(repository.get_document(identity, 2))
            self.assertEqual((repository.count('documents'), repository.count('chunks')), counts)
            self.assertEqual({c['chunk_id'] for c in repository.active_chunks() if c['document_id'] == identity}, chunk_ids)
            self.assertEqual(runs.get_agent_run(run.run_id)['status'], 'limited')
        finally:
            with db.make_session() as session:
                session.execute(delete(RagIndexProjection).where(RagIndexProjection.document_pk.in_([identity+'@1',identity+'@2'])))
                session.execute(delete(RagChunk).where(RagChunk.document_id == identity))
                session.execute(delete(RagDocument).where(RagDocument.document_id == identity))
                session.commit()
            temp.cleanup()

    def test_document_flush_deadline_rolls_back_old_index(self):
        self.assert_rolls_back('insert')

    def test_activation_flush_deadline_rolls_back_old_index(self):
        self.assert_rolls_back('activation')


if __name__ == '__main__':
    unittest.main(verbosity=2)
