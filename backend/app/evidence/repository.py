"""Append-only history operations borrow the caller's transaction and never commit."""
from copy import deepcopy
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import select
from app.business_version import SCOPE_ID,canonical_hash
from app.models import (EvidenceSnapshot,InsightOccurrence,EvidenceBinding,ActionOccurrenceLink,
                        ActionVerification,EvidenceSourceEvent,ActionCase,WatchTarget)
from app.evidence.contracts import EvidenceError,validate_stored_snapshot


def now():return datetime.now(timezone.utc).isoformat()


def snapshot_view(row):
    return dict(snapshotId=row.snapshot_id,scopeId=row.scope_id,factVersion=deepcopy(row.fact_version),
                payload=deepcopy(row.payload),payloadHash=row.payload_hash,schemaVersion=row.schema_version,
                sourceLevel=row.source_level,capturedAt=row.captured_at)


class EvidenceRepository:
    def __init__(self,session,*,scope_id=SCOPE_ID):self.session=session;self.scope_id=scope_id
    def put_snapshot(self,package,*,captured_at):
        package=validate_stored_snapshot(package,scope_id=self.scope_id)
        row=self.session.get(EvidenceSnapshot,package['snapshotId'])
        if row:
            old=validate_stored_snapshot(snapshot_view(row),scope_id=self.scope_id)
            if any(old[k]!=package[k] for k in package if k!='capturedAt'):raise EvidenceError('snapshot_integrity_error',409)
            return old
        row=EvidenceSnapshot(snapshot_id=package['snapshotId'],scope_id=self.scope_id,fact_version=deepcopy(package['factVersion']),
            payload=deepcopy(package['payload']),payload_hash=package['payloadHash'],schema_version=package['schemaVersion'],
            source_level=package['sourceLevel'],captured_at=captured_at)
        self.session.add(row);self.session.flush();return snapshot_view(row)
    def get_snapshot(self,snapshot_id):
        row=self.session.scalar(select(EvidenceSnapshot).where(EvidenceSnapshot.snapshot_id==snapshot_id,EvidenceSnapshot.scope_id==self.scope_id))
        return validate_stored_snapshot(snapshot_view(row),scope_id=self.scope_id) if row else None
    def put_occurrence(self,occurrence):
        row=self.session.get(InsightOccurrence,occurrence['occurrenceId']);sha=canonical_hash([occurrence['factIdentity'],occurrence['judgment']])
        if row:
            if row.scope_id!=self.scope_id or row.content_hash!=sha:raise EvidenceError('source_occurrence_conflict',409)
        else:
            row=InsightOccurrence(occurrence_id=occurrence['occurrenceId'],scope_id=self.scope_id,insight_type_id=occurrence['insightTypeId'],
                fact_identity=deepcopy(occurrence['factIdentity']),judgment=deepcopy(occurrence['judgment']),content_hash=sha)
            self.session.add(row);self.session.flush()
        return deepcopy(occurrence)
    def put_binding(self,binding):
        if binding['scopeId']!=self.scope_id:raise EvidenceError('not_found',404)
        if binding.get('snapshotId') and not self.get_snapshot(binding['snapshotId']):raise EvidenceError('snapshot_integrity_error',409)
        if binding.get('occurrenceId'):
            occurrence=self.session.get(InsightOccurrence,binding['occurrenceId'])
            if not occurrence or occurrence.scope_id!=self.scope_id:raise EvidenceError('source_occurrence_conflict',409)
        row=self.session.get(EvidenceBinding,binding['bindingId'])
        mapping={'bindingId':'binding_id','scopeId':'scope_id','snapshotId':'snapshot_id','ownerKind':'owner_kind',
                 'ownerInstanceId':'owner_instance_id','ownerPublicId':'owner_public_id','sourceKind':'source_kind',
                 'sourceInstanceId':'source_instance_id','occurrenceId':'occurrence_id','captureContext':'capture_context',
                 'sourceRecord':'source_record','recordedAt':'recorded_at'}
        if row:
            if any(getattr(row,v)!=binding[k] for k,v in mapping.items()):raise EvidenceError('source_occurrence_conflict',409)
        else:
            row=EvidenceBinding(**{v:deepcopy(binding[k]) for k,v in mapping.items()});self.session.add(row);self.session.flush()
        return self.get_binding(row.binding_id)
    def get_binding(self,binding_id):
        row=self.session.scalar(select(EvidenceBinding).where(EvidenceBinding.binding_id==binding_id,EvidenceBinding.scope_id==self.scope_id))
        if row is None:return None
        if row.snapshot_id and self.get_snapshot(row.snapshot_id) is None:raise EvidenceError('snapshot_integrity_error',409)
        model=ActionCase if row.source_kind=='action_case' else WatchTarget
        live=self.session.scalar(select(model.id).where(model.history_instance_id==row.source_instance_id))
        deleted=self.session.scalar(select(EvidenceSourceEvent.event_id).where(EvidenceSourceEvent.scope_id==self.scope_id,
            EvidenceSourceEvent.source_kind==row.source_kind,EvidenceSourceEvent.source_instance_id==row.source_instance_id,EvidenceSourceEvent.event_type=='deleted'))
        return dict(bindingId=row.binding_id,scopeId=row.scope_id,snapshotId=row.snapshot_id,ownerKind=row.owner_kind,
            ownerInstanceId=row.owner_instance_id,ownerPublicId=row.owner_public_id,sourceKind=row.source_kind,
            sourceInstanceId=row.source_instance_id,occurrenceId=row.occurrence_id,captureContext=deepcopy(row.capture_context),
            sourceRecord=deepcopy(row.source_record),recordedAt=row.recorded_at,historical=True,
            sourceStatus='deleted' if deleted else ('available' if live else 'unavailable'))
    def record_source_deleted(self,kind,instance_id):
        if not instance_id:return
        exists=self.session.scalar(select(EvidenceSourceEvent).where(EvidenceSourceEvent.scope_id==self.scope_id,
            EvidenceSourceEvent.source_kind==kind,EvidenceSourceEvent.source_instance_id==instance_id,EvidenceSourceEvent.event_type=='deleted'))
        if not exists:
            self.session.add(EvidenceSourceEvent(event_id=uuid4().hex,scope_id=self.scope_id,source_kind=kind,
                source_instance_id=instance_id,event_type='deleted',recorded_at=now()));self.session.flush()
    def case_history(self,case_id):
        case=self.session.get(ActionCase,case_id)
        if case is None:raise EvidenceError('not_found',404)
        identity=case.history_instance_id;opening=None;verifications=[]
        if identity:
            row=self.session.scalar(select(EvidenceBinding).where(EvidenceBinding.scope_id==self.scope_id,
                EvidenceBinding.owner_kind=='action_open',EvidenceBinding.owner_instance_id==identity))
            if row:opening=self.get_binding(row.binding_id)
            for row in self.session.scalars(select(ActionVerification).where(ActionVerification.scope_id==self.scope_id,
                ActionVerification.case_instance_id==identity).order_by(ActionVerification.seq)):
                verifications.append(dict(verificationId=row.verification_id,seq=row.seq,outcome=row.outcome,note=row.note,binding=self.get_binding(row.binding_id)))
        return dict(caseId=case_id,caseInstanceId=identity,opening=opening,verifications=verifications,
                    provenanceStatus='captured' if opening else 'insufficient_provenance',missingReason=None if opening else 'opening_not_captured')
