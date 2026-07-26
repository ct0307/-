"""报表查询和导出的部门数据隔离。"""
from io import BytesIO

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.v1.endpoints.reports import department_scope_for, export_report
from app.db.session import Base
from app.models.models import Contract, Risk, User
from app.services.report.exporter import contracts_metadata, export_risk_ledger, report_summary


def _seed() -> tuple[Session, User, Contract, Contract]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    business = User(
        username="business",
        password_hash="not-used",
        role="business",
        department="采购中心",
    )
    db.add(business)
    db.flush()
    own = Contract(
        filename="采购合同.txt",
        storage_path="own.txt",
        department="采购中心",
        uploaded_by=business.id,
    )
    other = Contract(
        filename="财务合同.txt",
        storage_path="other.txt",
        department="财务部",
        uploaded_by=business.id,
    )
    db.add_all([own, other])
    db.flush()
    db.add_all([
        Risk(
            contract_id=own.id,
            level="high",
            category="付款风险",
            original_text="采购原文",
            basis="采购依据",
            suggestion="采购建议",
        ),
        Risk(
            contract_id=other.id,
            level="high",
            category="账户风险",
            original_text="财务原文",
            basis="财务依据",
            suggestion="财务建议",
        ),
    ])
    db.commit()
    return db, business, own, other


def test_business_summary_only_counts_own_department():
    db, business, _own, _other = _seed()

    result = report_summary(db, department_scope=department_scope_for(business))

    assert result["kpi"]["total"] == 1
    assert result["kpi"]["risk"] == 1
    assert result["depts"] == [{"name": "采购中心", "risk": 1, "money": "—"}]


def test_business_metadata_only_returns_own_department():
    db, business, own, _other = _seed()

    result = contracts_metadata(db, department_scope=department_scope_for(business))

    assert [row["id"] for row in result] == [own.id]


def test_business_excel_only_contains_own_department():
    db, business, _own, _other = _seed()

    content = export_risk_ledger(db, department_scope=department_scope_for(business))
    sheet = load_workbook(BytesIO(content), read_only=True).active
    filenames = [row[0] for row in sheet.iter_rows(min_row=2, values_only=True)]

    assert filenames == ["采购合同.txt"]


def test_business_export_rejects_explicit_other_department_contract():
    db, business, _own, other = _seed()

    with pytest.raises(HTTPException) as exc_info:
        export_report(contract_ids=[other.id], db=db, user=business)

    assert exc_info.value.status_code == 403
