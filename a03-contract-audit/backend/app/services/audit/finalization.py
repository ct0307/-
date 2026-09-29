"""授权范围内的人工终审；终审指纹绑定风险意见及机器任务快照。"""
from datetime import datetime, timezone
import json
from fastapi import HTTPException
from sqlalchemy import func
from app.api.deps import require_department_access
from app.models.models import AuditWorkflow, AuditBatchItem, AuditLog, Contract, Risk, Rectification
from app.services import audit_log
from app.services.audit.workflow import fingerprint, group_risks


def save_workflow(db, contract, job_id, workflow, checks):
    row = db.query(AuditWorkflow).filter_by(contract_id=contract.id, audit_generation=contract.audit_generation).first()
    if row is None:
        row = AuditWorkflow(contract_id=contract.id,audit_generation=contract.audit_generation,version=0)
        db.add(row)
    else:
        row.version += 1
    row.audit_job_id = job_id
    row.snapshot_json = json.dumps({**workflow, 'cross_checks': checks}, ensure_ascii=False)
    row.published_fingerprint = ''
    row.review_json = '{}'
    row.reviewed_by = None
    row.reviewed_at = None
    db.flush()
    return row


def _load(db, contract_id, user):
    contract = db.query(Contract).filter(Contract.id==contract_id,Contract.deleted_at.is_(None)).first()
    if contract is None: raise HTTPException(404, '合同不存在或已删除')
    require_department_access(user, contract.department)
    if user.role not in {'legal','finance','admin'}: raise HTTPException(403,'仅审查人员可查看终审证据')
    row = db.query(AuditWorkflow).filter_by(contract_id=contract_id,audit_generation=contract.audit_generation).first()
    job = db.query(AuditBatchItem).filter_by(contract_id=contract_id).order_by(AuditBatchItem.id.desc()).first()
    risks = [] if row is None else db.query(Risk).filter(Risk.contract_id==contract_id,Risk.audit_job_id==row.audit_job_id).order_by(Risk.id).all()
    return contract,row,job,risks


def _view(contract,row,job,risks,user,db):
    if row is None:
        return dict(state='not_available',can_finalize=False,groups=[],conflicts=[],directed_reviews=[],
                    message='当前代次尚无工作流快照；历史记录需重新审查后使用终审。')
    snapshot = json.loads(row.snapshot_json)
    records = [{field:getattr(r,field) for field in ('id','claim_id','agent','category','original_text','level',
                'risk_reason','suggestion','review_status','evidence_status','basis','support_validator_version',
                'support_relation_status','original_text_verified','requires_manual_review','rag_sources')}
               for r in risks]
    # 状态不变但人工意见更新也必须使旧发布失效；审计日志与风险复核同事务落库。
    review_revision = db.query(func.max(AuditLog.id)).filter(
        AuditLog.action == 'update_risk',
        AuditLog.target.in_([f'risk:{risk.id}' for risk in risks]),
    ).scalar() if risks else None
    current = fingerprint(dict(snapshot=snapshot,risks=records,generation=contract.audit_generation,
                               review_revision=review_revision,
                               elements=contract.elements_json,requires_review=contract.requires_review,
                               review_reason=contract.review_reason,parse_source=contract.parse_source,
                               ocr_confidence=contract.ocr_confidence,contract_type=contract.contract_type,
                               content_hash=contract.content_sha256,department=contract.department,
                               latest_job=job.id if job else None,job_result=job.result_json if job else None))
    stale = (contract.status not in {'done','review_required'} or
             (job is not None and (job.id != row.audit_job_id or job.status not in {'done','review_required'})))
    state = 'stale' if stale else 'published' if row.published_fingerprint == current else 'review_changed' if row.published_fingerprint else 'awaiting_review'
    directed = snapshot.get('directed_reviews', [])
    conflicts = {str(c['id']): dict(id=str(c['id']),trigger=c.get('trigger','需人工确认'),
                                   note=c.get('note','')) for c in snapshot.get('cross_checks',[]) if c.get('verdict')=='conflict'}
    for item in directed:
        if item['status'] != 'reviewed' or item['verdict'] != 'agree':
            key=item['check_id']
            conflicts.setdefault(key,dict(id=key,trigger='定向复查未得出一致结论',note=item.get('reason_code','')))
    return dict(state=state,version=row.version,generation=row.audit_generation,audit_job_id=row.audit_job_id,
                review_fingerprint=current,can_finalize=user.role in {'legal','admin'} and not stale,
                groups=group_risks(records),pending_count=sum(r.review_status=='pending' for r in risks),
                requires_quality_ack=bool(contract.requires_review),conflicts=list(conflicts.values()),
                directed_reviews=directed,identity=snapshot.get('identity',{}),budget=snapshot.get('budget',{}),
                reviewed_by=row.reviewed_by,reviewed_at=row.reviewed_at,review=json.loads(row.review_json))


def workflow_view(db,contract_id,user):
    return _view(*_load(db,contract_id,user),user,db)


def finalize_workflow(db,contract_id,user,values):
    if user.role not in {'legal','admin'}: raise HTTPException(403,'仅法务或管理员可终审发布')
    contract,row,job,risks = _load(db,contract_id,user)
    view = _view(contract,row,job,risks,user,db)
    if row is None or not view['can_finalize']: raise HTTPException(409,'当前审查尚不可终审')
    if (values.get('expected_generation') != row.audit_generation or values.get('expected_version') != row.version
            or values.get('review_fingerprint') != view['review_fingerprint']):
        raise HTTPException(409,'审查或人工意见已变化，请刷新后重新确认')
    if view['pending_count']: raise HTTPException(409,'请先逐项复核所有风险')
    if not str(values.get('comment','')).strip(): raise HTTPException(422,'必须填写终审意见')
    if view['requires_quality_ack'] and not str(values.get('quality_comment','')).strip():
        raise HTTPException(422,'必须记录解析和审查质量问题的人工核验情况')
    resolutions=values.get('conflict_resolutions',{})
    required={c['id'] for c in view['conflicts']}
    if set(resolutions) != required or any(not str(v).strip() for v in resolutions.values()):
        raise HTTPException(422,'必须逐项填写当前冲突的裁决意见')
    for risk in risks:
        if risk.review_status=='to_modify' and not db.query(Rectification).filter_by(risk_id=risk.id).first():
            raise HTTPException(409,'需修改风险必须先关联整改任务')
    # CAS 阻止重复终审覆盖；指纹使风险意见或代次的并发变化立即令终审失效。
    changed=db.query(AuditWorkflow).filter_by(id=row.id,version=values['expected_version']).update({
        'version':row.version+1,'published_fingerprint':view['review_fingerprint'],
        'review_json':json.dumps(values,ensure_ascii=False),'reviewed_by':user.id,
        'reviewed_at':datetime.now(timezone.utc)},synchronize_session=False)
    if not changed:
        db.rollback()
        raise HTTPException(409,'终审已被其他人更新，请刷新')
    audit_log.record(db,user_id=user.id,action='finalize_audit',target=f'contract:{contract_id}',
                     detail=json.dumps(dict(generation=row.audit_generation,**values),ensure_ascii=False))
    db.commit(); db.expire_all()
    return workflow_view(db,contract_id,user)
