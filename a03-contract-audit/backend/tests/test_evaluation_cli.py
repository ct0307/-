"""硬指标 CLI 必须使用稳定退出码并生成脱敏证据。"""
import json
from pathlib import Path

from evaluation.cli import EXIT_FAILED, EXIT_INVALID, EXIT_OK, main


def _gold_row() -> dict:
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
            "payment_terms": ["首付款", "验收款"],
        },
    }


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return path


def _invoke_elements(tmp_path: Path, *, gold: dict, prediction: dict, run_id: str) -> int:
    gold_path = _write_jsonl(tmp_path / f"{run_id}-gold.jsonl", [gold])
    predictions_path = _write_jsonl(
        tmp_path / f"{run_id}-predictions.jsonl",
        [{"case_id": gold["case_id"], "prediction": prediction}],
    )
    return main(
        [
            "elements",
            "--gold",
            str(gold_path),
            "--predictions",
            str(predictions_path),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            run_id,
            "--min-f1",
            "0.90",
        ]
    )


def test_elements_command_returns_ok_and_writes_passed_manifest(tmp_path):
    gold = _gold_row()

    code = _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=gold["gold"],
        run_id="elements-pass",
    )
    manifest = json.loads(
        (tmp_path / "runs" / "elements-pass" / "manifest.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_OK
    assert manifest["status"] == "passed"
    assert manifest["modules"] == {"elements": "passed"}
    assert manifest["inputs"]["sample_count"] == 1


def test_elements_command_returns_failed_when_f1_is_below_threshold(tmp_path):
    gold = _gold_row()
    prediction = {**gold["gold"], "party_b": "错误公司"}

    code = _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=prediction,
        run_id="elements-low",
    )
    manifest = json.loads(
        (tmp_path / "runs" / "elements-low" / "manifest.json").read_text(encoding="utf-8")
    )

    assert code == EXIT_FAILED
    assert manifest["status"] == "failed"
    assert manifest["modules"] == {"elements": "failed"}


def test_elements_command_returns_invalid_for_bad_gold_without_creating_run(tmp_path):
    gold = _gold_row()
    gold["document_kind"] = "jpg"

    code = _invoke_elements(
        tmp_path,
        gold=gold,
        prediction=gold["gold"],
        run_id="elements-invalid",
    )

    assert code == EXIT_INVALID
    assert not (tmp_path / "runs" / "elements-invalid").exists()


def test_elements_command_returns_invalid_for_empty_gold(tmp_path):
    gold_path = _write_jsonl(tmp_path / "empty-gold.jsonl", [])
    predictions_path = _write_jsonl(tmp_path / "empty-predictions.jsonl", [])

    code = main(
        [
            "elements",
            "--gold",
            str(gold_path),
            "--predictions",
            str(predictions_path),
            "--runs-root",
            str(tmp_path / "runs"),
            "--run-id",
            "empty-run",
        ]
    )

    assert code == EXIT_INVALID
    assert not (tmp_path / "runs" / "empty-run").exists()


def test_elements_command_refuses_duplicate_run_id(tmp_path):
    gold = _gold_row()
    first = _invoke_elements(tmp_path, gold=gold, prediction=gold["gold"], run_id="same-run")
    second = _invoke_elements(tmp_path, gold=gold, prediction=gold["gold"], run_id="same-run")

    assert first == EXIT_OK
    assert second == EXIT_INVALID


def test_elements_evidence_does_not_store_raw_field_values(tmp_path):
    gold = _gold_row()

    _invoke_elements(tmp_path, gold=gold, prediction=gold["gold"], run_id="redacted-run")
    evidence = (tmp_path / "runs" / "redacted-run" / "elements.jsonl").read_text(
        encoding="utf-8"
    )

    assert "甲公司" not in evidence
    assert "乙公司" not in evidence
    assert "100万元" not in evidence
    assert "case-1" in evidence
