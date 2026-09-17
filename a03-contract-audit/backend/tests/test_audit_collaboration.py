"""法务与财务 Agent 的独立首审和结构化交接。"""

from app.llm.base import LLMResponse
from app.services.audit import auditor
from app.services.audit.collaboration import (
    build_review_handoff,
    first_pass,
)


def test_finance_first_pass_does_not_receive_legal_claims(monkeypatch):
    prompts: list[tuple[str, str]] = []

    class Adapter:
        def chat(self, system, user, **_kwargs):
            prompts.append((system, user))
            return LLMResponse(
                text='{"risks":[],"has_more":false}',
                model="test",
            )

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    auditor.audit_contract({}, "第一条 关联方提供服务。")

    finance_first_pass = next(
        user for system, user in prompts if "你是财务" in system
    )
    assert "法务 Agent 已完成" not in finance_first_pass
    assert "结构化 Claims" not in finance_first_pass


def test_first_pass_runs_agents_without_cross_agent_input():
    calls: list[str] = []

    bundle = first_pass(
        lambda role: calls.append(role) or f"{role}-result",
        roles=("legal", "finance"),
    )

    assert calls == ["legal", "finance"]
    assert bundle.legal == "legal-result"
    assert bundle.finance == "finance-result"


def test_review_handoff_contains_only_allowlisted_structured_fields():
    handoff = build_review_handoff(
        from_agent="legal",
        to_agent="finance",
        risks=[{
            "claim_id": "C-LEGAL-001",
            "category": "关联交易",
            "source_clause_ids": ["第一条"],
            "original_text": "关联方提供服务",
            "risk_reason": "这段自由推理不得交接",
            "suggestion": "这段自由建议不得交接",
        }],
        payment_schedule={
            "status": "complete",
            "total_percentage": "100",
            "clause_ids": ["第二条"],
            "calculation": "50% + 50% = 100%",
        },
    )

    payload = handoff.to_payload()

    assert payload == {
        "from_agent": "legal",
        "to_agent": "finance",
        "claim_ids": ["C-LEGAL-001"],
        "categories": ["关联交易"],
        "clause_ids": [["第一条"]],
        "deterministic_facts": {
            "payment_status": "complete",
            "payment_total_percentage": "100",
            "payment_clause_ids": ["第二条"],
        },
        "reason_codes": ["RELATED_PARTY_REVIEW"],
    }
    assert "original_text" not in str(payload)
    assert "risk_reason" not in str(payload)
    assert "suggestion" not in str(payload)
