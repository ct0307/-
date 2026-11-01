"""整改计划、职责分离、实际材料与不可覆盖的操作快照。"""
import json
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm.exc import StaleDataError

from app.api.deps import allowed_departments, require_department_access
from app.models.models import Contract, Risk, Rectification, RectificationEvent, User
from app.schemas.contract import RectificationOut, RectificationEventOut
from app.services import audit_log
from app.services.authorized_risks import load_authorized_risk

PROFESSIONAL = {"legal", "finance", "admin"}
TRANSITIONS = {
    "待处理": {"处理中"}, "处理中": {"待复核", "待风险接受"},
    "待复核": {"处理中", "已闭环"}, "待风险接受": {"处理中", "已接受风险"},
    "已闭环": {"待处理"}, "已接受风险": {"待处理"},
}
PLAN_FIELDS = ("owner", "due", "note", "acceptance_criteria", "contract_stage", "handling_method")


def professional(user):
    if user.role not in PROFESSIONAL:
        raise HTTPException(403, "仅法务、财务或管理员可管理整改计划")


def load(db, rc_id, user):
    raw = rc_id[2:] if str(rc_id).upper().startswith("RC") else rc_id
    try:
        pk = int(raw)
    except (ValueError, TypeError):
        raise HTTPException(400, "整改ID格式错误")
    row = db.get(Rectification, pk)
    if row is None:
        raise HTTPException(404, "整改项不存在")
    if row.risk_id is None:
        if user.role != "admin":
            raise HTTPException(403, "历史整改缺少合同归属，请管理员核验")
        return row, None, None
    risk, contract = load_authorized_risk(db, row.risk_id, user)
    return row, risk, contract


def check_version(row, supplied):
    if supplied is None:
        raise HTTPException(422, "请提供当前版本version")
    if supplied != row.version:
        raise HTTPException(409, "整改已被其他操作更新，请刷新后重试")


def eligible(person, contract):
    return person.role == "admin" or contract.department in allowed_departments(person)


def validate_plan(db, values, contract, created):
    if contract is None:
        raise HTTPException(422, "历史整改缺少来源合同，不能伪造整改计划")
    for key in PLAN_FIELDS:
        if not isinstance(values.get(key), str) or not values[key].strip():
            raise HTTPException(422, f"整改计划缺少必填项：{key}")
        values[key] = values[key].strip()
    try:
        due_date, created_date = date.fromisoformat(values["due"]), date.fromisoformat(created)
        if due_date.isoformat() != values["due"] or created_date.isoformat() != created or due_date < created_date:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "日期格式应为YYYY-MM-DD，截止日不得早于创建日")
    stage, method = values["contract_stage"], values["handling_method"]
    if stage not in {"unsigned", "signed", "unknown"} or method not in {"revision", "supplement", "performance"}:
        raise HTTPException(422, "合同阶段或整改方式无效")
    if (stage == "unsigned" and method != "revision") or (stage == "signed" and method == "revision"):
        raise HTTPException(422, "未签合同采用草稿修订，已签合同应采用补充协议或履约措施")
    collaborators = values.get("collaborators", [])
    if not isinstance(collaborators, list) or any(not isinstance(name, str) or not name.strip() for name in collaborators):
        raise HTTPException(422, "协作人必须为已注册用户名列表")
    names = [values["owner"], *collaborators]
    for name in names:
        person = db.query(User).filter(User.username == name).first()
        if person is None or not eligible(person, contract):
            raise HTTPException(422, "责任人及协作人必须已注册且有来源合同部门访问权")
    return values


def plan_values(row):
    return {**{key: getattr(row, key) for key in PLAN_FIELDS}, "collaborators": json.loads(row.collaborators_json or "[]")}


def snapshot(row):
    result = {}
    for column in Rectification.__table__.columns:
        value = getattr(row, column.name)
        result[column.name] = value.isoformat() if isinstance(value, datetime) else value
    result["collaborators"] = json.loads(row.collaborators_json or "[]")
    result["evidence"] = json.loads(row.evidence_json or "[]")
    return result


def persist(db, row, user, action, old, previous_plan=None):
    """版本更新与事件在同一事务内；并发更新失败必须一起回滚。"""
    try:
        db.flush()
        saved = snapshot(row)
        if row.risk_id is not None:
            risk = db.get(Risk, row.risk_id)
            source = db.get(Contract, risk.contract_id) if risk else None
            saved.update(contract_id=source.id if source else None,
                department=source.department if source else "",
                before_text=risk.original_text if risk else "",
                original_text_verified=risk.original_text_verified if risk else None)
        if previous_plan is not None:
            saved["previous_plan"] = previous_plan
        db.add(RectificationEvent(rectification_id=row.id, action=action, actor_id=user.id,
            actor=user.username, occurred_at=datetime.now(timezone.utc), from_status=old,
            to_status=row.status, snapshot_json=json.dumps(saved, ensure_ascii=False)))
        audit_log.record(db, user_id=user.id, action=f"rectification_{action}", target=f"rectification:{row.id}", detail=f"{old or ''} -> {row.status}")
        db.commit()
    except StaleDataError:
        db.rollback()
        raise HTTPException(409, "整改已被其他操作更新，请刷新后重试")
    except Exception:
        db.rollback()
        raise
    db.refresh(row)
    return output(db, row, user)


def output(db, row, user):
    result = RectificationOut.from_orm_row(row)
    if row.risk_id is not None:
        risk, contract = load_authorized_risk(db, row.risk_id, user)
        result.contract_id, result.before_text = contract.id, risk.original_text or ""
        result.department = contract.department
        result.original_text_verified = risk.original_text_verified
    owner = row.owner == user.username
    independent = not owner and row.submitted_by != user.id
    result.can_manage = user.role in PROFESSIONAL and row.status in {"待处理", "处理中"} and result.contract_id is not None
    result.can_execute = owner and row.status in {"待处理", "处理中"} and result.contract_id is not None
    result.can_review = user.role in PROFESSIONAL and independent and row.status == "待复核"
    result.can_accept = user.role == "admin" and independent and row.status == "待风险接受"
    result.can_escalate = (owner or user.role in PROFESSIONAL) and row.status not in {"已闭环", "已接受风险"} and (row.level == "high" or row.due < date.today().isoformat())
    result.can_reopen = user.role in PROFESSIONAL and row.status in {"已闭环", "已接受风险"} and result.contract_id is not None
    result.events = [RectificationEventOut(id=e.id, action=e.action, actor_id=e.actor_id, actor=e.actor,
        occurred_at=e.occurred_at, from_status=e.from_status, to_status=e.to_status,
        snapshot=json.loads(e.snapshot_json)) for e in db.query(RectificationEvent).filter(RectificationEvent.rectification_id == row.id).order_by(RectificationEvent.id).all()]
    return result


def create(db, payload, user):
    professional(user)
    if payload.risk_id is None:
        raise HTTPException(422, "整改必须关联已授权的风险项")
    risk, contract = load_authorized_risk(db, payload.risk_id, user)
    if payload.status != "待处理":
        raise HTTPException(400, "新整改项必须从待处理开始")
    if risk.review_status not in {"confirmed", "to_modify"}:
        raise HTTPException(409, "请先复核风险再创建整改任务")
    created = payload.created or date.today().isoformat()
    values = validate_plan(db, {key: getattr(payload, key) for key in (*PLAN_FIELDS, "collaborators")}, contract, created)
    row = Rectification(contract=contract.filename, risk=risk.category, level=risk.level,
        risk_id=risk.id, created=created, status="待处理", **{key: values[key] for key in PLAN_FIELDS},
        collaborators_json=json.dumps(values["collaborators"], ensure_ascii=False))
    db.add(row)
    return persist(db, row, user, "create", None)


def evidence(db, ids, source_id, user, description):
    if not ids:
        raise HTTPException(400, "至少关联一份实际修订材料或凭证")
    result = []
    source = db.get(Contract, source_id)
    for pk in dict.fromkeys(ids):
        material = db.get(Contract, pk)
        if material is None or material.deleted_at is not None or pk == source_id:
            raise HTTPException(400, "材料不存在、已删除或是原合同")
        require_department_access(user, material.department)
        if material.department != source.department:
            raise HTTPException(403, "整改材料必须属于来源合同部门")
        digest = material.content_sha256 or ""
        if len(digest) != 64 or any(character not in "0123456789abcdefABCDEF" for character in digest):
            raise HTTPException(400, "材料缺少有效内容哈希，请重新上传实际材料后提交")
        result.append(dict(contract_id=material.id,filename=material.filename,
            content_sha256=material.content_sha256,description=description))
    return result


def verify_submission_evidence(db, row, contract, user):
    """验收重新核对实际记录与提交时哈希，历史缺失哈希绝不补造。"""
    saved = json.loads(row.evidence_json or "[]")
    if not saved or any(not item.get("contract_id") or not item.get("content_sha256") for item in saved):
        raise HTTPException(400, "材料缺少提交时内容哈希，请退回并补交实际材料")
    current = evidence(db, [item["contract_id"] for item in saved], contract.id, user, row.resolution)
    actual_hashes = {item["contract_id"]: item["content_sha256"] for item in current}
    if any(not actual_hashes.get(item["contract_id"]) or item["content_sha256"] != actual_hashes[item["contract_id"]] for item in saved):
        raise HTTPException(409, "材料内容已变化或哈希缺失，请退回重新提交后验收")


def transition(db, rc_id, payload, user):
    row, _, contract = load(db, rc_id, user)
    check_version(row, payload.version)
    old, target = row.status, payload.status
    if target not in TRANSITIONS.get(old, set()):
        raise HTTPException(409, "不允许直接进行该状态流转")
    is_review = old in {"待复核", "待风险接受"}
    is_reopen = target == "待处理"
    allowed = {"status", "version"}
    if is_review:
        allowed.add("review_comment")
    elif target == "待复核":
        allowed.update({"resolution", "evidence_contract_ids", "after_text"})
    elif target == "待风险接受":
        allowed.update({"resolution", "acceptance_reason", "residual_risk"})
    if payload.model_fields_set - allowed:
        raise HTTPException(400, "本次操作不允许修改提交结果或其他动作字段")
    if is_review:
        if user.role not in PROFESSIONAL or row.owner == user.username or row.submitted_by == user.id:
            raise HTTPException(403, "必须由非责任人、非本次提交人的专业人员独立验收")
        if old == "待风险接受" and target == "已接受风险" and user.role != "admin":
            raise HTTPException(403, "风险接受必须由另一位管理员批准")
        if not (payload.review_comment or "").strip():
            raise HTTPException(400, "每次验收或退回必须重新填写本次意见")
        if target in {"已闭环", "已接受风险"}:
            validate_plan(db, plan_values(row), contract, row.created)
            if row.submitted_by is None or row.submitted_at is None:
                raise HTTPException(400, "缺少真实提交记录，请退回补齐后重新提交")
            if target == "已闭环" and (not json.loads(row.evidence_json or "[]") or row.contract_stage == "unknown"):
                raise HTTPException(400, "缺少实际材料或合同阶段，请退回补齐")
            if target == "已闭环":
                verify_submission_evidence(db, row, contract, user)
            if target == "已接受风险" and not all((getattr(row, key) or "").strip() for key in ("resolution", "acceptance_reason", "residual_risk")):
                raise HTTPException(400, "缺少风险接受理由、剩余风险或控制措施")
    elif is_reopen:
        professional(user)
        if contract is None:
            raise HTTPException(422, "历史整改缺少来源合同，不能重新开启")
    else:
        if row.owner != user.username:
            raise HTTPException(403, "仅整改责任人可开始及提交整改")
        validate_plan(db, plan_values(row), contract, row.created)
    # 所有前置校验完成后才修改ORM，避免失败请求污染当前事务。
    materials = None
    if target in {"待复核", "待风险接受"} and row.contract_stage == "unknown":
        raise HTTPException(400, "提交前必须确认合同签署阶段")
    if target == "待复核":
        if not (payload.resolution or "").strip():
            raise HTTPException(400, "每次提交必须填写本次整改结果")
        if row.handling_method in {"revision", "supplement"} and not (payload.after_text or "").strip():
            raise HTTPException(400, "修订或补充协议必须填写修改后条款")
        materials = evidence(db, payload.evidence_contract_ids, contract.id, user, payload.resolution.strip())
    if target == "待风险接受" and not all((getattr(payload, key) or "").strip() for key in ("resolution", "acceptance_reason", "residual_risk")):
        raise HTTPException(400, "风险接受必须填写理由、剩余风险及控制措施")
    now = datetime.now(timezone.utc)
    row.status, row.closed_at = target, None
    if target in {"待复核", "待风险接受"}:
        row.resolution = payload.resolution.strip()
        row.submitted_by, row.submitted_at = user.id, now
        row.review_comment, row.reviewed_by, row.reviewed_at = "", None, None
        row.accepted_at = None
        if materials is not None:
            row.evidence_json = json.dumps(materials, ensure_ascii=False)
            row.after_text = (payload.after_text or "").strip()
            row.acceptance_reason, row.residual_risk = "", ""
        else:
            row.acceptance_reason, row.residual_risk = payload.acceptance_reason.strip(), payload.residual_risk.strip()
    elif is_review:
        row.review_comment, row.reviewed_by, row.reviewed_at = payload.review_comment.strip(), user.id, now
        if target == "已闭环":
            row.closed_at = now
        elif target == "已接受风险":
            row.accepted_at = now
    elif is_reopen:
        row.accepted_at = None
    action = ("approve" if target == "已闭环" else "accept" if target == "已接受风险" else "reject" if is_review else "reopen" if is_reopen else "start" if target == "处理中" else "submit" if target == "待复核" else "request_acceptance")
    return persist(db, row, user, action, old)


def update_plan(db, rc_id, payload, user):
    row, _, contract = load(db, rc_id, user)
    professional(user)
    check_version(row, payload.version)
    if row.status not in {"待处理", "处理中"}:
        raise HTTPException(409, "仅待处理或处理中可修改计划")
    previous = plan_values(row)
    values = {**previous, **payload.model_dump(exclude_unset=True, exclude={"version"})}
    validate_plan(db, values, contract, row.created)
    for key in PLAN_FIELDS:
        setattr(row, key, values[key])
    row.collaborators_json = json.dumps(values["collaborators"], ensure_ascii=False)
    # 即使计划内容相同，操作也必须受版本控制并留痕。
    row.version += 1
    return persist(db, row, user, "update_plan", row.status, previous)


def escalate(db, rc_id, payload, user):
    row, _, _ = load(db, rc_id, user)
    check_version(row, payload.version)
    if not output(db, row, user).can_escalate:
        raise HTTPException(403, "仅责任人或专业人员可升级未结项的高风险或逾期整改")
    if not payload.reason.strip():
        raise HTTPException(422, "必须填写本次升级理由")
    row.escalation_reason, row.escalated_at, row.escalated_by = payload.reason.strip(), datetime.now(timezone.utc), user.id
    return persist(db, row, user, "escalate", row.status)
