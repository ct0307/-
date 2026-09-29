from datetime import date


def test_operational_metrics_deduplicate_contracts_and_keep_uncertainty():
    from app.services.report.operations import operational_summary
    snapshot = {"contracts": [
        {"id": 1, "department": "采购", "risk_high": 2, "risk_total": 2, "amount": "100万元", "job_status": "review_required"},
        {"id": 2, "department": "采购", "risk_high": 0, "risk_total": 0, "amount": "单价100元", "job_status": "done"},
    ], "risks": [{"id": 1, "contract_id": 1, "level": "high", "category": "付款", "original_text": "同一条款", "review_status": "pending", "agent": "legal"},
                 {"id": 2, "contract_id": 1, "level": "high", "category": "付款", "original_text": "同一条款", "review_status": "pending", "agent": "finance"}],
        "rectifications": [{"id": 1, "risk_id": 1, "due": "2026-09-28", "status": "待复核", "owner": "legal"},
                           {"id": 2, "risk_id": 2, "due": "未知", "status": "处理中", "owner": "finance"}]}
    result = operational_summary(snapshot, today=date(2026, 9, 29))
    assert result["high_risk_contracts"] == 1
    assert result["pending_risk_count"] == 2
    assert result["departments"][0]["contract_count"] == 2
    assert result["departments"][0]["high_risk_rate"] == 0.5
    assert result["overdue_count"] == 1
    assert result["unknown_due_count"] == 1
    assert result["historical_state"] == "INSUFFICIENT_HISTORY"
    assert result["amount_state"] == "UNVERIFIED"
    assert result["departments"][0]["contract_ids"] == [1, 2]
