"""合同风险发现和补全提示词构建器。"""
from __future__ import annotations

from app.services.audit.agent_profiles import AgentProfile
from app.services.audit.prompts.registry import get_prompt


PROMPT_VERSION = "2.1.0"


def build_review_system_prompt(
    profile: AgentProfile,
    *,
    focus: str,
    dimension_instruction: str,
) -> str:
    return get_prompt(f"{profile.role}.review", PROMPT_VERSION).render(
        agent_name=profile.name,
        focus=focus,
        dimension_instruction=dimension_instruction,
    )


def build_discovery_system_prompt(
    profile: AgentProfile,
    *,
    focus: str,
    dimension_instruction: str,
) -> str:
    return get_prompt(f"{profile.role}.discovery", PROMPT_VERSION).render(
        agent_name=profile.name,
        focus=focus,
        dimension_instruction=dimension_instruction,
    )


def build_enrichment_system_prompt(profile: AgentProfile) -> str:
    return get_prompt(f"{profile.role}.enrichment", PROMPT_VERSION).render(
        agent_name=profile.name,
    )
