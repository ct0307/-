from app.services.audit.evidence_validation import verify_support


def _risk(**changes):
    value = {
        "category": "违约金过高",
        "original_text": "违约金为合同金额50%",
        "risk_reason": "违约金可能过高",
        "original_text_verified": True,
    }
    value.update(changes)
    return value


def test_expired_source_cannot_be_supported():
    result = verify_support(_risk(), [{
        "content": "约定违约金过分高于损失的，可以请求适当减少。",
        "source": "旧法条",
        "reliable": True,
        "applicability_status": "expired",
    }])
    assert result.status == "unclear"
    assert result.failed_stage == "applicability"


def test_contradicting_authorized_source_is_contradicted():
    result = verify_support(
        _risk(category="法定书面形式缺失", original_text="双方仅口头约定"),
        [{
            "content": "当事人订立合同，可以采用书面形式、口头形式或者其他形式。",
            "source": "授权法条",
            "reliable": True,
            "applicability_status": "applicable",
        }],
        semantic_verifier=lambda _risk, _sources: "contradicted",
    )
    assert result.status == "contradicted"
    assert result.failed_stage == "semantic_relation"


def test_missing_original_quote_stops_at_original_stage():
    result = verify_support(_risk(original_text=""), [{
        "content": "违约金过高的约定可以调整。",
        "source": "现行法条",
        "reliable": True,
        "applicability_status": "applicable",
    }])
    assert result.status == "unclear"
    assert result.failed_stage == "original"


def test_unreliable_source_stops_at_authority_stage():
    result = verify_support(_risk(), [{
        "content": "违约金过高",
        "source": "未核验网页",
        "reliable": False,
        "applicability_status": "applicable",
    }])
    assert result.status == "unclear"
    assert result.failed_stage == "authority"


def test_v3_result_has_reason_and_version():
    result = verify_support(_risk(), [{
        "content": "违约金过高的约定可以调整。违约金为合同金额50%。",
        "source": "现行法条",
        "reliable": True,
        "applicability_status": "applicable",
    }])
    assert result.version == "support-v4"
    assert result.reason_code
    assert result.failed_stage in {"none", "facts", "semantic_relation"}
