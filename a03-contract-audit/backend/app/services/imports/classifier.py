"""基于本地规则的合同类型初筛。"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.services.imports.type_profiles import TypeProfile


@dataclass(frozen=True)
class TypeCandidate:
    contract_type: str
    score: float
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class TypeSuggestion:
    suggested_type: str
    confidence: float
    evidence: list[str]
    candidates: tuple[TypeCandidate, ...] = ()
    auto_ready_eligible: bool = False
    conflict: bool = False


_MATERIAL_SEMANTICS = re.compile(
    r"审核|审查|评审|说明|报告|模板|范本|复核|选用|记录|意见|参考|样本|材料|清单"
)
_BUSINESS_QUALIFIER = r"(?:设备|软件|系统|技术|服务|采购|销售|租赁|劳动|劳务|框架|合作)"
_CONTROLLED_TITLE_SUFFIX = (
    r"(?:"
    r"[（(](?:\d{4}(?:年|版)?|编号[A-Za-z0-9._-]{1,20}|(?:版本|修订)?[Vv]?\d+(?:\.\d+)*)[）)]"
    r"|(?:[Vv](?:ersion)?\d+(?:\.\d+)*|\d{4}版)"
    r")?"
)
_EXPLICIT_TYPE_RE = re.compile(
    r"^(?:合同类型|协议类型|文件类型)\s*[:：]\s*(?P<value>[^\r\n]{1,64})$"
)


def _find_explicit_type(text: str, available_types: list[str]) -> str:
    values_by_casefold = {
        value.strip().casefold(): value
        for value in available_types
        if value.strip()
    }
    nonempty_count = 0
    for raw_line in text[:1800].splitlines():
        line = raw_line.strip()
        if not line:
            continue
        nonempty_count += 1
        if nonempty_count > 40:
            break
        match = _EXPLICIT_TYPE_RE.fullmatch(line)
        if not match:
            continue
        matched = values_by_casefold.get(match.group("value").strip().casefold())
        if matched:
            return matched
    return ""


def _is_trusted_title_prefix(prefix: str) -> bool:
    if not prefix:
        return True
    if _MATERIAL_SEMANTICS.search(prefix):
        return False
    if re.fullmatch(rf"{_BUSINESS_QUALIFIER}{{1,2}}", prefix):
        return True
    return bool(re.fullmatch(
        rf".{{1,32}}(?:公司|集团|中心|部门|项目|工程){_BUSINESS_QUALIFIER}{{0,2}}",
        prefix,
    ))


def _is_contract_title(line: str, available_types: list[str]) -> bool:
    normalized = "".join(line.lower().split())
    if (
        len(normalized) > 64
        or any(marker in normalized for marker in ("附件", "条款"))
        or _MATERIAL_SEMANTICS.search(normalized)
    ):
        return False
    for value in available_types:
        match = re.fullmatch(
            rf"(?P<prefix>.*){re.escape(''.join(value.lower().split()))}{_CONTROLLED_TITLE_SUFFIX}",
            normalized,
        )
        if match and _is_trusted_title_prefix(match.group("prefix")):
            return True
    return False


def classify_contract_type(
    *,
    filename: str,
    text: str,
    available_types: list[str],
    profiles: Mapping[str, TypeProfile],
) -> TypeSuggestion:
    """在可用类型中排序候选，并仅把主交易证据标为自动就绪资格。"""

    name = Path(filename).stem.lower()
    lines = text[:8000].splitlines()
    first_line = next((line.strip().lower() for line in lines if line.strip()), "")
    title = first_line[:100]
    title_markers = ("附件", "条款")
    title_is_contract_type = _is_contract_title(first_line, available_types)
    heading = text[:1800].lower()
    body = text[1800:8000].lower()
    types = list(dict.fromkeys(available_types))
    scores: dict[str, float] = {value: 0.0 for value in types}
    evidence: dict[str, list[str]] = {value: [] for value in types}
    primary: set[str] = set()
    headline_scored: set[str] = set()
    trusted_headline_scored: set[str] = set()

    trusted_name = name if _is_contract_title(name, types) else ""
    material_name = bool(_MATERIAL_SEMANTICS.search(name))
    material_title = bool(_MATERIAL_SEMANTICS.search(first_line))
    trusted_title = title if title_is_contract_type else ""
    material_name = material_name or any(marker in name for marker in title_markers)
    material_title = material_title or any(
        marker in first_line for marker in title_markers
    )
    for source in (trusted_name, trusted_title):
        matches = [value for value in types if value.lower() in source]
        # 同一标题中较长的类型优先，避免“技术服务合同”同时命中“服务合同”。
        for value in matches:
            if any(value != longer and value in longer for longer in matches):
                continue
            if value in headline_scored:
                continue
            if not ((source == trusted_name and material_name) or (source == trusted_title and material_title)):
                scores[value] += 6
            evidence[value].append(value)
            if scores[value] > 0:
                primary.add(value)
                headline_scored.add(value)
                trusted_headline_scored.add(value)

    # 文件名中的受控交易别名可以产生建议，但不足以单独自动放行。
    for value in types:
        profile = profiles.get(value)
        if profile and scores[value] == 0 and not trusted_name:
            name_hits = [
                keyword for keyword in profile.aliases
                if keyword.lower() in name
            ]
            if name_hits and not material_name:
                scores[value] += 6
                evidence[value].extend(name_hits)
                headline_scored.add(value)

    semantic_heading = heading
    if trusted_title:
        semantic_heading = semantic_heading.replace(first_line, "", 1)

    for value in types:
        profile = profiles.get(value, TypeProfile())
        hits = [
            keyword
            for keyword in profile.positive_signals
            if keyword.lower() in semantic_heading or keyword.lower() in body
        ]
        if hits:
            if value not in headline_scored:
                scores[value] += (
                    3
                    if any(keyword.lower() in semantic_heading for keyword in hits)
                    else 1
                )
            evidence[value].extend(hits)
            primary.add(value)
        else:
            alias_hits = [
                alias
                for alias in profile.aliases
                if alias.lower() in semantic_heading or alias.lower() in body
            ]
            if alias_hits and value not in headline_scored:
                scores[value] += 0.25
                evidence[value].extend(alias_hits)

        negative_hits = [
            signal
            for signal in profile.negative_signals
            if signal.lower() in semantic_heading or signal.lower() in body
        ]
        if negative_hits:
            if value not in headline_scored:
                scores[value] -= (
                    3
                    if any(
                        signal.lower() in semantic_heading
                        for signal in negative_hits
                    )
                    else 1
                )
            evidence[value].extend(
                f"negative:{signal}" for signal in negative_hits
            )

    explicit_type = _find_explicit_type(text, types)
    conflict = False
    if explicit_type:
        conflict = any(
            value != explicit_type
            and value in primary
            and scores[value] >= 3
            for value in types
        )
        scores[explicit_type] += 10
        evidence[explicit_type].append(f"explicit_type:{explicit_type}")

    ranked = tuple(
        TypeCandidate(value, scores[value], tuple(dict.fromkeys(evidence[value])))
        for value in sorted(types, key=lambda item: (-scores[item], item))
        if scores[value] > 0
    )[:3]
    if not ranked:
        return TypeSuggestion("", 0.0, [])

    best = ranked[0]
    confidence = (
        0.20
        if best.score <= 0.25
        else 0.50
        if best.score < 3
        else 0.70
        if best.score < 6
        else 0.90
    )
    margin = best.score - ranked[1].score if len(ranked) > 1 else best.score
    if margin < 4:
        confidence = min(confidence, 0.40 if margin == 0 else 0.55 if margin <= 1 else 0.70)
    if explicit_type:
        confidence = 0.40 if conflict else 0.95
        eligible = not conflict
    else:
        eligible = (
            best.contract_type in trusted_headline_scored
            and best.contract_type in primary
            and best.score >= 6
            and margin >= 4
        )
    if material_name or material_title:
        eligible = False
    return TypeSuggestion(
        best.contract_type, confidence, list(best.evidence), ranked,
        eligible, conflict,
    )
