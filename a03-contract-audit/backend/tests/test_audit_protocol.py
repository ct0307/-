from typing import get_args

import pytest
from pydantic import ValidationError

from app.services.audit.protocol import (
    AUDIT_JSON_FORMAT,
    AUDIT_PROTOCOL_VERSION,
    AgentReviewResult,
    ReviewIssue,
    RiskCandidate,
    ReviewedRiskCandidate,
    RiskEnvelope,
    SecondaryDecision,
    SecondaryEnvelope,
    parse_risk_envelope,
)


def risk_payload(**overrides):
    payload = {
        "level": "high",
        "category": "付款风险",
        "quote": "乙方应在收到全部款项后履行义务。",
        "reason": "付款条件对甲方不利，缺少履约保障。",
        "suggestion": "将付款与验收节点绑定，并保留合理尾款。",
    }
    payload.update(overrides)
    return payload


def secondary_decision_payload(**overrides):
    payload = {
        "claim_id": "claim-001",
        "verdict": "confirm",
        "reason": "valid reason",
        "evidence_ids": ["evidence-1"],
    }
    payload.update(overrides)
    return payload


RISK_STRING_BOUNDS = (
    ("category", 2, 64),
    ("quote", 2, 500),
    ("reason", 4, 800),
    ("suggestion", 4, 800),
)

EXPECTED_REVIEW_ISSUE_CODES = {
    "OUTPUT_TRUNCATED",
    "INVALID_MODEL_OUTPUT",
    "MODEL_TIMEOUT",
    "MODEL_UNAVAILABLE",
    "PAGINATION_EXHAUSTED",
    "EVIDENCE_UNRESOLVED",
    "ORIGINAL_TEXT_UNRESOLVED",
    "PARSE_QUALITY_LOW",
    "CONTRACT_TEXT_INCOMPLETE",
    "SECONDARY_REVIEW_CONFLICT",
}


def test_protocol_constants_define_json_object_contract():
    assert AUDIT_PROTOCOL_VERSION == "candidate-v2"
    assert AUDIT_JSON_FORMAT == {"type": "json_object"}


def test_parse_risk_envelope_accepts_valid_object_and_strips_strings():
    envelope = parse_risk_envelope(
        '{"risks":[{"level":" high ","category":" 付款风险 ",'
        '"quote":" 应在约定日期付款 ","reason":" 付款保障不足 ",'
        '"suggestion":" 增加验收后付款条款 "}]}'
    )

    candidate = envelope.risks[0]
    assert candidate.level == "high"
    assert candidate.category == "付款风险"
    assert candidate.quote == "应在约定日期付款"
    assert candidate.reason == "付款保障不足"
    assert candidate.suggestion == "增加验收后付款条款"
    assert envelope.has_more is False


@pytest.mark.parametrize(
    "text",
    [
        "[]",
        "```json\n{}\n```",
        "prefix {}",
        "{} suffix",
    ],
)
def test_parse_risk_envelope_rejects_non_object_framing(text):
    with pytest.raises(ValueError):
        parse_risk_envelope(text)


@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": True},
        {"risks": [risk_payload()] * 6},
        {"risks": [risk_payload(level="critical")]},
        {"risks": [risk_payload(quote="x" * 501)]},
    ],
)
def test_parse_risk_envelope_rejects_invalid_model_payload(payload):
    import json

    with pytest.raises(ValidationError):
        parse_risk_envelope(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("category", "x"),
        ("category", "x" * 65),
        ("quote", "x"),
        ("reason", "x" * 3),
        ("reason", "x" * 801),
        ("suggestion", "x" * 3),
        ("suggestion", "x" * 801),
    ],
)
def test_risk_candidate_enforces_string_boundaries(field, value):
    with pytest.raises(ValidationError):
        RiskCandidate.model_validate(risk_payload(**{field: value}))


@pytest.mark.parametrize(
    "payload",
    [
        {"code": "UNKNOWN", "agent": "audit", "detail": "无效问题代码"},
        {"code": "MODEL_TIMEOUT", "agent": "a" * 17, "detail": "超出代理名称长度"},
        {"code": "MODEL_TIMEOUT", "agent": "audit", "detail": "x" * 256},
        {
            "code": "MODEL_TIMEOUT",
            "agent": "audit",
            "window_id": "w" * 65,
            "detail": "窗口标识过长",
        },
        {
            "code": "MODEL_TIMEOUT",
            "agent": "audit",
            "detail": "无效额外字段",
            "unexpected": True,
        },
    ],
)
def test_review_issue_rejects_invalid_codes_and_boundaries(payload):
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(payload)


def test_review_issue_accepts_exact_issue_code_and_strips_values():
    issue = ReviewIssue(
        code="OUTPUT_TRUNCATED",
        agent=" audit ",
        window_id=" window-1 ",
        detail=" 输出被截断 ",
    )

    assert issue.agent == "audit"
    assert issue.window_id == "window-1"
    assert issue.detail == "输出被截断"


@pytest.mark.parametrize(
    "payload",
    [
        {"complete": False, "planned_windows": 1, "completed_windows": 2},
        {"complete": True, "planned_windows": 2, "completed_windows": 1},
        {"complete": True, "planned_windows": 1, "completed_windows": 0},
    ],
)
def test_agent_review_result_rejects_inconsistent_window_progress(payload):
    with pytest.raises(ValidationError):
        AgentReviewResult.model_validate(payload)


def test_agent_review_result_defaults_and_accepts_complete_progress():
    result = AgentReviewResult(complete=True, planned_windows=2, completed_windows=2)

    assert result.candidates == []
    assert result.issues == []


@pytest.mark.parametrize(
    "payload",
    [
        {"claim_id": "short", "verdict": "confirm", "reason": "理由充分"},
        {"claim_id": "claim-001", "verdict": "unknown", "reason": "理由充分"},
        {"claim_id": "claim-001", "verdict": "confirm", "reason": "bad"},
        {
            "claim_id": "claim-001",
            "verdict": "confirm",
            "reason": "理由充分",
            "evidence_ids": ["evidence"] * 9,
        },
        {
            "claim_id": "claim-001",
            "verdict": "confirm",
            "reason": "理由充分",
            "extra": True,
        },
    ],
)
def test_secondary_decision_rejects_invalid_or_extra_values(payload):
    with pytest.raises(ValidationError):
        SecondaryDecision.model_validate(payload)


def test_secondary_envelope_is_strict_and_limits_decisions():
    decision = {
        "claim_id": "claim-001",
        "verdict": "conflict",
        "reason": "证据之间存在直接矛盾。",
        "evidence_ids": ["evidence-1"],
    }

    envelope = SecondaryEnvelope(decisions=[decision] * 5)
    assert len(envelope.decisions) == 5

    with pytest.raises(ValidationError):
        SecondaryEnvelope.model_validate({"decisions": [decision] * 6})
    with pytest.raises(ValidationError):
        SecondaryEnvelope.model_validate({"unknown": []})


@pytest.mark.parametrize(("field", "minimum", "maximum"), RISK_STRING_BOUNDS)
def test_risk_candidate_enforces_exact_stripped_string_boundaries(
    field, minimum, maximum
):
    for length in (minimum, maximum):
        candidate = RiskCandidate.model_validate(
            risk_payload(**{field: f" {'x' * length} "})
        )
        assert getattr(candidate, field) == "x" * length

    for length in (minimum - 1, maximum + 1):
        with pytest.raises(ValidationError):
            RiskCandidate.model_validate(risk_payload(**{field: "x" * length}))


def test_review_issue_code_annotation_is_exact_and_all_codes_are_valid():
    codes = set(get_args(ReviewIssue.model_fields["code"].annotation))

    assert codes == EXPECTED_REVIEW_ISSUE_CODES
    for code in codes:
        assert ReviewIssue(
            code=code,
            agent="audit",
            detail="valid issue detail",
        ).code == code


@pytest.mark.parametrize(
    "payload",
    [
        {"complete": False, "planned_windows": 0, "completed_windows": 0},
        {"complete": False, "planned_windows": 1, "completed_windows": -1},
    ],
)
def test_agent_review_result_rejects_invalid_window_counts(payload):
    with pytest.raises(ValidationError):
        AgentReviewResult.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "valid_lengths", "invalid_lengths"),
    [
        ("claim_id", (8, 64), (7, 65)),
        ("reason", (4, 500), (3, 501)),
    ],
)
def test_secondary_decision_enforces_exact_string_boundaries(
    field, valid_lengths, invalid_lengths
):
    for length in valid_lengths:
        decision = SecondaryDecision.model_validate(
            secondary_decision_payload(**{field: "x" * length})
        )
        assert getattr(decision, field) == "x" * length

    for length in invalid_lengths:
        with pytest.raises(ValidationError):
            SecondaryDecision.model_validate(
                secondary_decision_payload(**{field: "x" * length})
            )


def test_secondary_decision_enforces_evidence_id_limit():
    decision = SecondaryDecision.model_validate(
        secondary_decision_payload(evidence_ids=["evidence"] * 8)
    )

    assert len(decision.evidence_ids) == 8
    with pytest.raises(ValidationError):
        SecondaryDecision.model_validate(
            secondary_decision_payload(evidence_ids=["evidence"] * 9)
        )


def test_secondary_envelope_enforces_exact_decision_limit():
    decision = secondary_decision_payload()
    envelope = SecondaryEnvelope.model_validate({"decisions": [decision] * 5})

    assert len(envelope.decisions) == 5
    with pytest.raises(ValidationError):
        SecondaryEnvelope.model_validate({"decisions": [decision] * 6})


def review_issue_payload(**overrides):
    payload = {
        "code": "MODEL_TIMEOUT",
        "agent": "audit",
        "detail": "valid issue detail",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("length", [1, 16])
def test_review_issue_accepts_exact_stripped_agent_boundaries(length):
    issue = ReviewIssue.model_validate(
        review_issue_payload(agent=f" {'a' * length} ")
    )

    assert issue.agent == "a" * length


@pytest.mark.parametrize("agent", ["", " ", "a" * 17])
def test_review_issue_rejects_empty_or_overlong_agent(agent):
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(review_issue_payload(agent=agent))


@pytest.mark.parametrize("length", [1, 255])
def test_review_issue_accepts_exact_stripped_detail_boundaries(length):
    issue = ReviewIssue.model_validate(
        review_issue_payload(detail=f" {'d' * length} ")
    )

    assert issue.detail == "d" * length


@pytest.mark.parametrize("detail", ["", " ", "d" * 256])
def test_review_issue_rejects_empty_or_overlong_detail(detail):
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(review_issue_payload(detail=detail))


@pytest.mark.parametrize("window_id", [None, "w" * 64])
def test_review_issue_accepts_none_and_exact_max_window_id(window_id):
    issue = ReviewIssue.model_validate(review_issue_payload(window_id=window_id))

    assert issue.window_id == window_id


def test_review_issue_allows_empty_window_id_without_a_minimum_length():
    issue = ReviewIssue.model_validate(review_issue_payload(window_id=""))

    assert issue.window_id == ""


def test_review_issue_rejects_overlong_window_id():
    with pytest.raises(ValidationError):
        ReviewIssue.model_validate(review_issue_payload(window_id="w" * 65))


def test_risk_envelope_enforces_exact_risk_limit():
    envelope = RiskEnvelope.model_validate({"risks": [risk_payload()] * 5})

    assert len(envelope.risks) == 5
    with pytest.raises(ValidationError):
        RiskEnvelope.model_validate({"risks": [risk_payload()] * 6})


def test_agent_review_result_defaults_are_independent():
    first = AgentReviewResult(complete=False)
    second = AgentReviewResult(complete=False)

    assert first.planned_windows == 1
    assert first.completed_windows == 0
    assert first.complete is False
    assert second.candidates == []
    assert second.issues == []

    first.candidates.append(ReviewedRiskCandidate(**risk_payload(), source_window_id="window-1"))
    first.issues.append(ReviewIssue.model_validate(review_issue_payload()))

    assert second.candidates == []
    assert second.issues == []


@pytest.mark.parametrize(
    "model",
    [
        RiskCandidate,
        RiskEnvelope,
        ReviewIssue,
        AgentReviewResult,
        SecondaryDecision,
        SecondaryEnvelope,
    ],
)
def test_all_protocol_models_enable_strict_validation(model):
    assert model.model_config["strict"] is True


@pytest.mark.parametrize(
    "text",
    [
        '{"has_more":"yes"}',
        '{"has_more":"true"}',
    ],
)
def test_risk_envelope_json_rejects_string_booleans(text):
    with pytest.raises(ValidationError):
        RiskEnvelope.model_validate_json(text)


@pytest.mark.parametrize(
    "text",
    [
        '{"complete":"false"}',
        '{"complete":"true","completed_windows":1}',
        '{"complete":false,"planned_windows":"2"}',
        '{"complete":false,"planned_windows":2.0}',
    ],
)
def test_agent_review_result_json_rejects_coerced_types(text):
    with pytest.raises(ValidationError):
        AgentReviewResult.model_validate_json(text)


def test_agent_review_result_complete_defaults_to_finished_single_window():
    result = AgentReviewResult(candidates=[], issues=[], complete=True)

    assert result.planned_windows == 1
    assert result.completed_windows == 1
    assert result.complete is True


def test_agent_review_result_complete_defaults_to_explicit_planned_windows():
    result = AgentReviewResult(complete=True, planned_windows=3)

    assert result.completed_windows == 3


def test_agent_review_result_keeps_explicit_inconsistent_completion_invalid():
    with pytest.raises(ValidationError):
        AgentReviewResult(
            complete=True,
            planned_windows=2,
            completed_windows=1,
        )


def test_agent_review_result_and_risk_envelope_json_round_trip():
    agent_result = AgentReviewResult(
        candidates=[ReviewedRiskCandidate(**risk_payload(), source_window_id="window-1", source_clause_ids=["第一条"])],
        complete=True,
    )
    risk_envelope = RiskEnvelope(risks=[RiskCandidate.model_validate(risk_payload())])

    restored_agent_result = AgentReviewResult.model_validate_json(
        agent_result.model_dump_json()
    )
    restored_risk_envelope = RiskEnvelope.model_validate_json(
        risk_envelope.model_dump_json()
    )

    assert restored_agent_result == agent_result
    assert restored_risk_envelope == risk_envelope


@pytest.mark.parametrize("field,value", [("source_window_id", "forged"), ("source_clause_ids", ["伪造条款"])])
def test_model_envelope_cannot_supply_system_provenance(field, value):
    with pytest.raises(ValidationError):
        RiskEnvelope.model_validate({"risks": [risk_payload(**{field: value})]})
