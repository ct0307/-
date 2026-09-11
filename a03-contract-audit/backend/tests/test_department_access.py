"""合同数据归属部门权限测试。"""

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.deps import allowed_departments, require_department_access
from app.api.v1.endpoints.admin import update_user_departments
from app.db.session import Base
from app.models.models import AuditLog, LookupItem, User
from app.schemas.contract import DepartmentScopeUpdate


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
