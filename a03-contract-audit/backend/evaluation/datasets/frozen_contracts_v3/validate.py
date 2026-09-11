"""校验 v3 冻结文件和企业合同真实性门槛。"""
from __future__ import annotations

import argparse
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any, Sequence
from zipfile import ZipFile

import fitz
from docx import Document

from .annexes import ANNEX_NAMES, SCENARIO_ALLOWED_ANNEXES
from .cases import load_cases
from .content import ContractDocument, build_contract
from .generate import sha256_file


def _chinese_count(text: str) -> int:
    return sum("\u4e00" <= character <= "\u9fff" for character in text)


def _canonical_body(document: ContractDocument) -> str:
    return re.sub(r"[\W_]+", "", "\n".join(item.as_text() for item in (*document.sections, *document.annexes)).casefold())


def _shingles(text: str, width: int = 12) -> set[str]:
    if len(text) <= width:
        return {text}
    return {text[index:index + width] for index in range(len(text) - width + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 1.0


def validate_contract_documents(cases: Sequence, documents: Sequence[ContractDocument]) -> list[str]:
    reasons: list[str] = []
    if len(cases) != len(documents):
        return [f"案例与文档数量不一致：{len(cases)}/{len(documents)}"]
    for case, document in zip(cases, documents, strict=True):
        count = _chinese_count(document.plain_text)
        if case.length_class == "short" and not 1_200 <= count <= 1_800:
            reasons.append(f"{case.case_id} 正文长度不符合短式合同门槛：{count}")
        elif case.length_class == "long" and count < 6_000:
            reasons.append(f"{case.case_id} 正文长度低于复杂合同门槛：{count}")
        elif case.length_class == "standard" and count < 2_500:
            reasons.append(f"{case.case_id} 正文长度低于普通合同门槛：{count}")
        paragraphs = [paragraph.strip() for section in document.sections for paragraph in section.paragraphs if paragraph.strip()]
        if len(paragraphs) != len(set(paragraphs)):
            reasons.append(f"{case.case_id} 存在完全重复正文段落")
        if len([section for section in document.sections if section.paragraphs]) < 10:
            reasons.append(f"{case.case_id} 实质章节少于10个")
        invalid_annexes = set(case.annex_types) - SCENARIO_ALLOWED_ANNEXES.get(case.scenario, set())
        if invalid_annexes:
            reasons.append(f"{case.case_id} 附件与场景不匹配：{sorted(invalid_annexes)}")
        rendered_types = tuple(
            annex_type for annex_type in case.annex_types
            if any(ANNEX_NAMES[annex_type] in item.heading for item in document.annexes)
        )
        if rendered_types != case.annex_types:
            reasons.append(f"{case.case_id} 正文附件引用不完整")

    bodies = {document.case_id: _shingles(_canonical_body(document)) for document in documents}
    for left, right in combinations(bodies, 2):
        similarity = _jaccard(bodies[left], bodies[right])
        if similarity >= 0.97:
            reasons.append(f"正文相似度过高：{left}/{right}={similarity:.4f}")
    return reasons


def _docx_text(path: Path) -> str:
    word = Document(path)
    return "\n".join([
        *(paragraph.text for paragraph in word.paragraphs),
        *(cell.text for table in word.tables for row in table.rows for cell in row.cells),
    ])


def _maximum_similarity(documents: Sequence[ContractDocument]) -> tuple[float, tuple[str, str] | None]:
    bodies = {document.case_id: _shingles(_canonical_body(document)) for document in documents}
    if len(bodies) < 2:
        return 0.0, None
    similarity, pair = max((_jaccard(bodies[left], bodies[right]), (left, right)) for left, right in combinations(bodies, 2))
    return similarity, pair


def validate_dataset(dataset_root: Path) -> dict[str, Any]:
    root = Path(dataset_root).resolve()
    manifest_path = root / "freeze-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = load_cases()
    documents = [build_contract(case) for case in cases]
    reasons = validate_contract_documents(cases, documents)
    hashes: list[str] = []
    files_by_case: dict[str, Path] = {}
    for row in manifest.get("files", []):
        path = (root / row["path"]).resolve()
        if not path.is_file():
            reasons.append(f"文件不存在：{row['path']}")
            continue
        actual = sha256_file(path)
        hashes.append(actual)
        if actual != row["sha256"]:
            reasons.append(f"SHA-256 不匹配：{row['path']}")
        if path.stat().st_size != row["bytes"]:
            reasons.append(f"字节数不匹配：{row['path']}")
        if row["role"] == "valid":
            files_by_case[row["case_id"]] = path
    if len(manifest.get("files", [])) != 53:
        reasons.append("冻结清单必须包含53个文件")
    if len(hashes) != len(set(hashes)):
        reasons.append("冻结文件哈希必须唯一")

    page_metrics: dict[str, dict[str, Any]] = {}
    ocr_required: list[str] = []
    for case, source_document in zip(cases, documents, strict=True):
        path = files_by_case.get(case.case_id)
        if path is None:
            reasons.append(f"缺少有效合同：{case.case_id}")
            continue
        if case.format == "docx":
            try:
                extracted = _docx_text(path)
                if _chinese_count(extracted) < 1_000:
                    reasons.append(f"{case.case_id} DOCX 可提取正文过少")
                if case.revision_set:
                    with ZipFile(path) as archive:
                        xml = archive.read("word/document.xml")
                        settings = archive.read("word/settings.xml")
                        if not all(token in xml for token in (b"w:ins", b"w:del", b"w:commentRangeStart")):
                            reasons.append(f"{case.case_id} DOCX 修订结构不完整")
                        if b"w:trackRevisions" not in settings or "word/comments.xml" not in archive.namelist():
                            reasons.append(f"{case.case_id} DOCX 批注或修订设置缺失")
                page_metrics[case.case_id] = {"format": "docx", "page_count": None, "visual_status": "requires_render_review"}
            except Exception as exc:
                reasons.append(f"{case.case_id} DOCX 无法打开：{type(exc).__name__}")
            continue
        try:
            with fitz.open(path) as pdf:
                texts = [page.get_text().strip() for page in pdf]
                images = [bool(page.get_images(full=True)) for page in pdf]
                counts = [_chinese_count(text) for text in texts]
                if pdf.page_count < 2:
                    reasons.append(f"{case.case_id} PDF 页数异常：{pdf.page_count}")
                if case.render_mode == "native" and any(count == 0 for count in counts):
                    reasons.append(f"{case.case_id} 文本 PDF 存在空文本页")
                elif case.render_mode == "scanned":
                    if any(texts) or not all(images):
                        reasons.append(f"{case.case_id} 扫描 PDF 文本层或图像层不符合预期")
                    ocr_required.append(case.case_id)
                elif case.render_mode == "mixed" and not (any(texts) and any(not text for text in texts)):
                    reasons.append(f"{case.case_id} 混合 PDF 文本层不符合预期")
                nonempty_counts = [count for count in counts[1:] if count > 0]
                page_metrics[case.case_id] = {
                    "format": "pdf", "render_mode": case.render_mode, "page_count": pdf.page_count,
                    "minimum_extractable_chinese_per_content_page": min(nonempty_counts) if nonempty_counts else None,
                    "source_chinese_count": _chinese_count(source_document.plain_text),
                }
        except Exception as exc:
            reasons.append(f"{case.case_id} PDF 无法打开：{type(exc).__name__}")

    maximum_similarity, pair = _maximum_similarity(documents)
    report = {
        "schema_version": "1.0",
        "status": "passed" if not reasons else "failed",
        "evidence_level": "construction_truth_only",
        "formal_gold": False,
        "checks": {
            "manifest_file_count": len(manifest.get("files", [])),
            "unique_hash_count": len(set(hashes)),
            "maximum_source_similarity": maximum_similarity,
            "maximum_similarity_pair": list(pair) if pair else None,
            "ocr_required_cases": ocr_required,
            "page_metrics": page_metrics,
        },
        "reasons": reasons,
        "manifest_sha256": sha256_file(manifest_path),
    }
    (root / "validation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if reasons:
        raise ValueError("v3 冻结集验证失败：" + "; ".join(reasons))
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
