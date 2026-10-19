"""Scope-first case opening and per-verification historical evidence."""
from uuid import uuid4
from sqlalchemy import select,func
from app.business_version import SCOPE_ID
from app.models import ActionCase,ActionOccurrenceLink,ActionVerification
from app.evidence.contracts import EvidenceError
from app.evidence.repository import EvidenceRepository,now
from app.evidence.service import capture_transaction,persist_capture


def _binding(store,snapshot,frozen,*,kind,owner,case_id,instance,occurrence,record):
    return store.put_binding(dict(bindingId=uuid4().hex,scopeId=SCOPE_ID,snapshotId=snapshot['snapshotId'],
        ownerKind=kind,ownerInstanceId=owner,ownerPublicId=case_id,sourceKind='action_case',sourceInstanceId=instance,
        occurrenceId=occurrence,captureContext=dict(factVersion=snapshot['factVersion'],businessVersion=frozen.business_version),
        sourceRecord=record,recordedAt=now()))


def _open(tx,frozen,deadline,insight_type_id,*,legacy=False,source_watch_binding_id=None):
    from app.action.builder import _case_for,_steps_for
    snapshot=persist_capture(tx,frozen,deadline);store=EvidenceRepository(tx._session)
    insight=next((i for i in snapshot['payload']['factInsights'] if i['id']==insight_type_id and i['type'] in ('problem','opportunity')),None)
    if insight is None:raise ValueError('only current engine problem/opportunity can open a case')
    if source_watch_binding_id is not None:
        watch=store.get_binding(source_watch_binding_id)
        if not watch or watch['ownerKind']!='watch_event' or watch['occurrenceId']!=insight['occurrenceId'] or watch['sourceStatus']!='available':
            raise EvidenceError('source_occurrence_conflict',409)
    if not legacy:
        link=tx._session.get(ActionOccurrenceLink,(SCOPE_ID,insight['occurrenceId']))
        if link:
            current=tx._session.scalar(select(ActionCase).where(ActionCase.id==link.case_public_id).with_for_update().execution_options(populate_existing=True))
            if current is None or current.history_instance_id!=link.case_instance_id:raise EvidenceError('source_instance_deleted',409)
            return dict(case=tx.get_action_case(current.id),created=False,openingBinding=store.get_binding(link.opening_binding_id))
    deadline.prepare_session(tx._session)
    case=_case_for(insight);case['id']=insight_type_id if legacy else uuid4().hex
    if legacy:
        existing=tx._session.scalar(select(ActionCase).where(ActionCase.id==case['id']).with_for_update().execution_options(populate_existing=True))
        if existing:return dict(case=tx.get_action_case(case['id']),created=False)
    tx.create_action_case(case,_steps_for(insight),status='open')
    row=tx._session.get(ActionCase,case['id']);row.history_instance_id=uuid4().hex if legacy else case['id']
    opening=_binding(store,snapshot,frozen,kind='action_open',owner=row.history_instance_id,case_id=row.id,
        instance=row.history_instance_id,occurrence=insight['occurrenceId'],
        record=dict(insightTypeId=insight_type_id,insight=insight,sourceWatchBindingId=source_watch_binding_id,case=tx.get_action_case(row.id)))
    if not legacy:
        tx._session.add(ActionOccurrenceLink(scope_id=SCOPE_ID,occurrence_id=insight['occurrenceId'],case_instance_id=row.history_instance_id,
            case_public_id=row.id,opening_binding_id=opening['bindingId']))
    return dict(case=tx.get_action_case(row.id),created=True,openingBinding=opening)


def create_case_captured(repo,*,insight_type_id,expected_revision,source_watch_binding_id=None):
    with capture_transaction(repo) as (tx,frozen,deadline):
        if expected_revision!=frozen.business_version['revision']:raise EvidenceError('revision_conflict',409)
        return _open(tx,frozen,deadline,insight_type_id,source_watch_binding_id=source_watch_binding_id)


def attach_legacy_opening(repo,insight):
    with capture_transaction(repo) as (tx,frozen,deadline):
        if insight.get('type') not in ('problem','opportunity'):raise ValueError('only engine problem/opportunity can open a case')
        return _open(tx,frozen,deadline,insight['id'],legacy=True)


def verify_case_captured(repo,case_id,outcome,note=''):
    from app.action.flow import _verify_in_transaction
    with capture_transaction(repo) as (tx,frozen,deadline):
        snapshot=persist_capture(tx,frozen,deadline);store=EvidenceRepository(tx._session)
        deadline.prepare_session(tx._session)
        row=tx._session.scalar(select(ActionCase).where(ActionCase.id==case_id).with_for_update().execution_options(populate_existing=True))
        if row is None:
            from app.action.flow import ActionFlowError
            raise ActionFlowError(f'action case not found: {case_id}')
        if not row.history_instance_id:row.history_instance_id=uuid4().hex
        history=store.case_history(case_id)
        insight_type_id=history['opening']['sourceRecord']['insightTypeId'] if history['opening'] else case_id
        insight=next((i for i in snapshot['payload']['factInsights'] if i['id']==insight_type_id),None)
        verification_id=uuid4().hex
        binding=_binding(store,snapshot,frozen,kind='action_verification',owner=verification_id,case_id=case_id,instance=row.history_instance_id,
            occurrence=insight['occurrenceId'] if insight else None,
            record=dict(insightTypeId=insight_type_id,signalPresent=insight is not None,outcome=outcome,note=note,
                        causalSuccessVerified=False,openingCaptured=history['opening'] is not None))
        seq=(tx._session.scalar(select(func.max(ActionVerification.seq)).where(ActionVerification.scope_id==SCOPE_ID,ActionVerification.case_instance_id==row.history_instance_id)) or 0)+1
        tx._session.add(ActionVerification(verification_id=verification_id,scope_id=SCOPE_ID,case_instance_id=row.history_instance_id,
            case_public_id=case_id,seq=seq,outcome=outcome,note=note,binding_id=binding['bindingId'],recorded_at=now()))
        tx._session.flush();deadline.prepare_session(tx._session)
        result=_verify_in_transaction(tx,case_id,outcome,note)
        result.update(verificationId=verification_id,bindingId=binding['bindingId'],snapshotId=snapshot['snapshotId'])
        return result
