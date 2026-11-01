from evaluation.single_dual_agent import build_comparison, summarize_result


TARGET = "逾期付款每日按应付金额千分之三计收违约金。"


def _risk(agent="legal", quote=TARGET, **overrides):
    risk = {
        "agent": agent,
        "level": "high",
        "original_text": quote,
        "original_text_verified": True,
        "evidence_status": "partially_supported",
        "support_relation_status": "unclear",
        "requires_manual_review": True,
    }
    risk.update(overrides)
    return risk


def _run(mode, case_id="F2-006", risk_level="actionable"):
    result = {
        "risks": [_risk()],
        "cross_checks": [],
        "issues": [],
        "coverage": {"planned": 1, "completed": 1},
        "workflow": {"budget": {"calls": 1}},
    }
    observations = [{
        "ok": True,
        "model": "test-model",
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "latency_ms": 20,
    }]
    return {
        "mode": mode,
        "case": {"case_id": case_id, "risk_level": risk_level},
        "summary": summarize_result(
            result, observations, risk_level=risk_level, target_text=TARGET
        ),
    }


def test_actionable_target_detection_excludes_common_system_rules():
    result = {
        "risks": [_risk(agent="system")],
        "cross_checks": [],
        "issues": [],
        "coverage": {},
        "workflow": {},
    }
    summary = summarize_result(
        result, [], risk_level="actionable", target_text=TARGET
    )
    assert summary["target_hit_count"] == 1
    assert summary["model_target_hit_count"] == 0
    assert summary["actionable_model_target_detected"] is False


def test_negotiated_target_flag_is_separate_from_actionable_recall():
    result = {
        "risks": [_risk(level="medium")],
        "cross_checks": [],
        "issues": [],
        "coverage": {},
        "workflow": {},
    }
    summary = summarize_result(
        result, [], risk_level="negotiated", target_text=TARGET
    )
    assert summary["actionable_model_target_detected"] is None
    assert summary["negotiated_model_target_flagged"] is True


def test_comparison_aggregates_paired_runs_without_confusing_unmeasured_with_zero():
    comparison = build_comparison([_run("single"), _run("dual")])
    assert comparison["aggregate"]["paired_cases"] == 1
    assert comparison["aggregate"]["single"]["actionable_model_target_detected"] == 1
    assert comparison["aggregate"]["dual"]["actionable_cases"] == 1
    assert comparison["aggregate"]["single"]["negotiated_cases"] == 0
    assert comparison["aggregate"]["valid_pairs"] == 1
    assert comparison["statistical_significance"] == "not_evaluated"


def test_failed_pair_is_not_counted_as_a_missed_risk():
    single = _run("single")
    dual = _run("dual")
    single["summary"].update({
        "valid_for_comparison": False,
        "execution_complete": False,
        "all_model_calls_successful": False,
        "actionable_model_target_detected": False,
    })
    comparison = build_comparison([single, dual])
    assert comparison["aggregate"]["paired_cases"] == 1
    assert comparison["aggregate"]["valid_pairs"] == 0
    assert comparison["aggregate"]["excluded_pairs"] == ["F2-006"]
    assert comparison["aggregate"]["single"]["actionable_cases"] == 0
