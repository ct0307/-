"""单综合 Agent 与法财双 Agent 的小规模对照实验。

仅使用合成合同。单 Agent 组复用生产审查链，将首审角色临时替换为同时覆盖
法务与财务职责的综合 Agent；双 Agent 组使用生产法财首审。两组共享确定性
规则、RAG、定向复查、二次复核和发布门禁，不修改生产配置或数据库。
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Any, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
os.chdir(BACKEND_DIR)
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings  # noqa: E402
from app.llm.base import ChatOptions  # noqa: E402
from app.llm.factory import get_llm_adapter  # noqa: E402
from app.services.audit import auditor  # noqa: E402
from app.services.audit.agent_profiles import AgentProfile  # noqa: E402
from app.services.sensitive_data import redact_sensitive_text  # noqa: E402
from evaluation.datasets.frozen_contracts_v2.cases import load_cases  # noqa: E402
from evaluation.datasets.frozen_contracts_v2.content import build_contract  # noqa: E402

DEFAULT_CASE_IDS = ("F2-001", "F2-005", "F2-006", "F2-010", "F2-031", "F2-043")
MODES = ("single", "dual")
SCHEMA_VERSION = "single-dual-agent-v1"

GENERAL_PROFILE = AgentProfile(
    role="legal",
    name="合同综合审查 Agent",
    focus=(
        "违约责任、争议解决、知识产权归属、保密条款、验收标准、合同主体资格、"
        "关联交易识别、合同金额、付款节点、发票绑定、违约金上限、币种与大小写"
        "一致性、预算合规、收款账户与价格公允性"
    ),
    topics=(
        "违约 违约责任 违约金 赔偿 上限",
        "争议 仲裁 诉讼 管辖",
        "知识产权 著作权 保密 数据安全",
        "合同主体 甲方 乙方 关联交易",
        "金额 价款 币种 付款 发票 结算",
        "期限 履约 验收 现金流 收款账户",
    ),
)


class RecordingAdapter:
    """记录模型观测，不保存 API 密钥或端点。"""

    def __init__(self) -> None:
        self._adapter = get_llm_adapter()
        self._lock = threading.Lock()
        self.records: list[dict[str, Any]] = []

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        options: ChatOptions | None = None,
    ) -> Any:
        started = time.perf_counter()
        try:
            response = self._adapter.chat(
                system, user, temperature=temperature, options=options
            )
        except Exception as exc:
            with self._lock:
                self.records.append({
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error_code": getattr(exc, "code", None),
                    "latency_ms": round((time.perf_counter() - started) * 1000),
                    "system_sha256": _text_hash(system),
                    "user_sha256": _text_hash(user),
                })
            raise
        with self._lock:
            self.records.append({
                "ok": True,
                "model": response.model,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "latency_ms": response.latency_ms,
                "finish_reason": response.finish_reason,
                "temperature": temperature,
                "request_id": options.request_id if options else None,
                "system_sha256": _text_hash(system),
                "user_sha256": _text_hash(user),
            })
        return response

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._adapter.embed(texts)


def _text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _target_hits(risks: Iterable[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    normalized_target = _normalized(target)
    if not normalized_target:
        return []
    hits = []
    for risk in risks:
        quote = _normalized(str(risk.get("original_text", "")))
        if quote and (normalized_target in quote or quote in normalized_target):
            hits.append(risk)
    return hits


def summarize_result(
    result: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    risk_level: str,
    target_text: str,
) -> dict[str, Any]:
    risks = list(result.get("risks", []))
    model_risks = [risk for risk in risks if risk.get("agent") != "system"]
    hits = _target_hits(risks, target_text)
    model_hits = _target_hits(model_risks, target_text)
    successful_calls = [row for row in observations if row.get("ok")]
    coverage = result.get("coverage", {})
    execution_complete = (
        int(coverage.get("planned", 0)) > 0
        and coverage.get("completed") == coverage.get("planned")
    )
    all_model_calls_successful = bool(observations) and len(successful_calls) == len(observations)
    return {
        "execution_complete": execution_complete,
        "all_model_calls_successful": all_model_calls_successful,
        "valid_for_comparison": execution_complete and all_model_calls_successful,
        "risk_count": len(risks),
        "model_risk_count": len(model_risks),
        "model_risks_by_agent": dict(sorted(Counter(
            str(risk.get("agent", "unknown")) for risk in model_risks
        ).items())),
        "levels": dict(sorted(Counter(
            str(risk.get("level", "unknown")) for risk in risks
        ).items())),
        "target_hit_count": len(hits),
        "model_target_hit_count": len(model_hits),
        "actionable_model_target_detected": (
            bool(model_hits) if risk_level == "actionable" else None
        ),
        "negotiated_model_target_flagged": (
            bool(model_hits) if risk_level == "negotiated" else None
        ),
        "original_text_verified_count": sum(
            risk.get("original_text_verified") is True for risk in risks
        ),
        "evidence_supported_count": sum(
            risk.get("evidence_status") == "supported"
            and risk.get("support_relation_status") == "supported"
            for risk in risks
        ),
        "manual_review_count": sum(
            risk.get("requires_manual_review") is True for risk in risks
        ),
        "cross_check_count": len(result.get("cross_checks", [])),
        "issue_count": len(result.get("issues", [])),
        "coverage": result.get("coverage", {}),
        "budget": result.get("workflow", {}).get("budget", {}),
        "actual_model_calls": len(observations),
        "successful_model_calls": len(successful_calls),
        "actual_prompt_tokens": sum(
            int(row.get("prompt_tokens", 0)) for row in successful_calls
        ),
        "actual_completion_tokens": sum(
            int(row.get("completion_tokens", 0)) for row in successful_calls
        ),
        "actual_latency_ms_sum": sum(
            int(row.get("latency_ms", 0)) for row in successful_calls
        ),
        "returned_models": sorted({
            str(row.get("model")) for row in successful_calls if row.get("model")
        }),
    }


def _run_one(case: Any, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"未知实验组：{mode}")
    document = build_contract(case)
    contract_text = redact_sensitive_text(document.plain_text)
    recorder = RecordingAdapter()
    original_order = auditor._AGENT_ORDER
    original_profile = auditor.agent_profile
    original_factory = auditor.get_llm_adapter
    original_role_dimensions = auditor._ROLE_DIMENSIONS
    started = time.perf_counter()
    try:
        if mode == "single":
            auditor._AGENT_ORDER = ("legal",)
            auditor.agent_profile = lambda role: (
                GENERAL_PROFILE if role == "legal" else original_profile(role)
            )
            auditor._ROLE_DIMENSIONS = {
                **original_role_dimensions,
                "legal": frozenset(auditor._DIM_TOPICS),
            }
        auditor.get_llm_adapter = lambda: recorder
        result = auditor.audit_contract(
            {},
            contract_text,
            db=None,
            contract_id=None,
            dimensions=[],
            contract_type=case.contract_type,
            deadline=time.monotonic() + settings.AUDIT_DEADLINE_SECONDS,
        )
    finally:
        auditor._AGENT_ORDER = original_order
        auditor.agent_profile = original_profile
        auditor.get_llm_adapter = original_factory
        auditor._ROLE_DIMENSIONS = original_role_dimensions
    target_text = case.risk_clauses[0].text if case.risk_clauses else ""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "case": {
            "case_id": case.case_id,
            "title": case.title,
            "contract_type": case.contract_type,
            "risk_level": case.risk_level,
            "contract_sha256": _text_hash(contract_text),
            "source_contract_sha256": _text_hash(document.plain_text),
            "synthetic_redaction_applied": contract_text != document.plain_text,
            "contract_chars": len(contract_text),
            "target_clause_id": case.risk_clauses[0].clause_id if case.risk_clauses else None,
            "target_text": target_text,
            "evidence_level": "construction_truth_only",
        },
        "experiment": {
            "single_baseline": "一个同时承担法务与财务职责的综合 Agent",
            "dual_treatment": "现有法务与财务专业 Agent 独立首审及结构化协作",
            "shared_components": [
                "合同正文", "模型端点", "确定性规则", "RAG", "定向复查",
                "二次复核", "发布门禁", "输出预算",
            ],
            "requested_model": settings.LLM_MODEL,
            "prompt_version": "2.0.0",
            "single_profile": {
                "name": GENERAL_PROFILE.name,
                "focus": GENERAL_PROFILE.focus,
                "topics": list(GENERAL_PROFILE.topics),
            } if mode == "single" else None,
        },
        "wall_latency_ms": round((time.perf_counter() - started) * 1000),
        "result": result,
        "observations": recorder.records,
        "summary": summarize_result(
            result, recorder.records,
            risk_level=case.risk_level, target_text=target_text,
        ),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_comparison(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_pair = {(run["mode"], run["case"]["case_id"]): run for run in runs}
    case_ids = sorted({run["case"]["case_id"] for run in runs})
    pairs = []
    for case_id in case_ids:
        if not all((mode, case_id) in by_pair for mode in MODES):
            continue
        single = by_pair[("single", case_id)]
        dual = by_pair[("dual", case_id)]
        pairs.append({
            "case_id": case_id,
            "risk_level": single["case"]["risk_level"],
            "valid_for_comparison": bool(
                single["summary"].get("valid_for_comparison")
                and dual["summary"].get("valid_for_comparison")
            ),
            "single": single["summary"],
            "dual": dual["summary"],
        })

    valid_pairs = [pair for pair in pairs if pair["valid_for_comparison"]]
    aggregate: dict[str, Any] = {
        "paired_cases": len(pairs),
        "valid_pairs": len(valid_pairs),
        "excluded_pairs": [pair["case_id"] for pair in pairs if not pair["valid_for_comparison"]],
    }
    for mode in MODES:
        selected = [pair[mode] for pair in valid_pairs]
        actionable = [
            row for pair, row in zip(valid_pairs, selected)
            if pair["risk_level"] == "actionable"
        ]
        negotiated = [
            row for pair, row in zip(valid_pairs, selected)
            if pair["risk_level"] == "negotiated"
        ]
        aggregate[mode] = {
            "risk_count": sum(row["risk_count"] for row in selected),
            "model_risk_count": sum(row["model_risk_count"] for row in selected),
            "actionable_model_target_detected": sum(
                row["actionable_model_target_detected"] is True for row in actionable
            ),
            "actionable_cases": len(actionable),
            "negotiated_model_target_flagged": sum(
                row["negotiated_model_target_flagged"] is True for row in negotiated
            ),
            "negotiated_cases": len(negotiated),
            "original_text_verified_count": sum(
                row["original_text_verified_count"] for row in selected
            ),
            "evidence_supported_count": sum(
                row["evidence_supported_count"] for row in selected
            ),
            "manual_review_count": sum(row["manual_review_count"] for row in selected),
            "actual_model_calls": sum(row["actual_model_calls"] for row in selected),
            "actual_prompt_tokens": sum(row["actual_prompt_tokens"] for row in selected),
            "actual_completion_tokens": sum(
                row["actual_completion_tokens"] for row in selected
            ),
            "actual_latency_ms_sum": sum(row["actual_latency_ms_sum"] for row in selected),
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_level": "construction_truth_only_small_scale",
        "statistical_significance": "not_evaluated",
        "pairs": pairs,
        "aggregate": aggregate,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=list(DEFAULT_CASE_IDS))
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    parser.add_argument(
        "--authorize-configured-endpoint",
        action="store_true",
        help="仅在当前进程内授权 .env 已配置端点；仅发送合成合同，不修改 .env。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if settings.MODEL_PROCESSING_MODE == "external_model":
        if not args.authorize_configured_endpoint:
            raise SystemExit("外部模型实验须显式指定 --authorize-configured-endpoint")
        if not settings.LLM_BASE_URL or not settings.LLM_API_KEY:
            raise SystemExit("当前未完整配置外部模型端点或 API Key")
        settings.MODEL_EXTERNAL_ALLOWED_BASE_URLS = [settings.LLM_BASE_URL]
    selected = {case.case_id: case for case in load_cases() if case.case_id in args.cases}
    missing = sorted(set(args.cases) - set(selected))
    if missing:
        raise SystemExit(f"未知案例：{', '.join(missing)}")
    args.output.mkdir(parents=True, exist_ok=True)
    runs: list[dict[str, Any]] = []
    for case_id in args.cases:
        for mode in args.modes:
            destination = args.output / mode / f"{case_id}.json"
            print(f"RUN {mode} {case_id}", flush=True)
            payload = _run_one(selected[case_id], mode)
            _write_json(destination, payload)
            runs.append(payload)
            print(json.dumps(payload["summary"], ensure_ascii=False), flush=True)
    if set(args.modes) == set(MODES):
        comparison = build_comparison(runs)
        _write_json(args.output / "comparison.json", comparison)
        print(json.dumps(comparison["aggregate"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
