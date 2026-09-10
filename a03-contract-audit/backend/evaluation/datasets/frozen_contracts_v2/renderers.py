"""v2 文档格式渲染入口。"""
from __future__ import annotations

from pathlib import Path

from evaluation.datasets.frozen_contracts_v1.renderers import (
    ScanProfile,
    render_docx as _render_docx,
    render_mixed_pdf as _render_mixed_pdf,
    render_scanned_pdf as _render_scanned_pdf,
    render_text_pdf as _render_text_pdf,
)

from .content import ContractDocument
from .models import ContractCase
from .ooxml import inject_revisions


def render_docx(document: ContractDocument, output_path: Path, *, case: ContractCase) -> Path:
    path = _render_docx(document, output_path)
    if case.revision_set is not None:
        inject_revisions(path, case.revision_set)
    return path


def render_text_pdf(document: ContractDocument, output_path: Path) -> Path:
    return _render_text_pdf(document, output_path)


def render_scanned_pdf(document: ContractDocument, output_path: Path) -> Path:
    return _render_scanned_pdf(document, output_path, profile=ScanProfile.light())


def render_mixed_pdf(document: ContractDocument, output_path: Path) -> Path:
    return _render_mixed_pdf(document, output_path, profile=ScanProfile.light())


__all__ = [
    "render_docx",
    "render_text_pdf",
    "render_scanned_pdf",
    "render_mixed_pdf",
]
