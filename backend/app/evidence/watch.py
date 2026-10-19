"""Evaluate and bind one Watch using one scope-locked frozen input set."""
from copy import deepcopy
from uuid import uuid4
from sqlalchemy import select
from app.business_version import SCOPE_ID,canonical_hash
from app.models import WatchTarget,WatchEvent,EvidenceBinding
from app.evidence.repository import EvidenceRepository,now
from app.evidence.service import capture_transaction,persist_capture


class _Skipped(Exception):pass


def evaluate_captured(repo,target_id):
    from app.watch.evaluator import _evaluate_frozen
    miss=dict(hit=False,kind='miss',event=None,skipped=True)
    try:
        with capture_transaction(repo) as (tx,frozen,deadline):
            hint=tx.get_watch_target(target_id)
            if not hint or hint['status']!='watching':return miss
            snapshot=persist_capture(tx,frozen,deadline)
            deadline.prepare_session(tx._session)
            target=tx._session.scalar(select(WatchTarget).where(WatchTarget.id==target_id).with_for_update().execution_options(populate_existing=True))
            if not target or target.status!='watching' or target.intent!=hint['intent']:raise _Skipped()
            if not target.history_instance_id:target.history_instance_id=uuid4().hex
            store=EvidenceRepository(tx._session)
            context=dict(factVersion=snapshot['factVersion'],businessVersion=frozen.business_version,intentHash=canonical_hash(target.intent))

            class Adapter:
                get_series=frozen.get_series
                def list_watch_events(self,tid):
                    events=tx.list_watch_events(tid)
                    if not events:return []
                    last=events[-1]
                    event=tx._session.get(WatchEvent,last['id'])
                    binding=tx._session.scalar(select(EvidenceBinding).where(EvidenceBinding.owner_kind=='watch_event',EvidenceBinding.owner_instance_id==event.history_event_id,EvidenceBinding.scope_id==SCOPE_ID)) if event.history_event_id else None
                    previous=binding.capture_context if binding else {}
                    return [last] if all(previous.get(k)==context[k] for k in ('factVersion','intentHash')) else []
                def mark_watch_escalated(self,tid):return tx.mark_watch_escalated(tid)
                def add_watch_event(self,*args,**kwargs):
                    event=tx.add_watch_event(*args,**kwargs);row=tx._session.get(WatchEvent,event['id']);row.history_event_id=uuid4().hex
                    insight=next((i for i in snapshot['payload']['factInsights'] if i['id']==event['values'].get('engine_insight')),None)
                    binding=store.put_binding(dict(bindingId=uuid4().hex,scopeId=SCOPE_ID,snapshotId=snapshot['snapshotId'],
                        ownerKind='watch_event',ownerInstanceId=row.history_event_id,ownerPublicId=str(row.id),sourceKind='watch_target',
                        sourceInstanceId=target.history_instance_id,occurrenceId=insight['occurrenceId'] if insight else None,
                        captureContext=context,sourceRecord={**deepcopy(event),'target':deepcopy(hint)},recordedAt=now()))
                    event.update(bindingId=binding['bindingId'],historyEventId=row.history_event_id,snapshotId=snapshot['snapshotId'],occurrenceId=binding['occurrenceId'])
                    return event

            out=_evaluate_frozen(Adapter(),hint,snapshot['payload']['factInsights'])
            tx.touch_watch_target(target_id,now());deadline.check()
            return out
    except _Skipped:return miss
