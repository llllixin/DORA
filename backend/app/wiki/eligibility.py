"""Live source eligibility, shared by Wiki reading and indexed retrieval."""
from copy import deepcopy
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app import db
from app.models import ActionCase, KnowledgeArchive, KnowledgeCandidate, RagIndexBatch, RagIndexState
from app.rag.contracts import RagContractError
from app.rag.lifecycle import merge_removal_barriers
from app.wiki.candidates import available


def origin_states(session, candidate_ids, *, consume_row=None, admit_rows=None):
    states = {}
    for candidate_id in candidate_ids:
        if not isinstance(candidate_id, str) or not candidate_id:
            continue
        if admit_rows:
            admit_rows(session, KnowledgeCandidate, KnowledgeCandidate.candidate_id == candidate_id)
        row = session.get(KnowledgeCandidate, candidate_id)
        latest = None
        if row is not None:
            if consume_row:
                consume_row(row.__tablename__, {c.name: deepcopy(getattr(row, c.name)) for c in row.__table__.columns})
            latest = session.scalar(select(func.max(KnowledgeCandidate.revision)).where(
                KnowledgeCandidate.entry_type == row.entry_type, KnowledgeCandidate.source_id == row.source_id))
        states[candidate_id] = {
            'available': bool(row and row.status == 'reviewed' and row.revision == latest and
                              available(session, row, consume_row=consume_row,admit_rows=admit_rows)),
            'revision': row.revision if row else None,
            'source_hash': row.source_payload_hash if row else None,
        }
    return states


def origin_matches(document, states):
    origin = (document.get('governance') or {}).get('origin')
    if origin is None:
        return True
    if not isinstance(origin, dict) or not isinstance(origin.get('candidate_id'), str):
        return False
    state = states.get(origin['candidate_id'], {})
    return bool(state.get('available') and type(origin.get('revision')) is int and
                state.get('revision') == origin['revision'] and state.get('source_hash') == origin.get('source_hash'))


def current_state(documents):
    """Read origins and existing barriers without requiring vector-index migrations."""
    engine = db.get_engine()
    options = {'isolation_level': 'REPEATABLE READ'} if engine.dialect.name == 'postgresql' else {}
    try:
        with engine.connect().execution_options(**options) as connection, Session(connection) as session:
            manifest = {'versions': {}, 'barriers': {}}
            schema = inspect(connection)
            if schema.has_table(RagIndexState.__tablename__):
                head = session.get(RagIndexState, 'repository-json')
                if head and head.head_batch_id:
                    if not schema.has_table(RagIndexBatch.__tablename__):
                        raise RagContractError('wiki lifecycle unavailable')
                    batch = session.get(RagIndexBatch, head.head_batch_id)
                    if batch is None:
                        raise RagContractError('wiki lifecycle unavailable')
                    manifest = batch.manifest_json
            if not isinstance(manifest, dict) or not isinstance(manifest.get('versions'), dict) or not isinstance(manifest.get('barriers'), dict):
                raise RagContractError('wiki lifecycle unavailable')
            barriers = merge_removal_barriers(manifest, documents, mode='full')
            if any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in barriers.items()):
                raise RagContractError('wiki lifecycle unavailable')
            candidate_ids = []
            for document in documents:
                origin = (document.get('governance') or {}).get('origin')
                if isinstance(origin, dict) and isinstance(origin.get('candidate_id'), str):
                    candidate_ids.append(origin['candidate_id'])
            return {'barriers': barriers, 'origins': origin_states(session, set(candidate_ids))}
    except SQLAlchemyError as exc:
        raise RagContractError('wiki source eligibility unavailable') from exc
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise RagContractError('wiki lifecycle unavailable') from exc
