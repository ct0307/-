"""合同集导入可靠性门禁只报告指标和证据位置。"""

import json

import pytest

from app.services.imports.classifier import TypeSuggestion
from app.services.imports.file_validation import FileValidationError, ValidatedUpload
from app.services.parser.elements import ElementResult
from app.services.parser.extractor import DocumentBlock, DocumentParseResult, SourceAnchor
from evaluation.datasets.frozen_contracts_v3.cases import load_cases
from evaluation.ingestion_reliability import (
    evaluate_contract_set,
    evaluate_ingestion,
    sanitize_element_report,
)


def passing_element_report():
    return {
        "overall": {"f1": 0.80},
        "by_field": {
            field: {"f1": 0.10}
            for field in (
                "party_a", "party_b", "subject", "amount", "duration", "payment_terms"
            )
        },
        "errors": [],
    }


def test_gate_rejects_technical_failures_false_ready_and_weak_elements():
    report = evaluate_ingestion(
        valid_results=[{"status": "failed", "error_code": "OCR_UNAVAILABLE"}],
        invalid_results=[{"status": "failed", "contract_id": None}],
        classification={"high_confidence_false_ready": 1},
        element_report={
            "overall": {"f1": 0.79},
            "by_field": {"subject": {"f1": 0.0}},
        },
    )

    assert report.passed is False
    assert set(report.failures) == {
        "valid_contract_terminal_status",
        "ocr_unavailable",
        "classification_false_ready",
        "element_macro_f1",
        "element_zero_field",
    }


def test_gate_accepts_terminal_valid_files_and_rejected_invalid_files():
    report = evaluate_ingestion(
        valid_results=[
            {"status": "parsed", "error_code": None},
            {"status": "review_required", "error_code": None},
        ],
        invalid_results=[{"status": "failed", "contract_id": None}],
        supplemental_results=[{"status": "failed", "contract_id": None}],
        classification={
            "high_confidence_false_ready": 0,
            "auto_ready_enabled": False,
            "auto_ready_count": 0,
        },
        element_report=passing_element_report(),
        missing_evidence_count=0,
    )

    assert report.passed is True
    assert report.failures == ()


def test_gate_rejects_pdf_page_coverage_even_if_terminal_status_is_parsed():
    report = evaluate_ingestion(
        valid_results=[{
            "case_id": "F3-044", "status": "parsed", "error_code": None,
            "total_pages": 5, "missing_pages": [2, 3, 5],
        }],
        invalid_results=[{"status": "failed", "contract_id": None}],
        classification={"auto_ready_enabled": False, "auto_ready_count": 0},
        element_report=passing_element_report(),
    )

    assert report.passed is False
    assert "pdf_page_coverage" in report.failures
    assert report.metrics["missing_pdf_page_count"] == 3


def test_gate_cross_checks_page_anchors_without_relying_on_missing_pages_flag():
    report = evaluate_ingestion(
        valid_results=[{
            "status": "parsed", "error_code": None, "total_pages": 3,
            "missing_pages": [], "covered_pages": [1, 3],
        }],
        invalid_results=[],
        classification={"auto_ready_enabled": False, "auto_ready_count": 0},
        element_report=passing_element_report(),
    )

    assert "pdf_page_coverage" in report.failures
    assert report.metrics["missing_pdf_page_count"] == 1


def test_gate_rejects_pdf_without_page_coverage_metadata():
    report = evaluate_ingestion(
        valid_results=[{
            "status": "parsed", "error_code": None, "document_kind": "pdf",
            "total_pages": None, "missing_pages": [], "covered_pages": [],
        }],
        invalid_results=[],
        classification={"auto_ready_enabled": False, "auto_ready_count": 0},
        element_report=passing_element_report(),
    )

    assert report.passed is False
    assert "pdf_page_coverage" in report.failures
    assert report.metrics["missing_pdf_page_count"] == 1


def test_gate_rejects_invalid_contract_creation_and_missing_evidence():
    report = evaluate_ingestion(
        valid_results=[{"status": "parsed", "error_code": None}],
        invalid_results=[{"status": "failed", "contract_id": 9}],
        supplemental_results=[{"status": "parsed", "contract_id": 10}],
        classification={"high_confidence_false_ready": 0},
        element_report=passing_element_report(),
        missing_evidence_count=2,
    )

    assert set(report.failures) == {
        "invalid_input_rejection",
        "supplemental_corrupt_rejection",
        "element_evidence",
    }


def test_public_element_report_omits_contract_values():
    report = sanitize_element_report({
        "dataset_sha256": "a" * 64,
        "sample_count": 1,
        "overall": {"f1": 0.8, "precision": 0.8, "recall": 0.8},
        "by_field": {"party_a": {"f1": 0.5}},
        "errors": [{
            "case_id": "F3-001",
            "field": "party_a",
            "gold": "甲公司",
            "predicted": "乙公司",
        }],
        "cases": [{"case_id": "F3-001", "field_metrics": {}}],
    })

    serialized = json.dumps(report, ensure_ascii=False)
    assert "甲公司" not in serialized
    assert "乙公司" not in serialized
    assert report["mismatches"] == [{"case_id": "F3-001", "field": "party_a"}]


def test_contract_set_runner_requires_exact_50_plus_2_layout(tmp_path):
    (tmp_path / "有效合同").mkdir()
    (tmp_path / "无效测试文件").mkdir()

    with pytest.raises(ValueError, match="50"):
        evaluate_contract_set(tmp_path)


def test_contract_set_runner_evaluates_without_serializing_text(monkeypatch, tmp_path):
    valid_dir = tmp_path / "有效合同"
    invalid_dir = tmp_path / "无效测试文件"
    valid_dir.mkdir()
    invalid_dir.mkdir()
    for case in load_cases():
        extension = ".docx" if case.format == "docx" else ".pdf"
        (valid_dir / f"{case.case_id}-sample{extension}").write_bytes(b"valid")
    (invalid_dir / "FX3-051-empty-corrupt.pdf").write_bytes(b"")
    (invalid_dir / "FX3-052-spoofed.pdf.exe").write_bytes(b"invalid")

    import evaluation.ingestion_reliability as module

    def fake_validate(filename, _content):
        if filename.startswith("F3-"):
            return ValidatedUpload(extension=".pdf")
        raise FileValidationError("PDF_CORRUPT")

    def fake_extract(path):
        case_id = path.split("F3-")[1][:3]
        text = f"F3-{case_id} 合同原文"
        return DocumentParseResult(
            text=text,
            source="native",
            total_pages=1,
            blocks=(DocumentBlock(
                "page-1", "page_text", text, SourceAnchor(page_number=1),
            ),),
        )

    monkeypatch.setattr(module, "validate_upload", fake_validate)
    monkeypatch.setattr(
        module,
        "extract_uploaded_document",
        lambda filename, _content: fake_extract(filename),
    )
    monkeypatch.setattr(
        module,
        "extract_element_result",
        lambda parsed: ElementResult(
            values={field: None for field in passing_element_report()["by_field"]},
            evidence={},
            review_fields=(),
            source_text=parsed.text,
        ),
    )
    monkeypatch.setattr(
        module,
        "classify_contract_type",
        lambda **kwargs: TypeSuggestion("", 0.0, []),
    )
    monkeypatch.setattr(module, "evaluate_dataset", lambda gold, predictions: passing_element_report())

    report = evaluate_contract_set(tmp_path, available_types=["采购合同"])
    payload = report.to_dict()

    assert report.passed is True
    assert payload["metrics"]["valid_count"] == 50
    assert payload["metrics"]["invalid_count"] == 2
    assert payload["metrics"]["supplemental_count"] == 2
    assert "合同原文" not in json.dumps(payload, ensure_ascii=False)

    def reject_one_valid(filename, content):
        if filename.startswith("F3-001"):
            raise FileValidationError("PDF_CORRUPT")
        return fake_validate(filename, content)

    monkeypatch.setattr(module, "validate_upload", reject_one_valid)
    failed = evaluate_contract_set(tmp_path, available_types=["采购合同"])

    assert failed.valid_results[0]["error_code"] == "PDF_CORRUPT"
