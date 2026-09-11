"""独立验证冻结合同集的完整性、格式、现实画像和隐私边界。"""
from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
from typing import Any
from zipfile import BadZipFile, ZipFile

import fitz
from docx import Document

from evaluation.batch import load_batch_manifest

from .content import build_contract
from .generate import DATASET_ROOT, sha256_file
from .models import load_cases, load_profile


_IDENTITY_NUMBER = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
_BANK_CARD = re.compile(r"(?<!\d)\d{16,19}(?!\d)")
_REAL_SEAL_WORDS = re.compile(r"(?:公安局|人民政府|人民法院|国家税务总局).{0,12}(?:印章|公章)")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} 必须是 JSON 对象")
    return payload


def _extract_docx_text(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            if "word/document.xml" not in archive.namelist():
                raise ValueError("缺少 word/document.xml")
        word = Document(path)
    except (BadZipFile, ValueError, KeyError) as exc:
        raise ValueError(f"DOCX 无法打开: {path.name}: {exc}") from exc
    parts = [paragraph.text for paragraph in word.paragraphs]
    parts.extend(cell.text for table in word.tables for row in table.rows for cell in row.cells)
    return "\n".join(parts)


def _pdf_characteristics(path: Path) -> tuple[int, list[str], list[bool]]:
    try:
        with fitz.open(path) as pdf:
            return (
                pdf.page_count,
                [page.get_text().strip() for page in pdf],
                [bool(page.get_images(full=True)) for page in pdf],
            )
    except Exception as exc:
        raise ValueError(f"PDF 无法打开: {path.name}: {type(exc).__name__}") from exc


def _canonical_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def validate_dataset(dataset_root: Path) -> dict[str, Any]:
    root = Path(dataset_root).resolve()
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    manifest_path = root / "freeze-manifest.json"
    report_path = root / "validation-report.json"

    try:
        manifest = _load_json(manifest_path)
        files = manifest.get("files")
        if not isinstance(files, list) or len(files) != 53:
            reasons.append("冻结清单必须包含 53 个二进制样本")
            files = []

        hashes: list[str] = []
        for row in files:
            if not isinstance(row, dict):
                reasons.append("冻结清单文件记录必须是对象")
                continue
            relative = Path(str(row.get("path", "")))
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError:
                reasons.append(f"样本路径越界: {relative}")
                continue
            if not path.is_file():
                reasons.append(f"样本文件不存在: {relative.as_posix()}")
                continue
            actual_hash = sha256_file(path)
            expected_hash = str(row.get("sha256", ""))
            hashes.append(actual_hash)
            if actual_hash != expected_hash:
                reasons.append(f"SHA-256 不匹配: {relative.as_posix()}")
            if path.stat().st_size != row.get("bytes"):
                reasons.append(f"字节数不匹配: {relative.as_posix()}")
        if len(hashes) != len(set(hashes)):
            reasons.append("冻结样本存在重复 SHA-256")
        checks["manifest_file_count"] = len(files)
        checks["unique_hash_count"] = len(set(hashes))

        try:
            batch = load_batch_manifest(root / "batch-manifest.json")
            checks["batch_valid_count"] = sum(item.role == "valid" for item in batch.samples)
            checks["batch_invalid_count"] = sum(item.role == "invalid" for item in batch.samples)
        except ValueError as exc:
            reasons.append(str(exc))

        profile = load_profile(DATASET_ROOT / "corpus-profile.json")
        cases = load_cases(DATASET_ROOT / "cases.json")
        checks["formats"] = dict(Counter(case.format for case in cases))
        checks["scenarios"] = dict(Counter(case.scenario for case in cases))
        if checks["formats"] != dict(profile.formats):
            reasons.append("案例格式分布与画像不一致")
        if checks["scenarios"] != dict(profile.scenarios):
            reasons.append("案例场景分布与画像不一致")

        extracted_texts: dict[str, str] = {}
        file_by_case = {
            str(row.get("case_id")): root / str(row.get("path"))
            for row in files
            if isinstance(row, dict) and row.get("role") == "valid"
        }
        for case in cases:
            path = file_by_case.get(case.case_id)
            if path is None or not path.is_file():
                reasons.append(f"有效案例缺少文件: {case.case_id}")
                continue
            if case.format == "docx":
                text = _extract_docx_text(path)
                if len(text.strip()) < 500:
                    reasons.append(f"DOCX 正文过短: {case.case_id}")
                extracted_texts[case.case_id] = text
            else:
                page_count, page_texts, image_pages = _pdf_characteristics(path)
                if page_count != case.target_pages:
                    reasons.append(
                        f"PDF 页数不符: {case.case_id} expected={case.target_pages} actual={page_count}"
                    )
                if case.render_mode == "native" and not all(page_texts):
                    reasons.append(f"文本 PDF 存在无文本页: {case.case_id}")
                if case.render_mode == "scanned" and (
                    any(page_texts) or not all(image_pages)
                ):
                    reasons.append(f"扫描 PDF 文本层或图像页不符: {case.case_id}")
                if case.render_mode == "mixed" and not (
                    any(page_texts) and not all(page_texts) and all(
                        image for image, text in zip(image_pages, page_texts) if not text
                    )
                ):
                    reasons.append(f"混合 PDF 页面组成不符: {case.case_id}")
                extracted_texts[case.case_id] = "\n".join(page_texts)

            if not all("测试" in party for party in case.parties):
                reasons.append(f"主体未显式标记为合成测试名称: {case.case_id}")

        source_texts = {
            case.case_id: _canonical_text(build_contract(case).plain_text)
            for case in cases
        }
        maximum_similarity, pair = max(
            (
                SequenceMatcher(None, source_texts[left], source_texts[right], autojunk=True).ratio(),
                (left, right),
            )
            for left, right in combinations(source_texts, 2)
        )
        checks["maximum_similarity"] = maximum_similarity
        checks["maximum_similarity_pair"] = list(pair)
        if maximum_similarity >= 0.92:
            reasons.append(f"正文相似度过高: {pair[0]} / {pair[1]} = {maximum_similarity:.4f}")

        searchable = "\n".join(build_contract(case).plain_text for case in cases)
        if _IDENTITY_NUMBER.search(searchable):
            reasons.append("检测到疑似身份证号码")
        if _BANK_CARD.search(searchable):
            reasons.append("检测到疑似银行卡号")
        if _REAL_SEAL_WORDS.search(searchable):
            reasons.append("检测到疑似真实机关签章描述")
        checks["valid_files_checked"] = len(extracted_texts)
    except Exception as exc:
        if isinstance(exc, ValueError):
            reasons.append(str(exc))
        else:
            reasons.append(f"验证器异常: {type(exc).__name__}: {exc}")

    report = {
        "schema_version": "1.0",
        "status": "passed" if not reasons else "failed",
        "evidence_level": "construction_truth_only",
        "formal_gold": False,
        "checks": checks,
        "reasons": reasons,
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.is_file() else None,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
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
