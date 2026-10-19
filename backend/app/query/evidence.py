"""Evidence lookup uses only retained, delivered packets; no current source IO."""
from copy import deepcopy
from app.query.contracts import CONTRACT_VERSION,QueryConflict,QueryEvidenceNotFound,validate_evidence

def read_run_evidence(run_repository,run_id,evidence_id):
    run=run_repository.get_agent_run(run_id)
    if not run:raise QueryEvidenceNotFound('run_not_found',run_id=run_id)
    packets=[run.get('output') or {}]
    packets.extend(e.get('result',{}) for e in run.get('events',[]) if e.get('type')=='tool_result')
    matches=[]
    for packet in packets:
        if not isinstance(packet,dict) or packet.get('contractVersion')!=CONTRACT_VERSION:continue
        for e in packet.get('evidence',[]):
            if e.get('evidenceId')==evidence_id:
                try:validate_evidence(e)
                except Exception as exc:raise QueryConflict('evidence_integrity_conflict',run_id=run_id) from exc
                matches.append(e)
    if not matches:raise QueryEvidenceNotFound('evidence_not_found',run_id=run_id)
    # Each packet's full supporting identity/hash was validated above. Scores and
    # readAt may differ for the same stable evidence across two parent tools.
    return deepcopy(matches[0])
