"""Read from the authoritative source, independently of index sync."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from app.rag.contracts import load_documents
from app.rag.lifecycle import select_versions
from app.wiki.eligibility import current_state, origin_matches


def effective_documents(documents, on_date=None, *, barriers=None):
    today=on_date or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    return select_versions(documents,on_date=today,barriers=barriers or {})['eligible']


def read_cards(path=None, document_id=None, version=None):
    documents=load_documents(Path(path) if path else None)
    if document_id and version is not None:
        rows=[d for d in documents if d['id']==document_id and d['version']==version]
    else:
        state=current_state(documents)
        rows=[d for d in effective_documents(documents,barriers=state['barriers']) if origin_matches(d,state['origins'])]
        if document_id:rows=[d for d in rows if d['id']==document_id]
    return rows
