"""合同六要素的确定性抽取、校验与原文证据定位。"""

import re
from dataclasses import dataclass
from typing import Literal

from app.services.parser.extractor import DocumentParseResult


ELEMENT_FIELDS = (
    "party_a",
    "party_b",
    "subject",
    "amount",
    "duration",
    "payment_terms",
)
ELEMENT_CONFLICT_REVIEW_REASON = "关键要素冲突，请人工确认"


@dataclass(frozen=True)
class ElementEvidence:
    raw_text: str
    page: int | None
    start: int
    end: int
    confidence: float
    source: Literal["rule", "llm"]
    validation: Literal["valid", "ambiguous", "invalid"]


@dataclass(frozen=True)
class ElementResult:
    values: dict[str, str | list[str] | None]
    evidence: dict[str, ElementEvidence | list[ElementEvidence]]
    review_fields: tuple[str, ...]
    source_text: str


@dataclass(frozen=True)
class _Candidate:
    value: str
    start: int
    end: int
    confidence: float


_PARTY_PATTERNS = {
    "party_a": re.compile(
        r"(?:甲\s*方|采购方|采购人|委托方|出租方)"
        r"(?:\s*[（(][^）)\n]{0,20}[）)])?\s*[：:]\s*([^\n，,；;。]{2,80})"
    ),
    "party_b": re.compile(
        r"(?:乙\s*方|供应方|供应商|受托方|承租方)"
        r"(?:\s*[（(][^）)\n]{0,20}[）)])?\s*[：:]\s*([^\n，,；;。]{2,80})"
    ),
}

_SUBJECT_PATTERNS = (
    re.compile(r"(?:本合同标的|合同标的|标的名称|项目名称)\s*(?:为|是)?\s*[：:]?\s*([^\n，,；;。]{2,100})"),
    re.compile(
        r"(?:乙方|供应方|供应商|受托方)\s*(?:向\s*(?:甲方|采购方|采购人|委托方))?"
        r"\s*(?:提供|承建|销售)\s*([^\n，,；;。]{2,100})"
    ),
)

_AMOUNT_PATTERN = re.compile(
    r"(?:合同(?:总价|金额|总额|价款)|总价|价款总额|总金额|成交金额)"
    r"\s*(?:为|是|合计)?\s*[：:]?\s*(?:含税\s*)?"
    r"((?:人民币\s*)?[￥¥]?\s*\d[\d,]*(?:\.\d+)?\s*(?:万元|元))"
)
_EXCLUDED_AMOUNT_TERMS = ("违约金", "赔偿", "保证金", "注册资本", "单价")
_EXPLICIT_CONTRACT_AMOUNT_LABELS = ("合同总价", "合同金额", "合同总额", "合同价款")

_DURATION_PATTERNS = (
    re.compile(
        r"(?:合同期限|合同有效期|履约期限|有效期)\s*(?:为)?\s*[：:]?\s*自?\s*"
        r"(\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?\s*"
        r"(?:至|到|—|-)\s*\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?)"
    ),
    re.compile(
        r"(?:合同期限|合同有效期|履约期限|有效期)\s*(?:为)?\s*[：:]?\s*"
        r"([^\n，,；;。]{2,60})"
    ),
)

_PAYMENT_HEADER = re.compile(
    r"(?:付款方式|付款条款|付款计划|付款安排|收付款安排|支付方式|结算方式)\s*[：:]?"
)
_NUMBERED_PAYMENT_NODE = re.compile(
    r"(?:^|\n)\s*(?:\d+\s*[.、]|[（(]\s*\d+\s*[）)])\s*([^；;。\n]+)",
    re.MULTILINE,
)


def _candidate(match: re.Match[str], confidence: float) -> _Candidate:
    start, end = match.span(1)
    raw = match.group(1)
    left_trimmed = len(raw) - len(raw.lstrip())
    value = raw.strip()
    start += left_trimmed
    return _Candidate(value=value, start=start, end=start + len(value), confidence=confidence)


def _collect_scalar(pattern: re.Pattern[str], text: str, confidence: float) -> list[_Candidate]:
    return [_candidate(match, confidence) for match in pattern.finditer(text)]


def _collect_subjects(text: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for pattern in _SUBJECT_PATTERNS:
        candidates.extend(_collect_scalar(pattern, text, 0.90))
    return sorted(candidates, key=lambda item: item.start)


def _collect_amounts(text: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for match in _AMOUNT_PATTERN.finditer(text):
        sentence_start = max(
            (text.rfind(mark, 0, match.start()) for mark in "。！？\n；;"),
            default=-1,
        ) + 1
        sentence_ends = [
            index
            for mark in "。！？\n；;"
            if (index := text.find(mark, match.end())) >= 0
        ]
        sentence_end = min(sentence_ends, default=len(text))
        sentence = text[sentence_start:sentence_end]
        local_prefix = text[max(sentence_start, match.start() - 16):match.start(1)]
        label = text[match.start():match.start(1)]
        excluded_in_sentence = any(term in sentence for term in _EXCLUDED_AMOUNT_TERMS)
        excluded_near_label = any(term in local_prefix for term in _EXCLUDED_AMOUNT_TERMS)
        explicit_contract_amount = any(
            item in label for item in _EXPLICIT_CONTRACT_AMOUNT_LABELS
        )
        if not explicit_contract_amount and (excluded_near_label or excluded_in_sentence):
            continue
        candidates.append(_candidate(match, 0.98))
    return candidates


def _collect_durations(text: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for pattern in _DURATION_PATTERNS:
        for candidate in _collect_scalar(pattern, text, 0.95):
            if any(
                candidate.start < existing.end and existing.start < candidate.end
                for existing in candidates
            ):
                continue
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.start)


def _payment_section_end(text: str, start: int) -> int:
    end = min(len(text), start + 1200)
    heading = re.search(
        r"\n\s*(?:第[一二三四五六七八九十\d]+条(?:\s*[^\n]*)?"
        r"|(?:违约责任|争议解决|合同期限|保密|知识产权)[：:]?)",
        text[start:end],
    )
    return start + heading.start() if heading else end


def _collect_payment_section(text: str, section_start: int, section_end: int) -> list[_Candidate]:
    section = text[section_start:section_end]
    nodes = [
        _Candidate(
            value=match.group(1).strip(),
            start=section_start + match.start(1),
            end=section_start + match.start(1) + len(match.group(1).strip()),
            confidence=0.92,
        )
        for match in _NUMBERED_PAYMENT_NODE.finditer(section)
        if match.group(1).strip()
    ]
    if nodes:
        return nodes

    inline = re.match(r"\s*([^\n。]+)", section)
    if inline is None or not inline.group(1).strip():
        return []
    raw = inline.group(1)
    base_start = section_start + inline.start(1)
    candidates: list[_Candidate] = []
    for part in re.finditer(r"[^；;]+", raw):
        value = part.group(0).strip()
        if not value:
            continue
        left_trimmed = len(part.group(0)) - len(part.group(0).lstrip())
        start = base_start + part.start() + left_trimmed
        candidates.append(_Candidate(value, start, start + len(value), 0.90))
    return candidates


def _collect_payment_terms(text: str) -> list[_Candidate]:
    """按标题顺序收集付款节点；规范化后完全重复的节点只保留首次出现。"""
    headers = list(_PAYMENT_HEADER.finditer(text))
    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for index, header in enumerate(headers):
        next_header = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        section_end = min(_payment_section_end(text, header.end()), next_header)
        for candidate in _collect_payment_section(text, header.end(), section_end):
            normalized = _normalized(candidate.value)
            if normalized in seen:
                continue
            seen.add(normalized)
            candidates.append(candidate)
    return candidates


def legacy_element_values(
    values: dict[str, str | list[str] | None],
) -> dict[str, str | None]:
    """把结构化值转换为现有持久化、API、报表和前端可消费的扁平形状。"""
    legacy: dict[str, str | None] = {}
    for field, value in values.items():
        if isinstance(value, list):
            rendered = "；".join(item.strip() for item in value if item.strip())
            legacy[field] = rendered or None
        else:
            legacy[field] = value
    return legacy


def _block_spans(parsed: DocumentParseResult) -> list[tuple[int, int, int | None]]:
    spans: list[tuple[int, int, int | None]] = []
    cursor = 0
    for block in getattr(parsed, "blocks", ()):
        if block.anchor.char_start is not None and block.anchor.char_end is not None:
            spans.append((block.anchor.char_start, block.anchor.char_end, block.anchor.page_number))
            continue
        start = parsed.text.find(block.text, cursor)
        if start < 0:
            compact_block = "".join(char for char in block.text if not char.isspace())
            compact_source: list[str] = []
            source_offsets: list[int] = []
            for source_index, char in enumerate(parsed.text[cursor:], start=cursor):
                if char.isspace():
                    continue
                compact_source.append(char)
                source_offsets.append(source_index)
            compact_start = "".join(compact_source).find(compact_block)
            if compact_start >= 0 and compact_block:
                start = source_offsets[compact_start]
                end = source_offsets[compact_start + len(compact_block) - 1] + 1
                spans.append((start, end, block.anchor.page_number))
                cursor = end
                continue
        if start < 0:
            continue
        end = start + len(block.text)
        spans.append((start, end, block.anchor.page_number))
        cursor = end
    return spans


def _page_for(
    candidate: _Candidate,
    spans: list[tuple[int, int, int | None]],
    parsed: DocumentParseResult,
) -> int | None:
    for block_start, block_end, page in spans:
        if block_start <= candidate.start and candidate.end <= block_end:
            return page
    matching_pages = {
        block.anchor.page_number
        for block in parsed.blocks
        if candidate.value in block.text and block.anchor.page_number is not None
    }
    if len(matching_pages) == 1:
        return matching_pages.pop()
    return None


def _normalized(value: str) -> str:
    return re.sub(r"[\s，,；;。]", "", value)


def _scalar_result(
    candidates: list[_Candidate],
    spans: list[tuple[int, int, int | None]],
    parsed: DocumentParseResult,
) -> tuple[str | None, ElementEvidence | None, bool]:
    if not candidates:
        return None, None, False
    selected = candidates[0]
    ambiguous = len({_normalized(item.value) for item in candidates}) > 1
    evidence = ElementEvidence(
        raw_text=selected.value,
        page=_page_for(selected, spans, parsed),
        start=selected.start,
        end=selected.end,
        confidence=selected.confidence,
        source="rule",
        validation="ambiguous" if ambiguous else "valid",
    )
    return selected.value, evidence, ambiguous


def extract_element_result(parsed: DocumentParseResult) -> ElementResult:
    """抽取固定六要素，并为每个非空值提供可回查的全文字符区间。"""
    text = parsed.text
    spans = _block_spans(parsed)
    candidates = {
        "party_a": _collect_scalar(_PARTY_PATTERNS["party_a"], text, 0.96),
        "party_b": _collect_scalar(_PARTY_PATTERNS["party_b"], text, 0.96),
        "subject": _collect_subjects(text),
        "amount": _collect_amounts(text),
        "duration": _collect_durations(text),
    }
    values: dict[str, str | list[str] | None] = {}
    evidence: dict[str, ElementEvidence | list[ElementEvidence]] = {}
    review_fields: list[str] = []
    for field in ELEMENT_FIELDS[:-1]:
        value, item_evidence, ambiguous = _scalar_result(candidates[field], spans, parsed)
        values[field] = value
        if item_evidence is not None:
            evidence[field] = item_evidence
        if ambiguous:
            review_fields.append(field)

    payment_candidates = _collect_payment_terms(text)
    values["payment_terms"] = [item.value for item in payment_candidates]
    if payment_candidates:
        evidence["payment_terms"] = [
            ElementEvidence(
                raw_text=item.value,
                page=_page_for(item, spans, parsed),
                start=item.start,
                end=item.end,
                confidence=item.confidence,
                source="rule",
                validation="valid",
            )
            for item in payment_candidates
        ]

    return ElementResult(
        values=values,
        evidence=evidence,
        review_fields=tuple(review_fields),
        source_text=text,
    )


def merge_element_review(
    parsed: DocumentParseResult,
    result: ElementResult,
) -> tuple[bool, str | None]:
    """合并文档质量与字段冲突原因，保持原因顺序且避免重复。"""
    reasons = [parsed.review_reason] if parsed.review_reason else []
    if result.review_fields:
        reasons.append(ELEMENT_CONFLICT_REVIEW_REASON)
    unique_reasons = list(dict.fromkeys(reasons))
    return parsed.requires_review or bool(unique_reasons), "；".join(unique_reasons) or None
