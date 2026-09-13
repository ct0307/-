"""合同数据归属部门权限测试。"""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.deps import allowed_departments, require_department_access
from app.api.v1.endpoints import batches, contracts, imports, risks
from app.api.v1.endpoints.admin import update_user_departments
from app.db.session import Base
from app.models.models import AuditBatch, AuditLog, Contract, ImportBatch, ImportBatchItem, LookupItem, Risk, User
from app.schemas.contract import DepartmentScopeUpdate, RiskStatusUpdate


def user(role: str, department: str, grants: list[str]) -> User:
    return User(
        username=role,
        password_hash="x",
        role=role,
        department=department,
        authorized_departments_json=json.dumps(grants, ensure_ascii=False),
    )


def test_business_user_is_limited_to_own_department():
    actor = user("business", "采购中心", ["法务部"])

    assert allowed_departments(actor) == {"采购中心"}


def test_legal_user_uses_configured_departments_and_keeps_own_department():
    actor = user("legal", "法务部", ["采购中心", "研发部"])

    assert allowed_departments(actor) == {"法务部", "采购中心", "研发部"}


def test_department_guard_rejects_out_of_scope_department():
    actor = user("legal", "法务部", ["采购中心"])

    with pytest.raises(HTTPException) as error:
        require_department_access(actor, "财务部")

    assert error.value.status_code == 403


def test_admin_updates_known_department_scope_and_records_audit_log():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = user("admin", "管理部", [])
        admin.username = "admin"
        legal = user("legal", "法务部", [])
        db.add_all([admin, legal, LookupItem(category="department", value="采购中心")])
        db.commit()

        result = update_user_departments(
            legal.id,
            DepartmentScopeUpdate(departments=["采购中心"]),
            db=db,
            user=admin,
        )

        assert result.authorized_departments == ["法务部", "采购中心"]
        log = db.query(AuditLog).filter(AuditLog.action == "department_scope_update").one()
        assert log.target == f"user:{legal.id}"


def test_admin_rejects_unknown_department_scope():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = user("admin", "管理部", [])
        legal = user("legal", "法务部", [])
        db.add_all([admin, legal])
        db.commit()

        with pytest.raises(HTTPException) as error:
            update_user_departments(
                legal.id,
                DepartmentScopeUpdate(departments=["不存在部门"]),
                db=db,
                user=admin,
            )

        assert error.value.status_code == 422


def test_legal_user_can_access_audit_batch_for_authorized_department():
    actor = user("legal", "法务部", ["采购中心"])
    batch = AuditBatch(
        owner_id=99,
        department="采购中心",
        idempotency_key="authorized-batch",
    )

    batches._require_batch_access(batch, actor)


def test_contract_access_uses_authorized_department_scope():
    actor = user("legal", "法务部", ["采购中心"])
    authorized = Contract(
        filename="采购合同.txt",
        storage_path="purchase.txt",
        department="采购中心",
        uploaded_by=1,
    )
    unauthorized = Contract(
        filename="财务合同.txt",
        storage_path="finance.txt",
        department="财务部",
        uploaded_by=1,
    )

    assert contracts._dept_accessible(authorized, actor) is True
    assert contracts._dept_accessible(unauthorized, actor) is False


def test_import_batch_owner_loses_access_after_department_grant_is_revoked():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        actor = user("legal", "法务部", [])
        db.add(actor)
        db.flush()
        contract = Contract(
            filename="采购合同.txt",
            storage_path="purchase.txt",
            department="采购中心",
            uploaded_by=actor.id,
        )
        batch = ImportBatch(owner_id=actor.id, idempotency_key="revoked-import")
        batch.items.append(ImportBatchItem(filename=contract.filename, contract=contract, status="ready"))
        db.add(batch)
        db.commit()

        with pytest.raises(HTTPException) as error:
            imports._get_batch(db, batch.id, actor)

        assert error.value.status_code == 403


def test_risk_status_update_rejects_contract_outside_authorized_departments():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        actor = user("legal", "法务部", [])
        owner = user("business", "财务部", [])
        owner.username = "finance-owner"
        db.add_all([actor, owner])
        db.flush()
        contract = Contract(
            filename="财务合同.txt",
            storage_path="finance.txt",
            department="财务部",
            uploaded_by=owner.id,
        )
        risk = Risk(
            contract=contract,
            level="high",
            category="付款风险",
            original_text="原文",
            basis="依据",
            suggestion="建议",
        )
        db.add(risk)
        db.commit()

        with pytest.raises(HTTPException) as error:
            risks.update_risk_status(
                risk.id,
                RiskStatusUpdate(review_status="confirmed"),
                db=db,
                user=actor,
            )

        assert error.value.status_code == 403
        assert db.get(Risk, risk.id).review_status == "pending"
