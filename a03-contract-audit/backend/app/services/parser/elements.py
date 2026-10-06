"""合同六要素的确定性抽取、校验与原文证据定位。"""

import re
from dataclasses import asdict, dataclass
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
    missing_fields: tuple[str, ...] = ()


def element_evidence_payload(
    result: ElementResult,
    *,
    parsed: DocumentParseResult | None = None,
) -> dict[str, object]:
    """构造可持久化的版本化证据，不包含合同全文。"""
    fields: dict[str, object] = {}
    for field, value in result.evidence.items():
        if isinstance(value, list):
            fields[field] = [asdict(item) for item in value]
        else:
            fields[field] = asdict(value)
    payload: dict[str, object] = {
        "schema_version": 1,
        "fields": fields,
        "review_fields": list(result.review_fields),
        "missing_fields": list(result.missing_fields),
    }
    if parsed is not None:
        payload["document"] = {
            "total_pages": parsed.total_pages,
            "missing_pages": list(parsed.missing_pages),
        }
    return payload


@dataclass(frozen=True)
class _Candidate:
    value: str
    raw_text: str
    start: int
    end: int
    confidence: float


_PARTY_PATTERNS = {
    "party_a": re.compile(
        r"(?:甲[ \t]*方|采购方|采购人|委托方|出租方)"
        r"(?:[ \t]*[（(][^）)\n]{0,20}[）)])?[ \t]*[：:][ \t]*([^\n，,；;。]{2,80})"
    ),
    "party_b": re.compile(
        r"(?:乙[ \t]*方|供应方|供应商|受托方|承租方)"
        r"(?:[ \t]*[（(][^）)\n]{0,20}[）)])?[ \t]*[：:][ \t]*([^\n，,；;。]{2,80})"
    ),
}

_PARTY_SECTION = re.compile(
    r"(?:^|\n)合同主体和通知信息\s*\n(?P<body>.*?)(?=\n签署页(?:\n|$))",
    re.DOTALL,
)
_PARTY_SECTION_LINE = re.compile(
    r"(?m)^[^\n：:；;]{1,24}[：:]\s*([^；;\n]{2,100})(?=[；;])"
)

_SUBJECT_PATTERNS = (
    re.compile(r"本合同“[^”\n]{1,40}”以(.{2,180}?)为交易基础"),
    re.compile(r"本次交易明细为(.{2,180}?)[。；;\n]"),
    re.compile(r"本次[^\n，,；;。]{1,30}为(.{2,180}?)[，,；;。]"),
    re.compile(r"(?:本合同标的|合同标的|标的名称|项目名称)\s*(?:为|是)?\s*[：:]?\s*([^\n，,；;。]{2,100})"),
    re.compile(
        r"(?:乙方|供应方|供应商|受托方)\s*(?:向\s*(?:甲方|采购方|采购人|委托方))?"
        r"\s*(?:提供|承建|销售)\s*([^\n，,；;。]{2,100})"
    ),
)

_STRUCTURED_AMOUNT_PATTERNS = (
    re.compile(r"合同金额或结算口径为([\s\S]{1,160}?)。\s*付款按"),
    re.compile(r"金额为([\s\S]{1,160}?)[；;]\s*付款节点为"),
)

_AMOUNT_PATTERN = re.compile(
    r"(?:合同(?:总价|金额|总额|价款)|总价|价款总额|总金额|成交金额)"
    r"\s*(?:为|是|合计)?\s*[：:]?\s*(?:含税\s*)?"
    r"((?:人民币\s*)?[￥¥]?\s*\d[\d,]*(?:\.\d+)?\s*(?:万元|元))"
)
_EXCLUDED_AMOUNT_TERMS = ("违约金", "赔偿", "保证金", "注册资本", "单价")
_EXPLICIT_CONTRACT_AMOUNT_LABELS = ("合同总价", "合同金额", "合同总额", "合同价款")
_NON_CONTRACT_AMOUNT_CONTEXT = ("设备清单", "材料清单", "物料清单", "清单")
_AMOUNT_ALIAS_LABELS = (
    "成交含税价", "暂估采购额", "定作报酬", "采购额", "含税价", "服务报酬",
    "开发经费", "签约合同价", "包干总价", "监理酬金", "年度服务费用", "场地使用费",
    "租赁本金", "转购价", "暂估保险费", "服务费",
)
_BARE_MONEY_PATTERN = re.compile(
    r"((?:人民币\s*)?[￥¥]?\s*\d[\d,]*(?:\.\d+)?\s*(?:万元|元))"
)

_DURATION_PATTERNS = (
    re.compile(r"适用期间为([^。；;\n]{2,100})(?=[。；;])"),
    re.compile(
        r"(?:合同期限|合同有效期|履约期限|履行期限|有效期)\s*(?:为)?\s*[：:]?\s*自?\s*"
        r"(\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?\s*"
        r"(?:至|到|—|-)\s*\d{4}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?)"
    ),
    re.compile(
        r"(?:合同期限|合同有效期|履约期限|履行期限|有效期)\s*(?:为)?\s*[：:]?\s*"
        r"([^\n，,；;。]{2,60})"
    ),
)

_STRUCTURED_PAYMENT_PATTERNS = (
    re.compile(r"依次按以下节点办理：(.{1,500}?)。\s*付款申请"),
    re.compile(r"付款按“(.{1,500}?)”执行"),
    re.compile(r"付款节点为(.{1,500}?)。"),
    re.compile(r"(?:结算与付款|账单与发票|对账和开票)按(.{1,500}?)执行"),
)

_PAYMENT_HEADER = re.compile(
    r"(?:付款方式|付款条款|付款计划|付款安排|收付款安排|支付方式|结算方式|付款节点(?=\s*[：:]))\s*[：:]?"
)
_NUMBERED_PAYMENT_NODE = re.compile(
    r"(?:^|\n)\s*(?:\d+\s*[.、]|[（(]\s*\d+\s*[）)])\s*([^；;。]+?)"
    r"(?=\n\s*(?:\d+\s*[.、]|[（(]\s*\d+\s*[）)])|[；;。]|\Z)",
    re.MULTILINE,
)


def _normalize_amount(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _normalize_duration(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    value = re.sub(
        r"(\d{4})年(\d{1,2})月(\d{1,2})日?",
        lambda match: f"{match.group(1)}-{int(match.group(2))}-{int(match.group(3))}",
        value,
    )
    value = value.replace("至", "至").replace("到", "至").replace("—", "至")
    return value


def _candidate(
    match: re.Match[str],
    confidence: float,
    *,
    normalize=lambda value: value,
) -> _Candidate:
    start, end = match.span(1)
    raw = match.group(1)
    left_trimmed = len(raw) - len(raw.lstrip())
    raw_text = raw.strip()
    value = normalize(raw_text)
    start += left_trimmed
    return _Candidate(value=value, raw_text=raw_text, start=start, end=start + len(raw_text), confidence=confidence)


def _collect_scalar(
    pattern: re.Pattern[str],
    text: str,
    confidence: float,
    *,
    normalize=lambda value: value,
) -> list[_Candidate]:
    return [
        _candidate(match, confidence, normalize=normalize)
        for match in pattern.finditer(text)
    ]


def _collect_subjects(text: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for index, pattern in enumerate(_SUBJECT_PATTERNS):
        candidates.extend(_collect_scalar(pattern, text, 0.98 if index == 0 else 0.90))
    return sorted(candidates, key=lambda item: (-item.confidence, item.start))


def _collect_section_parties(text: str) -> tuple[list[_Candidate], list[_Candidate]]:
    match = _PARTY_SECTION.search(text)
    if match is None:
        return [], []
    body_start = match.start("body")
    candidates = []
    for line in _PARTY_SECTION_LINE.finditer(match.group("body")):
        raw = line.group(1).strip()
        left_trimmed = len(line.group(1)) - len(line.group(1).lstrip())
        start = body_start + line.start(1) + left_trimmed
        candidates.append(_Candidate(raw, raw, start, start + len(raw), 0.99))
    return candidates[:1], candidates[1:2]


def _collect_amounts(text: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    structured_spans: list[tuple[int, int]] = []
    no_fixed_total = False
    for pattern in _STRUCTURED_AMOUNT_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1).strip()
            compact_raw = re.sub(r"\s+", "", raw)
            structured_spans.append(match.span(1))
            if not raw or any(
                marker in raw
                for marker in ("不设固定总额", "据实结算", "不设固定金额")
            ) or (
                re.search(r"(?:订单|验收数量).*?结算", compact_raw)
                and not re.search(r"\d|人民币|万元|元|%", compact_raw)
            ):
                no_fixed_total = True
                continue
            left_trimmed = len(match.group(1)) - len(match.group(1).lstrip())
            start = match.start(1) + left_trimmed
            candidates.append(
                _Candidate(
                    _normalize_amount(raw),
                    raw,
                    start,
                    start + len(raw),
                    0.995,
                )
            )
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
        local_prefix = text[max(sentence_start, match.start() - 24):match.start(1)]
        label = text[match.start():match.start(1)]
        excluded_in_sentence = any(term in sentence for term in _EXCLUDED_AMOUNT_TERMS)
        excluded_near_label = any(term in local_prefix for term in _EXCLUDED_AMOUNT_TERMS)
        explicit_contract_amount = any(
            item in label for item in _EXPLICIT_CONTRACT_AMOUNT_LABELS
        )
        inside_structured_value = any(
            start <= match.start(1) and match.end(1) <= end
            for start, end in structured_spans
        )
        weak_material_context = any(
            item in text[max(sentence_start, match.start() - 16):match.start()]
            for item in _NON_CONTRACT_AMOUNT_CONTEXT
        )
        if inside_structured_value or (
            not explicit_contract_amount
            and (
                no_fixed_total
                or excluded_near_label
                or excluded_in_sentence
                or weak_material_context
            )
        ):
            continue
        confidence = 0.99 if explicit_contract_amount else 0.90
        candidate = _candidate(match, confidence, normalize=_normalize_amount)
        candidates.append(candidate)
    alias_pattern = re.compile("|".join(map(re.escape, _AMOUNT_ALIAS_LABELS)))
    for label_match in alias_pattern.finditer(text):
        if no_fixed_total or any(
            start <= label_match.start() < end
            for start, end in structured_spans
        ):
            continue
        segment_end = min(
            next((text.find(mark, label_match.end()) for mark in "。；;" if text.find(mark, label_match.end()) >= 0), len(text)),
            label_match.end() + 100,
        )
        money_match = _BARE_MONEY_PATTERN.search(text, label_match.end(), segment_end)
        if money_match is None:
            continue
        candidate = _Candidate(
            value=_normalize_amount(money_match.group(1).strip()),
            raw_text=money_match.group(1).strip(),
            start=money_match.start(1),
            end=money_match.end(1),
            confidence=0.94,
        )
        if not any(existing.start == candidate.start for existing in candidates):
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: (-item.confidence, item.start))


def _collect_durations(text: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    for index, pattern in enumerate(_DURATION_PATTERNS):
        normalize = (lambda value: value) if index == 0 else _normalize_duration
        for candidate in _collect_scalar(pattern, text, 0.95, normalize=normalize):
            if index == 2 and (
                candidate.raw_text.startswith(("、", "，", ","))
                or not re.search(
                    r"\d{4}\s*[-/.年]|\d+\s*(?:年|个月|月|日|天)|"
                    r"生效|届满|终止|长期|永久|至|到",
                    candidate.raw_text,
                )
            ):
                continue
            if any(
                candidate.start < existing.end and existing.start < candidate.end
                for existing in candidates
            ):
                continue
            candidates.append(candidate)
    return sorted(candidates, key=lambda item: item.start)


def _payment_section_end(text: str, start: int) -> int:
    end = len(text)
    heading = re.search(
        r"\n\s*(?:第[一二三四五六七八九十\d]+条(?:\s*[^\n]*)?"
        r"|(?:违约责任|争议解决|合同期限|履行期限|履约期限|保密|知识产权)[：:]?"
        r"|验收(?:标准|方式|条款)?[ \t]*[：:])",
        text[start:end],
    )
    return start + heading.start() if heading else end


def _collect_payment_section(text: str, section_start: int, section_end: int) -> list[_Candidate]:
    section = text[section_start:section_end]
    nodes = [
        _Candidate(
            value=re.sub(r"[\r\n]+", "", match.group(1).strip()),
            raw_text=match.group(1).strip(),
            start=section_start + match.start(1),
            end=section_start + match.start(1) + len(match.group(1).strip()),
            confidence=0.92,
        )
        for match in _NUMBERED_PAYMENT_NODE.finditer(section)
        if match.group(1).strip()
    ]
    if nodes:
        return nodes

    inline = re.match(r"\s*([^。]+)", section)
    if inline is None or not inline.group(1).strip():
        return []
    raw = inline.group(1)
    base_start = section_start + inline.start(1)
    candidates: list[_Candidate] = []
    for part in re.finditer(r"[^；;]+", raw):
        value = part.group(0).strip()
        if not value or value.strip("“”\" ") == "" or (
            "适用以下商业条件" in value or "合同金额或结算口径" in value
        ):
            continue
        left_trimmed = len(part.group(0)) - len(part.group(0).lstrip())
        start = base_start + part.start() + left_trimmed
        candidates.append(_Candidate(re.sub(r"[\r\n]+", "", value), value, start, start + len(value), 0.90))
    return candidates


def _collect_payment_terms(text: str) -> list[_Candidate]:
    """按标题顺序收集付款节点；规范化后完全重复的节点只保留首次出现。"""
    structured: list[_Candidate] = []
    structured_seen: set[str] = set()
    for pattern in _STRUCTURED_PAYMENT_PATTERNS:
        for match in pattern.finditer(text):
            raw = match.group(1)
            group_start = match.start(1)
            for part in re.finditer(r"[^；;]+", raw):
                value = part.group(0).strip().strip("“”\"")
                if not value:
                    continue
                normalized = _normalized(value)
                if normalized in structured_seen:
                    continue
                left_trimmed = len(part.group(0)) - len(part.group(0).lstrip())
                start = group_start + part.start() + left_trimmed
                structured.append(_Candidate(value, value, start, start + len(value), 0.96))
                structured_seen.add(normalized)

    headers = list(_PAYMENT_HEADER.finditer(text))
    candidates: list[_Candidate] = list(structured)
    seen: set[str] = set(structured_seen)
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


def _payment_conflicts(candidates: list[_Candidate]) -> bool:
    stage_patterns = (
        ("start", re.compile(r"(?:合同)?(?:签订|签署|签约|生效)后|预付款|首付款|启动款")),
        ("invoice", re.compile(r"(?:收到)?发票后|收票后|开票后")),
        ("delivery", re.compile(r"发货|到货|交付|进场")),
        ("acceptance", re.compile(r"验收|终验|初验")),
        ("warranty", re.compile(r"质保|保修")),
        ("progress", re.compile(r"进度|里程碑")),
    )
    grouped: dict[str, set[str]] = {}
    for item in candidates:
        stage = next(
            (name for name, pattern in stage_patterns if pattern.search(item.value)),
            None,
        )
        if stage is None:
            action = re.search(r"(.{2,30}?)(?:支付|付款|付至|结算)", item.value)
            stage = _normalized(action.group(1)) if action else None
        if not stage:
            continue
        financial_value = re.search(
            r"\d+(?:\.\d+)?\s*%|(?:人民币\s*)?[￥¥]?\s*\d[\d,]*(?:\.\d+)?\s*(?:万元|元)",
            item.value,
        )
        if financial_value is None:
            continue
        grouped.setdefault(stage, set()).add(_normalized(financial_value.group(0)))
    return any(len(values) > 1 for values in grouped.values())


def legacy_element_values(
    values: dict[str, str | list[str] | None],
    *,
    text: str | None = None,
) -> dict[str, object]:
    """把结构化值转换为现有持久化、API、报表和前端可消费的扁平形状。"""
    legacy: dict[str, object] = {}
    for field, value in values.items():
        if isinstance(value, list):
            rendered = "；".join(item.strip() for item in value if item.strip())
            legacy[field] = rendered or None
        else:
            legacy[field] = value
    if text is not None:
        sign_date = re.search(
            r"(?:签订|签署)(?:日期|时间|于)?[：:]?\s*(\d{4}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2})",
            text,
        )
        legacy["sign_date"] = sign_date.group(1).strip() if sign_date else None
        legacy["text_length"] = len(text)
        legacy["has_breach_clause"] = "违约" in text
        legacy["has_dispute_clause"] = bool(re.search(r"争议(?:解决|处理)|仲裁|诉讼", text))
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
    overlapping = sorted(
        (start, end, page) for start, end, page in spans
        if start < candidate.end and end > candidate.start
    )
    pages = {page for _, _, page in overlapping}
    if len(pages) == 1 and None not in pages:
        covered = candidate.start
        for start, end, _ in overlapping:
            if start > covered and parsed.text[covered:start].strip():
                break
            covered = max(covered, end)
        if covered >= candidate.end:
            return next(iter(pages))
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
    page = _page_for(selected, spans, parsed)
    ambiguous = (
        len({_normalized(item.value) for item in candidates}) > 1
        or (any(block.anchor.page_number is not None for block in parsed.blocks) and page is None)
    )
    evidence = ElementEvidence(
        raw_text=selected.raw_text,
        page=page,
        start=selected.start,
        end=selected.end,
        confidence=selected.confidence,
        source="rule",
        validation="ambiguous" if ambiguous else "valid",
    )
    return selected.value, evidence, ambiguous


def extract_element_result(parsed: DocumentParseResult) -> ElementResult:
    """抽取固定六要素，并为每个非空值提供可回查的全文字符区间。"""
    text = _table_label_text(parsed)
    spans = _block_spans(parsed)
    section_party_a, section_party_b = _collect_section_parties(text)
    candidates = {
        "party_a": section_party_a + _collect_scalar(_PARTY_PATTERNS["party_a"], text, 0.96),
        "party_b": section_party_b + _collect_scalar(_PARTY_PATTERNS["party_b"], text, 0.96),
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
        payment_conflict = _payment_conflicts(payment_candidates) or any(
            any(block.anchor.page_number is not None for block in parsed.blocks)
            and _page_for(item, spans, parsed) is None
            for item in payment_candidates
        )
        evidence["payment_terms"] = [
            ElementEvidence(
                raw_text=item.raw_text,
                page=_page_for(item, spans, parsed),
                start=item.start,
                end=item.end,
                confidence=item.confidence,
                source="rule",
                validation="ambiguous" if payment_conflict else "valid",
            )
            for item in payment_candidates
        ]
        if payment_conflict:
            review_fields.append("payment_terms")

    return ElementResult(
        values=values,
        evidence=evidence,
        review_fields=tuple(review_fields),
        source_text=parsed.text,
        missing_fields=tuple(
            field for field, label in {
                "party_a": "甲方|采购方|采购人|委托方|出租方",
                "party_b": "乙方|供应方|供应商|受托方|承租方",
                "subject": "合同标的|标的名称|项目名称",
                "amount": "合同金额|合同总价|合同总额",
                "duration": "履行期限|履约期限|合同期限|合同有效期",
                "payment_terms": "付款方式|付款安排|支付方式|付款条款|付款节点",
            }.items()
            if not values.get(field) and re.search(rf"(?:^|\n)\s*(?:{label})\s*[：:]", text)
        ),
    )


def _table_label_text(parsed: DocumentParseResult) -> str:
    """仅在明确的双列表格标签后补等长冒号，保持全部原文字符偏移。"""
    labels = {
        "甲方", "乙方", "采购方", "采购人", "委托方", "出租方", "供应方", "供应商",
        "受托方", "承租方", "合同标的", "标的名称", "项目名称", "合同金额", "合同总价",
        "履行期限", "履约期限", "合同期限", "合同有效期", "付款方式", "付款安排", "支付方式", "付款节点",
    }
    text = parsed.text
    cursor = 0
    for block in parsed.blocks:
        start = parsed.text.find(block.text, cursor)
        if start < 0:
            continue
        cursor = start + len(block.text)
        if block.block_type != "table_row" or len(block.cells) != 2:
            continue
        label = block.cells[0].strip()
        if label not in labels or not block.cells[1].strip():
            continue
        separator = start + block.text.find(label) + len(label)
        if separator < len(text) and text[separator].isspace():
            text = text[:separator] + "：" + text[separator + 1:]
    return text


def merge_element_review(
    parsed: DocumentParseResult,
    result: ElementResult,
) -> tuple[bool, str | None]:
    """合并文档质量与字段冲突原因，保持原因顺序且避免重复。"""
    reasons = [parsed.review_reason] if parsed.review_reason else []
    if result.review_fields:
        reasons.append(ELEMENT_CONFLICT_REVIEW_REASON)
    if result.missing_fields:
        labels = dict(zip(ELEMENT_FIELDS, ("甲方", "乙方", "合同标的", "合同金额", "履行期限", "付款条款")))
        reasons.append("关键要素未能提取，请人工确认：" + "、".join(labels[field] for field in result.missing_fields))
    unique_reasons = list(dict.fromkeys(reasons))
    return parsed.requires_review or bool(unique_reasons), "；".join(unique_reasons) or None
