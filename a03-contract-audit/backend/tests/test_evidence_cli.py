"""支持关系评测 CLI 的证据流契约。"""

import json

from evaluation.cli import EXIT_OK, main


def _gold() -> dict:
    return {
        "case_id": "case-1",
        "file": "case-1.pdf",
        "contract_type": "采购合同",
        "document_kind": "pdf",
        "reviewers": ["reviewer-a", "reviewer-b"],
        "review_status": "agreed",
        "version": "v1",
        "gold": {
            "party_a": "甲公司",
            "party_b": "乙公司",
            "subject": "设备采购",
            "amount": "100万元",
            "duration": "12个月",
            "payment_terms": ["首付款"],
        },
        "evidence": [
            {"risk_key": "risk-1", "support_relation_status": "supported"},
        ],
    }


def test_evidence_cli_writes_reportable_run(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    prediction_path = tmp_path / "predictions.jsonl"
    gold_path.write_text(json.dumps(_gold(), ensure_ascii=False) + "\n", encoding="utf-8")
    prediction_path.write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "prediction": {
                    "evidence": [
                        {"risk_key": "risk-1", "support_relation_status": "supported"}
                    ]
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    args = [
        "evidence",
        "--gold",
        str(gold_path),
        "--predictions",
        str(prediction_path),
        "--runs-root",
        str(tmp_path / "runs"),
        "--run-id",
        "evidence-pass",
        "--min-f1",
        "0.3",
    ]
    assert main(args) == EXIT_OK

    run_dir = tmp_path / "runs" / "evidence-pass"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "passed"
    assert manifest["modules"] == {"evidence": "passed"}
    assert (run_dir / "evidence.jsonl").is_file()
    assert main(["report", "--run-dir", str(run_dir)]) == EXIT_OK
    assert "依据支持关系评测" in (run_dir / "report.md").read_text(encoding="utf-8")
