"""Bounded, file-locked historical source views; no engine or model calls."""
from contextlib import nullcontext
from app.db_budget import budget_connection,budget_scope
from copy import deepcopy
import json
from pathlib import Path
from sqlalchemy import select, func, cast, Text, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from app.business_version import SCOPE_ID, canonical_hash
from app import models as m
from app.evidence.contracts import validate_stored_snapshot, EvidenceError
from app.evidence.repository import snapshot_view
from app.evidence.migrations import require_evidence_ready
from app.rag.contracts import KNOWLEDGE_ROOT, RagIndexUnavailable
from app.rag.source import KnowledgeSource
from app.rag.identity import source_version_hash, document_key
from app.rag.lifecycle import select_versions, merge_removal_barriers
from app.rag.ontology_contracts import validate_ontology, content_hash
from app.wiki.candidates import available
from app.graph.contracts import GraphError, GraphLimits
from app.graph.registry import SCHEMA_HASH
from app.runtime.contracts import RuntimeFailure


def byte_size(value):
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())


def row_data(row):
    return {c.name: deepcopy(getattr(row, c.name)) for c in row.__table__.columns}


def validate_binding(binding,snapshot,session):
    record=binding['source_record'];kind=binding['owner_kind']
    if snapshot is None:return
    if binding['capture_context'].get('factVersion')!=snapshot['factVersion']:raise GraphError('source_integrity_error')
    expected_kind={'action_open':'action_case','action_verification':'action_case','watch_event':'watch_target'}
    if expected_kind.get(kind)!=binding['source_kind']:raise GraphError('source_integrity_error')
    insights={i['id']:i for i in snapshot['payload']['factInsights']}
    if kind=='action_open':
        actual=insights.get(record.get('insightTypeId'))
        if (not actual or record.get('insight')!=actual or binding['occurrence_id']!=actual['occurrenceId']
                or record.get('case',{}).get('id')!=binding['owner_public_id']
                or binding['owner_instance_id']!=binding['source_instance_id']):raise GraphError('source_integrity_error')
    elif kind=='action_verification':
        actual=insights.get(record.get('insightTypeId'))
        row=session.get(m.ActionVerification,binding['owner_instance_id'])
        if (record.get('signalPresent') is not (actual is not None)
                or binding['occurrence_id']!=(actual['occurrenceId'] if actual else None)
                or row is None or row.scope_id!=SCOPE_ID or row.binding_id!=binding['binding_id']
                or row.case_instance_id!=binding['source_instance_id'] or row.case_public_id!=binding['owner_public_id']
                or row.outcome!=record.get('outcome') or row.note!=record.get('note')):raise GraphError('source_integrity_error')
    elif kind=='watch_event':
        actual=insights.get((record.get('values') or {}).get('engine_insight'))
        intent=(record.get('target') or {}).get('intent')
        if (str(record.get('id'))!=binding['owner_public_id']
                or binding['occurrence_id']!=(actual['occurrenceId'] if actual else None)
                or (intent and binding['capture_context'].get('intentHash')!=canonical_hash(intent))):
            raise GraphError('source_integrity_error')


def source_inventory(session,budget):
    result={}
    for model in (m.EvidenceSnapshot,m.EvidenceBinding,m.InsightOccurrence,m.EvidenceSourceEvent,
                  m.ActionVerification,m.ActionCase,m.WatchTarget,m.KnowledgeCandidate,m.RagDocument):
        budget.prepare(session)
        predicate=model.scope_id==SCOPE_ID if hasattr(model,'scope_id') else True
        result[model.__tablename__]=session.scalar(select(func.count()).select_from(model).where(predicate))
    return result


class SourceReader:
    def __init__(self, engine, source=None, *, limits=None):
        self.engine, self.source = engine, source or KnowledgeSource()
        self.limits = limits or GraphLimits()

    def _rows(self, session, model, budget, *, scope=False, maximum=None):
        budget.prepare(session)
        predicate = model.scope_id == SCOPE_ID if scope else True
        cap = self.limits.maxSourceRows if maximum is None else maximum
        count = session.scalar(select(func.count()).select_from(model).where(predicate))
        if count > cap: raise GraphError('build_input_limit', 422)
        # Admit JSON size in SQL before fetching payloads into Python/driver buffers.
        for column in model.__table__.columns:
            if isinstance(column.type, m.JSON):
                size = session.scalar(select(func.sum(func.length(cast(column, Text)))).where(predicate)) or 0
                if size > self.limits.maxSourceBytes: raise GraphError('build_input_limit', 422)
        rows = session.scalars(select(model).where(predicate).order_by(*model.__table__.primary_key.columns).limit(cap+1)).all()
        budget.source_rows += len(rows)
        if budget.source_rows > self.limits.maxSourceRows: raise GraphError('build_input_limit', 422)
        return rows

    def capture(self, budget, *, connection=None, locked_file=None):
        budget.check()
        try:
            with budget_scope(budget): require_evidence_ready(self.engine,connection=connection)
            budget.check()
            file_context = nullcontext(locked_file) if locked_file is not None else self.source.locked_snapshot(
                budget=budget, max_bytes=self.limits.maxSourceBytes)
            with file_context as source:
                if connection is not None:
                    with Session(connection) as session: return self._capture(session, source, budget)
                options = {'isolation_level':'REPEATABLE READ'} if self.engine.dialect.name == 'postgresql' else {}
                with budget_connection(self.engine,budget) as conn:
                    conn=conn.execution_options(**options)
                    with conn.begin():
                        if conn.dialect.name == 'sqlite': conn.exec_driver_sql('BEGIN')
                        with Session(conn) as session: return self._capture(session, source, budget)
        except GraphError: raise
        except RuntimeFailure as exc: raise GraphError('build_input_limit',422) from exc
        except (EvidenceError, ValueError, KeyError, TypeError) as exc:
            raise GraphError('source_integrity_error', 503) from exc
        except (SQLAlchemyError, RagIndexUnavailable, OSError) as exc:
            raise GraphError('source_unavailable', 503) from exc

    def _capture(self, session, source, budget):
        budget.source_rows = 0
        records, missing = {}, []
        def record(kind, native_id, data, *, version, level, status='available'):
            key = kind + ':' + native_id
            records[key] = dict(kind=kind, sourceId=native_id, version=version, data=deepcopy(data),
                                hash=canonical_hash(data), level=level, status=status)

        stored = self._rows(session, m.EvidenceSnapshot, budget, scope=True, maximum=self.limits.maxSnapshots)
        snapshots = [validate_stored_snapshot(snapshot_view(r), scope_id=SCOPE_ID) for r in stored]
        snap_by_id = {s['snapshotId']:s for s in snapshots}
        occurrences = self._rows(session, m.InsightOccurrence, budget, scope=True)
        occurrences = {r.occurrence_id:r for r in occurrences}
        for snap in snapshots:
            for insight in snap['payload']['factInsights']:
                old = occurrences.get(insight['occurrenceId'])
                if (old is None or old.judgment != insight or old.fact_identity != snap['factVersion'] or
                    old.content_hash != canonical_hash([old.fact_identity, old.judgment])):
                    raise GraphError('source_integrity_error')
            record('snapshot', snap['snapshotId'], snap, version=snap['payloadHash'], level=snap['sourceLevel'])
        # A rule version is shared by snapshots; its origin grade is conservative.
        rules={}
        for snap in snapshots:
            fact=snap['factVersion']; rid=canonical_hash([fact['ontologyVersion'],fact['ruleVersion']])
            data=dict(ontologyVersion=fact['ontologyVersion'],ruleVersion=fact['ruleVersion'],effectiveRules=snap['payload']['effectiveRules'])
            previous=rules.get(rid)
            if previous and previous['data']!=data:raise GraphError('source_integrity_error')
            levels=([previous['level']] if previous else [])+[snap['sourceLevel']]
            level='simulated' if 'simulated' in levels else ('legacy_unknown' if 'legacy_unknown' in levels else 'reported')
            rules[rid]=dict(data=data,level=level)
        for rid,rule in rules.items():
            record('rule',rid,rule['data'],version=rule['data']['ruleVersion'],level=rule['level'])

        cases = self._rows(session, m.ActionCase, budget)
        targets = self._rows(session, m.WatchTarget, budget)
        live = {('action_case', r.history_instance_id) for r in cases if r.history_instance_id}
        live |= {('watch_target', r.history_instance_id) for r in targets if r.history_instance_id}
        events = self._rows(session, m.EvidenceSourceEvent, budget, scope=True)
        deleted = {(r.source_kind,r.source_instance_id) for r in events if r.event_type == 'deleted'}
        bindings = [row_data(r) for r in self._rows(session, m.EvidenceBinding, budget, scope=True)]
        for binding in bindings:
            sid = binding['snapshot_id']
            if sid is not None and sid not in snap_by_id: raise GraphError('source_integrity_error')
            snap = snap_by_id.get(sid)
            validate_binding(binding,snap,session)
            if binding['occurrence_id'] and (snap is None or not any(
                    i['occurrenceId'] == binding['occurrence_id'] for i in snap['payload']['factInsights'])):
                raise GraphError('source_integrity_error')
            pair = binding['source_kind'], binding['source_instance_id']
            status = 'deleted' if pair in deleted else ('available' if pair in live else 'unavailable')
            record('binding', binding['binding_id'], binding, version=binding['binding_id'],
                   level=snap['sourceLevel'] if snap else 'legacy_unknown', status=status)

        candidates = self._rows(session, m.KnowledgeCandidate, budget)
        origins = {r.candidate_id:dict(available=available(session,r), revision=r.revision, hash=r.source_payload_hash)
                   for r in candidates}
        state = session.get(m.RagIndexState, 'repository-json')
        head = session.get(m.RagIndexBatch, state.head_batch_id) if state and state.head_batch_id else None
        manifest = head.manifest_json if head else {}
        docs = source.documents
        barriers = merge_removal_barriers(manifest, docs, mode='full')
        selection = select_versions(docs, on_date=source.business_date, barriers=barriers)
        eligible = {document_key(d):d for d in selection['eligible']}
        formal = {document_key(d):d for d in docs}
        persisted = self._rows(session, m.RagDocument, budget)
        documents = []
        for row in persisted:
            if row.source_snapshot is None or row.source_version_hash is None: continue
            doc = row.source_snapshot
            if row.pk != document_key(doc) or row.source_version_hash != source_version_hash(doc):
                raise GraphError('source_integrity_error')
            current = eligible.get(row.pk)
            status = 'available' if current and source_version_hash(current) == row.source_version_hash else 'changed'
            if row.pk not in formal: status = 'removed'
            if doc['id'] in selection['reasons']: status = selection['reasons'][doc['id']]
            origin = (doc.get('governance') or {}).get('origin') or {}
            if origin:
                live_origin = origins.get(origin.get('candidate_id'), {})
                if not (live_origin.get('available') and live_origin.get('revision') == origin.get('revision')
                        and live_origin.get('hash') == origin.get('source_hash')): status = 'origin_unavailable'
            level = (doc.get('governance') or {}).get('evidence_level') or 'legacy_unknown'
            if doc.get('source_type') == 'simulated': level = 'simulated'
            record('document', row.pk, doc, version=row.source_version_hash, level=level, status=status)
            documents.append(doc)
        for key in eligible:
            if 'document:'+key not in records:
                missing.append(dict(sourceId=key, reason='document_pending'))

        ontology = {}
        wanted = {s['factVersion']['ontologyVersion'] for s in snapshots}
        current = json.loads((KNOWLEDGE_ROOT/'ontology/ontology.json').read_text())
        wanted.add(current['ontologyVersion'])
        directory = KNOWLEDGE_ROOT/'ontology/releases'
        publications = json.loads((directory/'manifest.json').read_text())
        for version in sorted(wanted):
            release_id, separator, release_hash = version.partition(':')
            publication = publications[release_id]
            if separator and release_hash != publication['contentHash']:
                raise GraphError('source_integrity_error')
            path = (directory/publication['file']).resolve()
            if not path.is_relative_to(directory.resolve()) or publication['status'] != 'reviewed':
                raise GraphError('source_integrity_error')
            raw = json.loads(path.read_text()); validate_ontology(raw)
            if raw['ontologyVersion'] != release_id or content_hash(raw) != publication['contentHash']:
                raise GraphError('source_integrity_error')
            ontology[version] = raw
            record('ontology', version, raw, version=publication['contentHash'], level='project')
        if current != ontology[current['ontologyVersion']]: raise GraphError('source_integrity_error')
        for case in cases:
            if not case.history_instance_id:
                missing.append(dict(sourceId=case.id, reason='opening_not_captured'))
        vector = dict(scopeId=SCOPE_ID, knowledgeNamespace='repository-json', sourceRevision=source.revision,
                      effectiveDate=source.business_date.isoformat(), barriers=barriers, graphSchemaHash=SCHEMA_HASH,
                      adapterVersion='a09-source-v1',
                      inventory=source_inventory(session,budget),
                      rules={rid:{k:v for k,v in value['data'].items() if k!='effectiveRules'} for rid,value in sorted(rules.items())},
                      records=[dict(key=k, hash=v['hash'], status=v['status']) for k,v in sorted(records.items())],
                      deletions=[row_data(r) for r in events])
        view = dict(records=records, snapshots=snapshots, bindings=bindings, documents=documents,
                    ontology=ontology, vector=vector, missing=missing)
        if byte_size(view) > self.limits.maxSourceBytes: raise GraphError('build_input_limit', 422)
        budget.check()
        return view

    def for_batch(self,session,source,vector,budget):
        from app.graph.read_source import batch_sources
        return batch_sources(self,session,source,vector,budget)

    def lock_sources(self, session, budget):
        budget.prepare(session)
        state = session.scalar(select(m.BusinessRevision).where(m.BusinessRevision.scope_id == SCOPE_ID).with_for_update())
        if state is None: raise GraphError('source_unavailable')
        # Preserve existing scope→case→archive→candidate→file ordering.
        for model in (m.ActionCase, m.KnowledgeArchive, m.KnowledgeCandidate):
            count = session.scalar(select(func.count()).select_from(model))
            if count > self.limits.maxSourceRows: raise GraphError('build_input_limit', 422)
            budget.prepare(session)
            session.scalars(select(model).order_by(*model.__table__.primary_key.columns)
                            .with_for_update().limit(self.limits.maxSourceRows+1)).all()
