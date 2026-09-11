"""生成一次性 50+2 高拟真合成冻结合同集。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .content import build_contract
from .models import ContractCase, load_cases, load_profile
from .renderers import (
    ScanProfile,
    render_docx,
    render_mixed_pdf,
    render_scanned_pdf,
    render_text_pdf,
)


DATASET_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class GenerationResult:
    root: Path
    valid_count: int
    invalid_count: int
    supplemental_count: int
    manifest: dict[str, Any]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_title(title: str) -> str:
    value = re.sub(r'[<>:"/\\|?*]', "-", title).strip(" .")
    return value[:42] or "contract"


def case_filename(case: ContractCase) -> str:
    extension = ".docx" if case.format == "docx" else ".pdf"
    return f"{case.case_id}-{_safe_title(case.title)}{extension}"


def _scan_profile(case: ContractCase) -> ScanProfile:
    index = int(case.case_id[-3:])
    return ScanProfile(
        dpi=(112, 120, 128)[index % 3],
        rotation_degrees=(0.18, 0.28, 0.38)[index % 3],
        brightness=(0.96, 0.98, 1.0)[index % 3],
        contrast=(0.92, 0.96, 0.99)[index % 3],
        jpeg_quality=(76, 82, 86)[index % 3],
        shadow_width=(5, 8, 11)[index % 3],
    )


def _render_case(case: ContractCase, output_path: Path) -> None:
    document = build_contract(case)
    if case.format == "docx":
        render_docx(document, output_path)
    elif case.render_mode == "native":
        render_text_pdf(document, output_path)
    elif case.render_mode == "scanned":
        render_scanned_pdf(document, output_path, profile=_scan_profile(case))
    elif case.render_mode == "mixed":
        render_mixed_pdf(document, output_path, profile=_scan_profile(case))
    else:
        raise ValueError(f"不支持的渲染模式：{case.render_mode}")


def _document_kind(case: ContractCase) -> str:
    if case.format == "docx":
        return "docx"
    if case.format == "scanned_or_mixed_pdf":
        return "scanned_pdf"
    return "pdf"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    content = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    )
    path.write_text(content, encoding="utf-8")


def _file_record(
    root: Path,
    path: Path,
    *,
    case_id: str,
    role: str,
    expected_status: int | str,
    document_kind: str,
) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "document_kind": document_kind,
        "expected_status": expected_status,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def generate_dataset(output_root: Path) -> GenerationResult:
    """生成新冻结目录；目标已存在时拒绝覆盖。"""
    root = Path(output_root).resolve()
    if root.exists():
        raise FileExistsError(f"冻结目录已存在: {root}")

    profile_path = DATASET_ROOT / "corpus-profile.json"
    cases_path = DATASET_ROOT / "cases.json"
    profile = load_profile(profile_path)
    cases = load_cases(cases_path)
    if len(cases) != profile.valid_count:
        raise ValueError("案例数量与冻结画像不一致")

    valid_root = root / "contracts" / "valid"
    invalid_root = root / "contracts" / "invalid"
    supplemental_root = root / "supplemental"
    valid_root.mkdir(parents=True)
    invalid_root.mkdir(parents=True)
    supplemental_root.mkdir(parents=True)

    files: list[dict[str, Any]] = []
    batch_samples: list[dict[str, Any]] = []
    truth_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for case in cases:
        output_path = valid_root / case_filename(case)
        _render_case(case, output_path)
        record = _file_record(
            root,
            output_path,
            case_id=case.case_id,
            role="valid",
            expected_status="done",
            document_kind=_document_kind(case),
        )
        files.append(record)
        batch_samples.append(
            {
                "path": record["path"],
                "role": "valid",
                "sha256": record["sha256"],
                "expected_status": "done",
            }
        )
        truth_row = {
            "case_id": case.case_id,
            "file": record["path"],
            "contract_type": case.contract_type,
            "document_kind": _document_kind(case),
            "gold": dict(case.truth),
            "evidence_level": "construction_truth_only",
            "version": profile.version,
        }
        truth_rows.append(truth_row)
        review_rows.append(
            {
                "case_id": case.case_id,
                "file": record["path"],
                "contract_type": case.contract_type,
                "document_kind": _document_kind(case),
                "gold": dict(case.truth),
                "reviewers": [],
                "review_status": "pending_human_review",
                "review_notes": [],
                "version": profile.version,
            }
        )

    invalid_specs = (
        ("FX-051", "FX-051-empty-corrupt.pdf", b""),
        ("FX-052", "FX-052-spoofed.pdf.exe", b"MZ\x90\x00synthetic-spoofed-extension"),
    )
    for case_id, filename, payload in invalid_specs:
        path = invalid_root / filename
        path.write_bytes(payload)
        record = _file_record(
            root,
            path,
            case_id=case_id,
            role="invalid",
            expected_status=400,
            document_kind="invalid",
        )
        files.append(record)
        batch_samples.append(
            {
                "path": record["path"],
                "role": "invalid",
                "sha256": record["sha256"],
                "expected_status": 400,
            }
        )

    supplemental_path = supplemental_root / "SX-001-nonempty-corrupt.pdf"
    supplemental_path.write_bytes(
        b"%PDF-1.7\n% synthetic nonempty corrupt input without xref\n"
    )
    files.append(
        _file_record(
            root,
            supplemental_path,
            case_id="SX-001",
            role="supplemental",
            expected_status="async_failed",
            document_kind="invalid_pdf",
        )
    )

    manifest = {
        "schema_version": "1.0",
        "dataset_version": profile.version,
        "evidence_level": "construction_truth_only",
        "formal_gold": False,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "profile_sha256": sha256_file(profile_path),
        "cases_sha256": sha256_file(cases_path),
        "files": files,
    }
    batch_manifest = {
        "schema_version": "1.0",
        "contract_type": "综合业务合同冻结集",
        "dimensions": ["合同要素", "履约风险", "格式兼容", "OCR"],
        "samples": batch_samples,
    }
    _write_jsonl(root / "construction-truth.jsonl", truth_rows)
    _write_jsonl(root / "gold-review-template.jsonl", review_rows)
    _write_json(root / "batch-manifest.json", batch_manifest)
    _write_json(root / "freeze-manifest.json", manifest)
    (root / "README.md").write_text(
        (DATASET_ROOT / "README.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return GenerationResult(
        root=root,
        valid_count=profile.valid_count,
        invalid_count=profile.invalid_count,
        supplemental_count=1,
        manifest=manifest,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = generate_dataset(args.output)
    print(
        f"valid={result.valid_count} invalid={result.invalid_count} "
        f"supplemental={result.supplemental_count} root={result.root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
