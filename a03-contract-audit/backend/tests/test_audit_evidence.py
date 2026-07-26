"""单条风险法规证据链契约。"""
from app.llm.base import LLMResponse
from app.services.audit import auditor
from app.services.audit.evidence import bind_risk_evidence, build_evidence_query


def test_risk_evidence_query_contains_category_and_original_text():
    assert build_evidence_query("违约金过高", "每日按合同金额的1%计收") == (
        "违约金过高 每日按合同金额的1%计收"
    )


def test_risk_evidence_query_limits_untrusted_original_text():
    query = build_evidence_query("付款风险", "甲" * 500)

    assert query.startswith("付款风险 ")
    assert len(query.removeprefix("付款风险 ")) == 240


def test_each_risk_binds_its_own_retrieved_sources():
    queries: list[tuple[str, int]] = []

    def fake_search(query: str, *, top_k: int):
        queries.append((query, top_k))
        return [{"content": "约定违约金过高时可以适当减少。", "source": "民法典第585条", "score": 0.9}]

    risk = {"category": "违约金过高", "original_text": "每日按合同金额的1%计收"}
    result = bind_risk_evidence(risk, search=fake_search, top_k=2)

    assert queries == [("违约金过高 每日按合同金额的1%计收", 2)]
    assert result["rag_sources"][0]["source"] == "民法典第585条"
    assert "民法典第585条" in result["basis"]


def test_missing_evidence_requires_manual_review():
    risk = {"category": "未知风险", "original_text": "未知条款"}

    result = bind_risk_evidence(risk, search=lambda *_args, **_kwargs: [])

    assert result["rag_sources"] == []
    assert "人工复核" in result["basis"]


def test_selected_dimensions_are_enforced_in_agent_prompt(monkeypatch):
    captured: list[str] = []

    class Adapter:
        def chat(self, system: str, _user: str) -> LLMResponse:
            captured.append(system)
            return LLMResponse(text="[]", model="test")

    monkeypatch.setattr(auditor, "get_llm_adapter", lambda: Adapter())
    monkeypatch.setattr(auditor, "retrieve", lambda *_args, **_kwargs: [])

    auditor._agent_audit(
        "legal",
        {},
        "合同正文",
        {"elements": {}},
        dimensions=["confidentiality"],
    )

    assert "本次仅审查以下维度：保密条款审查" in captured[0]
