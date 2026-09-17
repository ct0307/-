import hashlib

import pytest
from pydantic import ValidationError

from app.services.audit.claims import (
    CLAIM_SCHEMA_VERSION,
    AuditClaim,
    claim_id_for,
)


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
