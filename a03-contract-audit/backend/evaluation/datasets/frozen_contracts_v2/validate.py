"""验证 v2 冻结文件、语义证据和 OOXML 结构。"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile

import fitz
from docx import Document

from .cases import load_cases
from .content import build_contract
from .generate import sha256_file


def _docx_text(path: Path) -> str:
    word = Document(path)
    return "\n".join([*(item.text for item in word.paragraphs), *(cell.text for table in word.tables for row in table.rows for cell in row.cells)])


def validate_dataset(dataset_root: Path) -> dict[str, Any]:
    root = Path(dataset_root).resolve()
    manifest_path = root / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    reasons: list[str] = []
    hashes = []
    file_by_case = {}
    for row in manifest.get("files", []):
        path = (root / row["path"]).resolve()
        if not path.is_file():
            reasons.append(f"文件不存在: {row['path']}")
            continue
        actual = sha256_file(path)
        hashes.append(actual)
        if actual != row["sha256"]:
            reasons.append(f"SHA-256 不匹配: {row['path']}")
        if path.stat().st_size != row["bytes"]:
            reasons.append(f"字节数不匹配: {row['path']}")
        if row["role"] == "valid":
            file_by_case[row["case_id"]] = path
    if len(manifest.get("files", [])) != 53:
        reasons.append("冻结清单必须包含 53 个文件")
    if len(hashes) != len(set(hashes)):
        reasons.append("冻结文件哈希必须唯一")

    extracted_checks = 0
    ocr_required_cases: list[str] = []
    for case in load_cases():
        path = file_by_case.get(case.case_id)
        if path is None:
            reasons.append(f"缺少有效合同: {case.case_id}")
            continue
        if case.format == "docx":
            text = _docx_text(path)
            extracted_checks += 1
            if case.revision_set:
                with ZipFile(path) as archive:
                    document_xml = archive.read("word/document.xml")
                    settings_xml = archive.read("word/settings.xml")
                    if not all(token in document_xml for token in (b"w:ins", b"w:del", b"w:commentRangeStart")) or b"w:trackRevisions" not in settings_xml or "word/comments.xml" not in archive.namelist():
                        reasons.append(f"DOCX 修订结构不完整: {case.case_id}")
        else:
            with fitz.open(path) as pdf:
                texts = [page.get_text().strip() for page in pdf]
                images = [bool(page.get_images(full=True)) for page in pdf]
                if pdf.page_count != case.target_pages:
                    reasons.append(f"PDF 页数不符: {case.case_id}")
                if case.render_mode == "native" and not all(texts):
                    reasons.append(f"文本 PDF 存在空文本页: {case.case_id}")
                if case.render_mode == "scanned" and (any(texts) or not all(images)):
                    reasons.append(f"扫描 PDF 结构不符: {case.case_id}")
                if case.render_mode == "mixed" and not (any(texts) and not all(texts)):
                    reasons.append(f"混合 PDF 结构不符: {case.case_id}")
                text = "\n".join(texts)
                if case.render_mode == "native":
                    extracted_checks += 1
                else:
                    ocr_required_cases.append(case.case_id)
        if case.format == "docx" or case.render_mode == "native":
            for risk in case.risk_clauses:
                if risk.text not in text:
                    reasons.append(f"风险原文未落盘: {case.case_id}/{risk.clause_id}")
            for conflict in case.conflicts:
                if conflict.text_a not in text or conflict.text_b not in text:
                    reasons.append(f"冲突双值未落盘: {case.case_id}")

    canonical = {case.case_id: re.sub(r"[\W_]+", "", build_contract(case).plain_text.casefold()) for case in load_cases()}
    similarity, pair = max((SequenceMatcher(None, canonical[a], canonical[b], autojunk=True).ratio(), (a, b)) for a, b in combinations(canonical, 2))
    if similarity >= 0.85:
        reasons.append(f"正文相似度过高: {pair[0]}/{pair[1]}={similarity:.4f}")
    report = {
        "schema_version": "1.0",
        "status": "passed" if not reasons else "failed",
        "evidence_level": "construction_truth_only",
        "formal_gold": False,
        "checks": {"manifest_file_count": len(manifest.get("files", [])), "unique_hash_count": len(set(hashes)), "extractable_semantic_checks": extracted_checks, "ocr_required_semantic_cases": ocr_required_cases, "maximum_similarity": similarity, "maximum_similarity_pair": list(pair)},
        "reasons": reasons,
        "manifest_sha256": sha256_file(manifest_path),
    }
    (root / "validation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if reasons:
        raise ValueError("冻结集验证失败: " + "; ".join(reasons))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = validate_dataset(args.dataset)
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
