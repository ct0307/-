"""对 50+2 冻结合同集执行不落库的导入可靠性验收。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.config import settings
from app.services.imports.classifier import TypeSuggestion, classify_contract_type
from app.services.imports.errors import parse_failure
from app.services.imports.file_validation import FileValidationError, validate_upload
from app.services.parser.elements import (
    ELEMENT_FIELDS,
    ElementEvidence,
    ElementResult,
    extract_element_result,
)
from app.services.parser.extractor import extract_uploaded_document
from evaluation.datasets.frozen_contracts_v3.cases import load_cases
from evaluation.elements import evaluate_dataset


DEFAULT_CONTRACT_TYPES = (
    "软件开发外包合同", "技术服务合同", "采购合同", "销售合同", "劳动合同",
    "租赁合同", "保密协议", "合作协议", "服务协议", "框架协议",
    "技术开发合同", "合作合同", "服务合同", "劳务合同",
)
_CASE_ID = re.compile(r"^(?P<case_id>(?:F|FX)3-\d{3})")
_VALID_TERMINAL_STATUSES = {"parsed", "review_required"}
_MIN_ELEMENT_F1 = 0.80
_MIN_HIGH_CONFIDENCE_PRECISION = 0.95


@dataclass(frozen=True)
class IngestionReport:
    passed: bool
    failures: tuple[str, ...]
    metrics: Mapping[str, Any]
    valid_results: tuple[Mapping[str, Any], ...] = ()
    invalid_results: tuple[Mapping[str, Any], ...] = ()
    supplemental_results: tuple[Mapping[str, Any], ...] = ()
    classification: Mapping[str, Any] | None = None
    elements: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "truth_basis": "construction_truth_only",
            "formal_legal_gold": False,
            "passed": self.passed,
            "failures": list(self.failures),
            "metrics": dict(self.metrics),
            "classification": dict(self.classification or {}),
            "elements": dict(self.elements or {}),
            "valid_results": [dict(item) for item in self.valid_results],
            "invalid_results": [dict(item) for item in self.invalid_results],
            "supplemental_results": [dict(item) for item in self.supplemental_results],
        }


def sanitize_element_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """保留指标和错误位置，移除金标准及预测原值。"""
    safe: dict[str, Any] = {
        key: report[key]
        for key in ("dataset_sha256", "sample_count", "overall", "by_field")
        if key in report
    }
    for key in ("by_contract_type", "by_document_kind"):
        if key in report:
            safe[key] = report[key]
    safe["mismatches"] = [
        {"case_id": item.get("case_id"), "field": item.get("field")}
        for item in report.get("errors", [])
        if isinstance(item, Mapping)
    ]
    return safe


def evaluate_ingestion(
    *,
    valid_results: Sequence[Mapping[str, Any]],
    invalid_results: Sequence[Mapping[str, Any]],
    classification: Mapping[str, Any],
    element_report: Mapping[str, Any],
    supplemental_results: Sequence[Mapping[str, Any]] = (),
    missing_evidence_count: int = 0,
) -> IngestionReport:
    failures: list[str] = []
    if any(item.get("status") not in _VALID_TERMINAL_STATUSES for item in valid_results):
        failures.append("valid_contract_terminal_status")
    if any(item.get("error_code") == "OCR_UNAVAILABLE" for item in valid_results):
        failures.append("ocr_unavailable")
    if any(
        item.get("status") != "failed" or item.get("contract_id") is not None
        for item in invalid_results
    ):
        failures.append("invalid_input_rejection")
    if supplemental_results and any(
        item.get("status") != "failed" or item.get("contract_id") is not None
        for item in supplemental_results
    ):
        failures.append("supplemental_corrupt_rejection")
    if int(classification.get("high_confidence_false_ready", 0)) > 0:
        failures.append("classification_false_ready")
    if (
        not classification.get("auto_ready_enabled", False)
        and int(classification.get("auto_ready_count", 0)) > 0
    ):
        failures.append("classification_auto_ready_disabled")
    if (
        classification.get("auto_ready_enabled", False)
        and float(classification.get("high_confidence_precision", 0.0))
        < _MIN_HIGH_CONFIDENCE_PRECISION
    ):
        failures.append("classification_high_confidence_precision")

    overall_f1 = float(element_report.get("overall", {}).get("f1", 0.0))
    if overall_f1 < _MIN_ELEMENT_F1:
        failures.append("element_macro_f1")
    if any(
        float(metrics.get("f1", 0.0)) <= 0.0
        for metrics in element_report.get("by_field", {}).values()
    ):
        failures.append("element_zero_field")
    if missing_evidence_count > 0:
        failures.append("element_evidence")
    missing_pdf_page_count = 0
    for item in valid_results:
        missing_pages = set(item.get("missing_pages") or ())
        total_pages = item.get("total_pages")
        covered_pages = item.get("covered_pages")
        if item.get("document_kind") == "pdf" and (
            not isinstance(total_pages, int) or total_pages <= 0 or covered_pages is None
        ):
            missing_pdf_page_count += 1
            continue
        if isinstance(total_pages, int) and total_pages > 0 and covered_pages is not None:
            missing_pages.update(set(range(1, total_pages + 1)) - set(covered_pages))
        missing_pdf_page_count += len(missing_pages)
    if missing_pdf_page_count:
        failures.append("pdf_page_coverage")

    safe_elements = sanitize_element_report(element_report)
    metrics = {
        "valid_count": len(valid_results),
        "invalid_count": len(invalid_results),
        "supplemental_count": len(supplemental_results),
        "ocr_unavailable_count": sum(
            item.get("error_code") == "OCR_UNAVAILABLE" for item in valid_results
        ),
        "missing_evidence_count": missing_evidence_count,
        "missing_pdf_page_count": missing_pdf_page_count,
        "element_macro_f1": overall_f1,
    }
    return IngestionReport(
        passed=not failures,
        failures=tuple(failures),
        metrics=metrics,
        classification=classification,
        elements=safe_elements,
    )


def _contract_directories(root: Path) -> tuple[Path, Path]:
    layouts = (
        (root / "有效合同", root / "无效测试文件"),
        (root / "contracts" / "valid", root / "contracts" / "invalid"),
    )
    for valid_dir, invalid_dir in layouts:
        if valid_dir.is_dir() and invalid_dir.is_dir():
            return valid_dir, invalid_dir
    raise ValueError("合同集必须包含‘有效合同/无效测试文件’目录或 contracts/valid、contracts/invalid")


def _discover_contract_set(root: Path) -> tuple[list[Path], list[Path]]:
    valid_dir, invalid_dir = _contract_directories(root)
    valid_files = sorted(path for path in valid_dir.iterdir() if path.is_file())
    invalid_files = sorted(path for path in invalid_dir.iterdir() if path.is_file())
    if len(valid_files) != 50 or len(invalid_files) != 2:
        raise ValueError(
            f"合同集必须是 50 份有效合同和 2 份无效输入，当前为 {len(valid_files)}+{len(invalid_files)}"
        )
    expected_ids = {case.case_id for case in load_cases()}
    actual_ids = {_case_id(path) for path in valid_files}
    if actual_ids != expected_ids:
        missing = sorted(expected_ids - actual_ids)
        extra = sorted(actual_ids - expected_ids)
        raise ValueError(f"有效合同 case_id 不匹配，缺少={missing}，额外={extra}")
    return valid_files, invalid_files


def _case_id(path: Path) -> str:
    match = _CASE_ID.match(path.name)
    if not match:
        raise ValueError(f"文件名缺少冻结 case_id：{path.name}")
    return match.group("case_id")


def _dataset_sha256(root: Path, files: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _expected_type(case: Any) -> str:
    if case.scenario == "procurement":
        return "采购合同"
    if case.scenario == "leasing":
        return "租赁合同"
    if case.scenario == "framework":
        return "框架协议"
    if case.scenario == "construction":
        return "服务合同"
    if case.scenario == "workforce":
        return "劳务合同" if "劳务" in case.contract_type else "服务合同"
    if case.scenario == "data_ip":
        return "技术开发合同" if "研发" in case.contract_type else "合作协议"
    if case.scenario == "operations":
        return "服务协议" if "协议" in case.contract_type else "服务合同"
    if case.scenario == "technology":
        return "技术服务合同" if any(
            marker in case.contract_type for marker in ("服务", "运维", "托管", "订阅", "集成")
        ) else "技术开发合同"
    return ""


def _evidence_positions(
    result: ElementResult,
    *,
    require_page: bool = False,
) -> tuple[dict[str, Any], int]:
    fields: dict[str, Any] = {}
    missing = 0
    for field in ELEMENT_FIELDS:
        value = result.values.get(field)
        present = bool(value) if not isinstance(value, list) else any(value)
        raw_evidence = result.evidence.get(field)
        evidence = raw_evidence if isinstance(raw_evidence, list) else [raw_evidence] if raw_evidence else []
        valid_evidence = [
            item for item in evidence
            if isinstance(item, ElementEvidence)
            and 0 <= item.start < item.end <= len(result.source_text)
            and (not require_page or isinstance(item.page, int) and item.page > 0)
        ]
        positions = [
            {
                "page": item.page,
                "start": item.start,
                "end": item.end,
                "confidence": item.confidence,
                "source": item.source,
                "validation": item.validation,
            }
            for item in valid_evidence
        ]
        if present and not positions:
            missing += 1
        fields[field] = {"present": present, "evidence": positions}
    return fields, missing


def _rejected_upload(case_id: str, filename: str, content: bytes) -> dict[str, Any]:
    try:
        validate_upload(filename, content)
    except FileValidationError as exc:
        return {"case_id": case_id, "status": "failed", "contract_id": None, "error_code": exc.code}
    except Exception:
        return {
            "case_id": case_id,
            "status": "failed",
            "contract_id": None,
            "error_code": "VALIDATION_INTERNAL_ERROR",
        }
    return {"case_id": case_id, "status": "accepted", "contract_id": case_id, "error_code": None}


def _gold_record(case: Any, path: Path) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "file": path.name,
        "contract_type": case.contract_type,
        "document_kind": "docx" if path.suffix.lower() == ".docx" else "pdf",
        "reviewers": ["construction-case-definition", "rendered-document-validation"],
        "review_status": "agreed",
        "version": "3.0.0-construction-baseline",
        "gold": dict(case.truth.evaluation_projection(case.parties)),
    }


def _classification_summary(rows: Sequence[Mapping[str, Any]], auto_ready_enabled: bool) -> dict[str, Any]:
    confusion: dict[str, dict[str, int]] = {}
    high_confidence = [row for row in rows if row["confidence"] >= settings.CONTRACT_TYPE_READY_THRESHOLD]
    for row in rows:
        expected = str(row["expected"])
        predicted = str(row["predicted"] or "unclassified")
        confusion.setdefault(expected, {})[predicted] = confusion.setdefault(expected, {}).get(predicted, 0) + 1
    correct = sum(row["predicted"] == row["expected"] for row in high_confidence)
    auto_ready = [row for row in rows if row["auto_ready"]]
    false_ready = [row for row in auto_ready if row["predicted"] != row["expected"]]
    return {
        "auto_ready_enabled": auto_ready_enabled,
        "auto_ready_count": len(auto_ready),
        "high_confidence_count": len(high_confidence),
        "high_confidence_correct": correct,
        "high_confidence_precision": correct / len(high_confidence) if high_confidence else 1.0,
        "high_confidence_false_ready": len(false_ready),
        "false_ready_case_ids": [row["case_id"] for row in false_ready],
        "confusion_matrix": confusion,
    }


def evaluate_contract_set(
    dataset: Path,
    *,
    available_types: Sequence[str] = DEFAULT_CONTRACT_TYPES,
    auto_ready_enabled: bool | None = None,
) -> IngestionReport:
    root = dataset.resolve()
    valid_files, invalid_files = _discover_contract_set(root)
    cases = {case.case_id: case for case in load_cases()}
    enabled = settings.CONTRACT_TYPE_AUTO_READY_ENABLED if auto_ready_enabled is None else auto_ready_enabled
    valid_results: list[dict[str, Any]] = []
    predictions: dict[str, Mapping[str, Any]] = {}
    gold_records: list[dict[str, Any]] = []
    classification_rows: list[dict[str, Any]] = []
    missing_evidence_count = 0

    for path in valid_files:
        case_id = _case_id(path)
        case = cases[case_id]
        gold_records.append(_gold_record(case, path))
        try:
            validate_upload(path.name, path.read_bytes())
            parsed = extract_uploaded_document(path.name, path.read_bytes())
            elements = extract_element_result(parsed)
            predictions[case_id] = elements.values
            evidence, missing = _evidence_positions(
                elements,
                require_page=path.suffix.lower() == ".pdf",
            )
            missing_evidence_count += missing
            suggestion: TypeSuggestion = classify_contract_type(
                filename=path.name,
                text=parsed.text,
                available_types=list(available_types),
            )
            expected = _expected_type(case)
            auto_ready = bool(
                enabled
                and not parsed.requires_review
                and not elements.review_fields
                and suggestion.auto_ready_eligible
                and suggestion.suggested_type
                and suggestion.confidence >= settings.CONTRACT_TYPE_READY_THRESHOLD
            )
            classification_rows.append({
                "case_id": case_id,
                "expected": expected,
                "predicted": suggestion.suggested_type,
                "confidence": suggestion.confidence,
                "auto_ready": auto_ready,
            })
            requires_review = parsed.requires_review or bool(elements.review_fields)
            valid_results.append({
                "case_id": case_id,
                "status": "review_required" if requires_review else "parsed",
                "error_code": None,
                "document_kind": path.suffix.lower().lstrip("."),
                "parse_source": parsed.source,
                "ocr_confidence": parsed.ocr_confidence,
                "total_pages": parsed.total_pages,
                "missing_pages": list(parsed.missing_pages),
                "covered_pages": sorted({
                    block.anchor.page_number for block in parsed.blocks
                    if block.anchor.page_number is not None
                }),
                "requires_review": requires_review,
                "classification": {
                    "expected": expected,
                    "predicted": suggestion.suggested_type,
                    "confidence": suggestion.confidence,
                    "auto_ready": auto_ready,
                },
                "elements": evidence,
            })
        except Exception as exc:
            error_code = exc.code if isinstance(exc, FileValidationError) else parse_failure(exc).code
            predictions[case_id] = {}
            valid_results.append({
                "case_id": case_id,
                "status": "failed",
                "error_code": error_code,
                "document_kind": path.suffix.lower().lstrip("."),
                "parse_source": None,
                "ocr_confidence": None,
                "total_pages": None,
                "missing_pages": [],
                "covered_pages": [],
                "requires_review": False,
                "classification": {},
                "elements": {},
            })

    invalid_results = [
        _rejected_upload(_case_id(path), path.name, path.read_bytes())
        for path in invalid_files
    ]
    supplemental_results = [
        _rejected_upload("SX3-PDF", "memory-corrupt.pdf", b"%PDF-1.7\ncorrupt without xref"),
        _rejected_upload("SX3-DOCX", "memory-corrupt.docx", b"PK\x03\x04corrupt archive"),
    ]
    raw_element_report = evaluate_dataset(gold_records, predictions)
    classification = _classification_summary(classification_rows, enabled)
    evaluated = evaluate_ingestion(
        valid_results=valid_results,
        invalid_results=invalid_results,
        supplemental_results=supplemental_results,
        classification=classification,
        element_report=raw_element_report,
        missing_evidence_count=missing_evidence_count,
    )
    metrics = {
        **evaluated.metrics,
        "dataset_sha256": _dataset_sha256(root, [*valid_files, *invalid_files]),
        "scanned_case_count": sum(case.render_mode == "scanned" for case in cases.values()),
    }
    return IngestionReport(
        passed=evaluated.passed,
        failures=evaluated.failures,
        metrics=metrics,
        valid_results=tuple(valid_results),
        invalid_results=tuple(invalid_results),
        supplemental_results=tuple(supplemental_results),
        classification=classification,
        elements=evaluated.elements,
    )


def _write_report(path: Path, report: IngestionReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = evaluate_contract_set(args.dataset)
        _write_report(args.output, report)
    except (OSError, ValueError) as exc:
        print(f"合同集质量门禁环境错误：{exc}")
        return 2
    print(
        f"合同集质量门禁：{'通过' if report.passed else '失败'}，"
        f"有效={report.metrics['valid_count']}，无效={report.metrics['invalid_count']}，"
        f"六要素F1={report.metrics['element_macro_f1']:.4f}"
    )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
