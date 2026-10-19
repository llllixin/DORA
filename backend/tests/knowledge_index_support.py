"""Real disposable SQLite/source fixtures for index consumers; never use default DB."""
from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from sqlalchemy import create_engine
from app import db
from app.models import Base
from app.rag.migration import init_rag_index
from app.rag.source import KnowledgeSource
from app.rag.repository import RagRepository
from app.rag.indexer import RagIndexer
from app.rag.embeddings import HashEmbeddingProvider
from tests.model_runtime_support import MemoryRuns


@contextmanager
def temporary_index(documents, provider=None, runs=None):
    with TemporaryDirectory(prefix='dora-a06-fixture-') as folder:
        root=Path(folder);engine=create_engine('sqlite:///'+str(root/'db.sqlite'))
        path=root/'documents.json'
        def write(docs):path.write_text(json.dumps(docs,ensure_ascii=False))
        write(documents);Base.metadata.create_all(engine);init_rag_index(engine)
        try:
            with patch.object(db,'_engine',engine):
                repo=RagRepository(source=KnowledgeSource(path))
                yield repo,RagIndexer(repo,provider or HashEmbeddingProvider(),runs or MemoryRuns()),write
        finally:engine.dispose()
