import hashlib

import pytest
from pydantic import ValidationError

from app.services.audit import auditor
from app.services.audit.claims import (
    CLAIM_SCHEMA_VERSION,
    AuditClaim,
    claim_id_for,
    normalize_finding,
)
from app.services.audit.protocol import RiskFinding


def test_claim_id_is_stable_and_keeps_existing_risk_identity():
    claim = AuditClaim(
        agent="legal",
        level="high",
        category="付款条件不明确",
        dimension="payment",
        subject="甲方",
        action="支付尾款",
        condition="验收完成",
        consequence="支付20%合同款",
        quote="验收完成后支付剩余款项",
        clause_ids=["C-18"],
        missing_information=["付款期限"],
        review_targets=["finance"],
    )

    legacy_payload = "legal\0付款条件不明确\0验收完成后支付剩余款项"
    expected = "C-" + hashlib.sha256(
        legacy_payload.encode("utf-8")
    ).hexdigest()[:16].upper()

    assert claim.claim_id == claim_id_for(claim) == expected
    assert claim.schema_version == CLAIM_SCHEMA_VERSION == "claim-v1"


def test_claim_id_ignores_formatting_whitespace_but_not_business_text():
    compact = AuditClaim(
        agent="finance",
        level="medium",
        category="付款期限",
        dimension="payment",
        quote="验收后付款",
    )
    spaced = AuditClaim(
        agent="finance",
        level="medium",
        category="付款期限",
        dimension="payment",
        quote="验收 后付款",
    )
    changed = AuditClaim(
        agent="finance",
        level="medium",
        category="付款期限",
        dimension="payment",
        quote="交付后付款",
    )

    assert compact.claim_id == spaced.claim_id
    assert compact.claim_id != changed.claim_id


def test_claim_rejects_empty_quote_and_unknown_fields():
    with pytest.raises(ValidationError):
        AuditClaim(
            agent="legal",
            level="high",
            category="主体风险",
            dimension="legal",
            quote=" ",
        )

    with pytest.raises(ValidationError):
        AuditClaim(
            agent="legal",
            level="high",
            category="主体风险",
            dimension="legal",
            quote="主体信息缺失",
            confidence=99,
        )


def test_normalize_finding_preserves_agent_window_and_clause_ids():
    finding = RiskFinding(
        level="medium",
        category="付款期限",
        quote="验收后付款",
    )

    claim = normalize_finding(
        finding,
        agent="finance",
        dimension="payment",
        window_id="window-1",
        clause_ids=("第三条",),
    )

    assert claim.agent == "finance"
    assert claim.level == finding.level
    assert claim.category == finding.category
    assert claim.quote == finding.quote
    assert claim.dimension == "payment"
    assert claim.source_window_id == "window-1"
    assert claim.clause_ids == ["第三条"]
    assert (claim.subject, claim.action, claim.condition, claim.consequence) == (
        "",
        "",
        "",
        "",
    )


def test_claim_adapter_keeps_existing_risk_api_fields():
    claim = AuditClaim(
        agent="finance",
        level="medium",
        category="付款期限",
        dimension="payment",
        quote="验收后付款",
        source_window_id="window-1",
        clause_ids=["第三条"],
    )

    risk = auditor._risk_from_claim(
        claim,
        risk_reason="付款期限不明确",
        suggestion="补充付款期限",
    )

    assert risk["claim_id"] == claim.claim_id
    assert risk["agent"] == "finance"
    assert risk["original_text"] == claim.quote
    assert risk["source_window_id"] == "window-1"
    assert risk["source_clause_ids"] == ["第三条"]
    assert risk["risk_reason"] == "付款期限不明确"
    assert risk["suggestion"] == "补充付款期限"
