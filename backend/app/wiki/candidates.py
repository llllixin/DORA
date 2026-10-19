"""Candidates are generated inside Action transactions; writes are local CLI only."""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from app import db
from app.models import ActionCase, KnowledgeArchive, KnowledgeCandidate
from app.wiki.contracts import approve, canonical_hash, compile_content, require, retire
from app.rag.contracts import validate_document


@contextmanager
def safe_session():
    try:
        with db.make_session() as session:yield session
    except SQLAlchemyError as exc:
        from app.repository import DataSourceUnavailableError
        raise DataSourceUnavailableError('candidate data source unavailable') from exc


def snapshot(archive, case, history_refs=None):
    result={'entry_type':archive.entry_type,'source_id':archive.source_id,'code':archive.code,
            'title':archive.title,'content':archive.content,'note':archive.note,'created_at':archive.created_at,
            'case_origin':case.origin,'case_created_at':case.created_at}
    if history_refs is not None:result['history_refs']=deepcopy(history_refs)
    return result


def captured_refs(session,case):
    """Only existing persisted bindings become new candidate provenance."""
    if not case.history_instance_id:return None,False
    from app.evidence.repository import EvidenceRepository
    store=EvidenceRepository(session);history=store.case_history(case.id)
    bindings=[b for b in [history['opening'],*[v['binding'] for v in history['verifications']]] if b]
    if not bindings:return None,False
    refs=dict(caseInstanceId=case.history_instance_id,openingBindingId=history['opening']['bindingId'] if history['opening'] else None,
              verificationBindingIds=[v['binding']['bindingId'] for v in history['verifications']],snapshotIds=sorted({b['snapshotId'] for b in bindings}))
    simulated=any(store.get_snapshot(b['snapshotId'])['payload']['hasSimulatedInputs'] for b in bindings)
    return refs,simulated


def siblings(session, entry_type, source_id):
    return session.execute(select(KnowledgeCandidate).where(KnowledgeCandidate.entry_type==entry_type,KnowledgeCandidate.source_id==source_id).order_by(KnowledgeCandidate.revision.desc())).scalars().all()


def capture(session, archive, case):
    """Caller holds source case lock; unique revision plus source hash dedup."""
    session.flush();refs,simulated=captured_refs(session,case);origin=snapshot(archive,case,refs);sha=canonical_hash(origin)
    history=siblings(session,archive.entry_type,archive.source_id)
    existing=history[0] if history and history[0].source_payload_hash==sha and not source_removed(history[0]) else None
    if existing is not None:return existing,False
    revision=max((r.revision for r in history),default=0)+1
    candidate_id='c-'+uuid4().hex
    level='simulated' if case.origin=='demo' or simulated else 'reported'
    doc_id='archive-'+archive.entry_type+'-'+canonical_hash([archive.entry_type,archive.source_id,case.created_at])[:20]
    sections={'context':'行动处理记录；'+('来源为项目演示。' if level=='simulated' else '缺少企业历史验证材料。'),
              'observed_problem':archive.title,
              'handling':archive.content or '来源没有完整处理过程，不能补造步骤。',
              'verification':('已保存历史事实引用；流程状态为resolved，未独立核验经营效果或因果。' if refs else '流程状态为resolved；没有不可变指标快照或独立经营效果核验。'),
              'result':archive.note or '未提供独立结果结论。',
              'reuse_scope':'仅作此来源的处理记录参考，跨主体/时间/业务条件需重新核验。',
              'limitations':'不以resolved或人工文案审核推断企业效果、经营因果或已验证案例。'}
    payload={'schema_version':2,'id':doc_id,'title':archive.title,'knowledge_type':'case','status':'draft',
             'content':'','metric_keys':[],'dimensions':[],'concept_ids':['procedure.action'],'aliases':[],
             'source_type':'simulated' if level=='simulated' else 'project','source_ref':'backend/app/repository.py',
             'source_url':'','version':1,'valid_from':datetime.now(timezone.utc).date().isoformat(),'valid_to':None,
             'reviewed_by':None,'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'wiki_card':{'card_type':'case','sections':sections,'concept_note':'处理记录引用行动流程概念，不伪造经营实例。'},
             'governance':{'evidence_level':level,'applicability':'该来源记录的处理过程，不代表已核验企业经营效果。',
                           'unknowns':['历史指标快照','独立经营结果验证'],'source_refs':['backend/app/repository.py'],
                           'origin':{'candidate_id':candidate_id,'revision':revision,'source_hash':sha,'snapshot':origin},'review':None}}
    payload['content']=compile_content(payload['wiki_card']);validate_document(payload)
    row=KnowledgeCandidate(candidate_id=candidate_id,entry_type=archive.entry_type,source_id=archive.source_id,
                           source_payload_hash=sha,revision=revision,payload=payload,evidence_level=level,status='draft',
                           review_events=[],created_at=payload['updated_at'])
    session.add(row);session.flush();return row,True


def source_removed(row):
    return any(event.get('eventType')=='source_deleted' for event in row.review_events)


def mark_source_removed(session,source_ids):
    """Caller owns source case locks; preserve invalidation even if IDs/text reappear."""
    rows=session.execute(select(KnowledgeCandidate).where(KnowledgeCandidate.source_id.in_(source_ids)).order_by(KnowledgeCandidate.candidate_id).with_for_update()).scalars().all()
    for row in rows:
        if not source_removed(row):
            row.review_events=[*row.review_events,{'eventType':'source_deleted','actor':'system',
                                'reason':'Original source deleted; old approval cannot be reused',
                                'timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                'revision':row.revision}]


def available(session,row,*,consume_row=None,admit_rows=None):
    if source_removed(row):return False
    if admit_rows:admit_rows(session,ActionCase,ActionCase.id==row.source_id)
    case=session.get(ActionCase,row.source_id)
    if case is not None and consume_row:
        consume_row(case.__tablename__,{c.name:deepcopy(getattr(case,c.name)) for c in case.__table__.columns})
    if admit_rows:admit_rows(session,KnowledgeArchive,KnowledgeArchive.entry_type==row.entry_type,KnowledgeArchive.source_id==row.source_id)
    archive=session.execute(select(KnowledgeArchive).where(KnowledgeArchive.entry_type==row.entry_type,KnowledgeArchive.source_id==row.source_id)).scalars().first()
    if archive is not None and consume_row:
        consume_row(archive.__tablename__,{c.name:deepcopy(getattr(archive,c.name)) for c in archive.__table__.columns})
    refs=row.payload.get('governance',{}).get('origin',{}).get('snapshot',{}).get('history_refs')
    if refs and (not case or case.history_instance_id!=refs.get('caseInstanceId')):return False
    return bool(case and case.status=='resolved' and archive and canonical_hash(snapshot(archive,case,refs))==row.source_payload_hash)


def as_dict(session,row):
    latest=siblings(session,row.entry_type,row.source_id)[0].revision
    return {'candidate_id':row.candidate_id,'entry_type':row.entry_type,'source_id':row.source_id,
            'source_payload_hash':row.source_payload_hash,'revision':row.revision,'payload':deepcopy(row.payload),
            'evidence_level':row.evidence_level,'status':row.status,'review_events':deepcopy(row.review_events),
            'created_at':row.created_at,'source_available':available(session,row),'superseded':row.revision<latest}


def locked(session,candidate_id,*,withdrawal=False):
    hint=session.get(KnowledgeCandidate,candidate_id);require(hint is not None,'candidate not found')
    session.execute(select(ActionCase).where(ActionCase.id==hint.source_id).with_for_update()).scalar_one_or_none()
    session.execute(select(KnowledgeArchive).where(KnowledgeArchive.entry_type==hint.entry_type,KnowledgeArchive.source_id==hint.source_id).with_for_update()).scalars().first()
    row=session.execute(select(KnowledgeCandidate).where(KnowledgeCandidate.candidate_id==candidate_id).with_for_update().execution_options(populate_existing=True)).scalar_one()
    if not withdrawal:
        require(available(session,row),'candidate source missing or changed')
        require(row.revision==siblings(session,row.entry_type,row.source_id)[0].revision,'candidate revision superseded')
    return row


class CandidateService:
    def list(self):
        with safe_session() as s:
            return [as_dict(s,row) for row in s.execute(select(KnowledgeCandidate).order_by(KnowledgeCandidate.created_at,KnowledgeCandidate.revision)).scalars()]

    def get(self,candidate_id):
        with safe_session() as s:
            row=s.get(KnowledgeCandidate,candidate_id)
            return as_dict(s,row) if row else None

    def collect(self):
        created=0
        with safe_session() as s:
            # Same source→candidate lock order as normal Action writes.
            for case in s.execute(select(ActionCase).where(ActionCase.status=='resolved').order_by(ActionCase.id).with_for_update()).scalars():
                archives=s.execute(select(KnowledgeArchive).where(KnowledgeArchive.source_id==case.id)).scalars().all()
                for archive in archives:created+=int(capture(s,archive,case)[1])
            s.commit()
        return {'created':created}

    def revise(self,candidate_id,payload):
        with safe_session() as s:
            old=locked(s,candidate_id);doc=deepcopy(payload)
            require(doc.get('id')==old.payload['id'],'candidate topic identity cannot change')
            require(doc['governance']['evidence_level']==old.evidence_level and doc['source_type']==old.payload['source_type'],'cannot upgrade candidate provenance')
            require(doc['governance'].get('origin')==old.payload['governance']['origin'],'candidate source snapshot cannot change')
            doc['status']='draft';doc['reviewed_by']=None;doc['governance']['review']=None;doc['governance'].pop('source_hashes',None)
            revision=old.revision+1;new_id='c-'+uuid4().hex
            doc['governance']['origin']['candidate_id']=new_id;doc['governance']['origin']['revision']=revision
            doc['content']=compile_content(doc['wiki_card']);validate_document(doc)
            row=KnowledgeCandidate(candidate_id=new_id,entry_type=old.entry_type,source_id=old.source_id,source_payload_hash=old.source_payload_hash,
                                   revision=revision,payload=doc,evidence_level=old.evidence_level,status='draft',review_events=[],created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            s.add(row);s.flush();result=as_dict(s,row);s.commit();return result

    def review(self,candidate_id,*,actor,reason,decision,base_version):
        require(decision in {'approve','reject','retire'},'unknown review decision')
        require(isinstance(actor,str) and bool(actor.strip()) and isinstance(reason,str) and bool(reason.strip()),'explicit actor and reason required')
        with safe_session() as s:
            row=locked(s,candidate_id,withdrawal=decision=='retire')
            if decision=='reject':
                require(row.status=='draft','only draft can be rejected')
                doc=deepcopy(row.payload)
            elif decision=='retire':
                require(row.status=='reviewed','only reviewed candidate can retire')
                doc=retire(row.payload,actor=actor,reason=reason,base_version=base_version)
            else:
                require(row.status=='draft','candidate is not draft')
                doc=approve(row.payload,actor=actor,reason=reason,base_version=base_version)
            row.payload=doc;row.status=doc['status']
            from app.wiki.contracts import payload_hash
            row.review_events=[*row.review_events,{'actor':actor,'reason':reason,'decision':decision,'timestamp':datetime.now(timezone.utc).isoformat(timespec='seconds'),'revision':row.revision,'payloadHash':payload_hash(doc),'baseVersion':base_version}]
            s.flush();result=as_dict(s,row);s.commit();return result

    def export(self,candidate_id):
        with safe_session() as s:
            hint=s.get(KnowledgeCandidate,candidate_id)
            row=locked(s,candidate_id,withdrawal=bool(hint and hint.status=='retired'))
            require(row.status in {'reviewed','retired'},'only approved or retirement records may export')
            return validate_document(deepcopy(row.payload))

    def publish(self,candidate_id,path=None,*,render_dir=None):
        from app.wiki.publication import publish_batch
        with safe_session() as s:
            hint=s.get(KnowledgeCandidate,candidate_id)
            row=locked(s,candidate_id,withdrawal=bool(hint and hint.status=='retired'))
            require(row.status in {'reviewed','retired'},'only approved or retirement records may publish')
            return publish_batch([row.payload],path,render_dir=render_dir,
                                 candidate_guard=lambda doc: doc==row.payload and available(s,row))
