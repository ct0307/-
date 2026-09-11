"""生成并冻结 50+2 高拟真合成合同集 v3。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from . import DATASET_ROOT
from .cases import load_cases
from .content import build_contract
from .renderers import render_docx, render_mixed_pdf, render_scanned_pdf, render_text_pdf


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


def _filename(case) -> str:
    title = re.sub(r'[<>:"/\\|?*]', "-", case.title).strip(" .")[:46]
    suffix = ".docx" if case.format == "docx" else ".pdf"
    return f"{case.case_id}-{title}{suffix}"


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _record(root: Path, path: Path, case_id: str, role: str, expected_status: int | str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "path": path.relative_to(root).as_posix(),
        "role": role,
        "expected_status": expected_status,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def generate_dataset(output_root: Path) -> GenerationResult:
    root = Path(output_root).resolve()
    if root.exists():
        raise FileExistsError(f"冻结目录已存在：{root}")
    valid_root = root / "contracts" / "valid"
    invalid_root = root / "contracts" / "invalid"
    supplemental_root = root / "supplemental"
    valid_root.mkdir(parents=True)
    invalid_root.mkdir(parents=True)
    supplemental_root.mkdir(parents=True)

    files: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    truth_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    for case in load_cases():
        document = build_contract(case)
        path = valid_root / _filename(case)
        if case.format == "docx":
            render_docx(document, path, case=case)
        elif case.render_mode == "native":
            render_text_pdf(document, path)
        elif case.render_mode == "scanned":
            render_scanned_pdf(document, path)
        else:
            render_mixed_pdf(document, path)
        record = _record(root, path, case.case_id, "valid", "done")
        files.append(record)
        samples.append({key: record[key] for key in ("path", "role", "sha256", "expected_status")})
        truth = {
            "case_id": case.case_id,
            "file": record["path"],
            "contract_type": case.contract_type,
            "document_kind": "docx" if case.format == "docx" else "pdf",
            "gold": dict(case.truth.evaluation_projection(case.parties)),
            "risk_level": case.risk_level,
            "evidence_level": "construction_truth_only",
            "version": "3.0.0",
        }
        truth_rows.append(truth)
        review_rows.append({**truth, "reviewers": [], "review_status": "pending_human_review"})

    invalid_specs = (
        ("FX3-051", "FX3-051-empty-corrupt.pdf", b""),
        ("FX3-052", "FX3-052-spoofed.pdf.exe", b"MZ\x90\x00synthetic-spoofed-extension-v3"),
    )
    for case_id, filename, payload in invalid_specs:
        path = invalid_root / filename
        path.write_bytes(payload)
        record = _record(root, path, case_id, "invalid", 400)
        files.append(record)
        samples.append({key: record[key] for key in ("path", "role", "sha256", "expected_status")})
    supplemental = supplemental_root / "SX3-001-nonempty-corrupt.pdf"
    supplemental.write_bytes(b"%PDF-1.7\n% synthetic corrupt v3 without xref\n")
    files.append(_record(root, supplemental, "SX3-001", "supplemental", "async_failed"))

    v1_root = DATASET_ROOT.parent / "frozen_contracts_v1"
    v2_root = DATASET_ROOT.parent / "frozen_contracts_v2"
    manifest = {
        "schema_version": "1.0",
        "dataset_version": "3.0.0",
        "evidence_level": "construction_truth_only",
        "formal_gold": False,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "content_generation": "explicit_case_facts_and_natural_pagination",
        "v1_cases_sha256": sha256_file(v1_root / "cases.json"),
        "v1_profile_sha256": sha256_file(v1_root / "corpus-profile.json"),
        "v2_cases_sha256": sha256_file(v2_root / "cases.py"),
        "files": files,
    }
    _write_json(root / "freeze-manifest.json", manifest)
    _write_json(root / "batch-manifest.json", {
        "schema_version": "1.0",
        "contract_type": "综合业务合同冻结集v3",
        "dimensions": ["合同要素", "真实业务条款", "场景附件", "文档风格", "OCR"],
        "samples": samples,
    })
    _write_jsonl(root / "construction-truth.jsonl", truth_rows)
    _write_jsonl(root / "gold-review-template.jsonl", review_rows)
    (root / "README.md").write_text((DATASET_ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    return GenerationResult(root, 50, 2, 1, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = generate_dataset(args.output)
    print(f"valid={result.valid_count} invalid={result.invalid_count} supplemental={result.supplemental_count} root={result.root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
