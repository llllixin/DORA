"""A07 private fixtures; never connect to an implicit database."""
from contextlib import contextmanager
from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from app import db
from app.models import MetricSeries,BusinessRevision
from app.business_store import initialize_scope
from app.rag.contracts import load_documents
from tests.knowledge_index_support import temporary_index
from tests.model_runtime_support import MemoryRuns

@contextmanager
def query_fixture(source_documents=None,metric_rows=None,source_mode='uploaded'):
    docs=load_documents() if source_documents is None else source_documents
    runs=MemoryRuns()
    with temporary_index(docs,runs=runs) as (repo,indexer,write):
        engine=db.get_engine()
        with Session(engine) as session:
            initialize_scope(session);state=session.get(BusinessRevision,'dora:default')
            rows=metric_rows if metric_rows is not None else [dict(metric_key='margin',label='当前',dimension='全国',value=12,unit='%')]
            state.source_manifest={'metric:'+r['metric_key']:source_mode for r in rows}
            for row in rows:session.add(MetricSeries(**row))
            session.commit()
        yield SimpleNamespace(engine=engine,repository=repo,source=repo.source,indexer=indexer,runs=runs,write_source=write,
                              now=lambda:datetime(2026,10,16,10,tzinfo=ZoneInfo('Asia/Shanghai')))

def change_directory(root=None):
    from pathlib import Path
    root=Path(root) if root is not None else Path(__file__).resolve().parents[2]
    base=root/'openspec/changes'
    candidates=[p for p in [base/'unified-readonly-query',*base.glob('archive/*-unified-readonly-query')] if p.is_dir()]
    if len(candidates)!=1:raise AssertionError('exactly one A07 change directory required')
    return candidates[0]
