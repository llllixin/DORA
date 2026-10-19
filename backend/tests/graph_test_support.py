"""Disposable graph fixtures, built through real A05 capture paths."""
from contextlib import contextmanager
import json
from pathlib import Path
from unittest.mock import patch
from app.evidence.action import create_case_captured
from app.rag.source import KnowledgeSource
from tests.evidence_test_support import evidence_fixture


@contextmanager
def graph_fixture():
    with evidence_fixture() as (repo, engine):
        path = Path(engine.url.database).parent / 'documents.json'
        path.write_text('[]')
        source = KnowledgeSource(path)
        with patch.dict('os.environ', {'DORA_GRAPH_ENABLED': 'true'}):
            yield repo, engine, source


def open_case(repo):
    return create_case_captured(repo, insight_type_id='p1',
                               expected_revision=repo.read_business_inputs().business_version['revision'])


def install_document(engine, source, document):
    from sqlalchemy.orm import Session
    from app.models import RagDocument
    from app.rag.identity import source_version_hash
    rows = json.loads(source.path.read_text())
    if not any((r['id'],r['version'])==(document['id'],document['version']) for r in rows):rows.append(document)
    source.path.write_text(json.dumps(rows, ensure_ascii=False))
    with Session(engine) as s:
        s.add(RagDocument(pk=f"{document['id']}@{document['version']}", document_id=document['id'],
                         version=document['version'], title=document['title'], content=document['content'],
                         knowledge_type=document['knowledge_type'], status=document['status'],
                         content_hash=source_version_hash(document), metadata_json={}, active=True,
                         source_snapshot=document, source_version_hash=source_version_hash(document),
                         created_at='fixture', updated_at='fixture'))
        s.commit()
