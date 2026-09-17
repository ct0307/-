import pytest

from app.services.audit.agent_profiles import (
    AGENT_ORDER,
    DIMENSION_TOPICS,
    ROLE_DIMENSIONS,
    agent_profile,
)
from app.services.audit.prompts.registry import get_prompt
from app.services.audit.prompts.review import (
    build_discovery_system_prompt,
    build_enrichment_system_prompt,
)


def test_prompt_registry_returns_versioned_template_and_stable_hash():
    prompt = get_prompt("legal.discovery", "2.0.0")

    assert prompt.prompt_id == "legal.discovery"
    assert prompt.version == "2.0.0"
    assert len(prompt.template_sha256) == 64
    assert "不得生成法规依据" in prompt.system
    assert get_prompt("legal.discovery", "2.0.0") == prompt


def test_prompt_registry_rejects_unknown_version():
    with pytest.raises(ValueError, match="未知提示词版本"):
        get_prompt("legal.discovery", "9.9.9")


def test_prompt_builders_keep_role_focus_and_dimension_instruction():
    profile = agent_profile("finance")
    discovery = build_discovery_system_prompt(
        profile,
        focus="金额与付款条款",
        dimension_instruction="本次仅审查以下维度：金额与付款条款。",
    )
    enrichment = build_enrichment_system_prompt(profile)

    assert "财务会计 Agent" in discovery
    assert "金额与付款条款" in discovery
    assert "本次仅审查以下维度" in discovery
    assert "不得生成法规依据" in discovery
    assert "批量" in enrichment
    assert "reason" in enrichment and "suggestion" in enrichment


def test_agent_profiles_preserve_existing_role_routes():
    assert AGENT_ORDER == ("legal", "finance")
    assert "confidentiality" in ROLE_DIMENSIONS["legal"]
    assert "confidentiality" not in ROLE_DIMENSIONS["finance"]
    assert DIMENSION_TOPICS["payment"] == "金额 付款 发票 结算"
    assert agent_profile("legal").topics[0] == "违约 违约责任 违约金"
