from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy.orm import Session

from app.models.models import ContractTypeProfile, LookupItem


@dataclass(frozen=True)
class TypeProfile:
    aliases: tuple[str, ...] = ()
    positive_signals: tuple[str, ...] = ()
    negative_signals: tuple[str, ...] = ()


def normalize_terms(
    values: Sequence[str],
    *,
    max_items: int = 32,
    max_length: int = 64,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or any(
        not isinstance(value, str) for value in values
    ):
        raise ValueError("合同类型规则必须是字符串数组")
    cleaned = tuple(dict.fromkeys(value.strip() for value in values if value.strip()))
    if len(cleaned) > max_items or any(len(value) > max_length for value in cleaned):
        raise ValueError("合同类型规则超出长度或数量限制")
    return cleaned


def load_type_profiles(
    db: Session,
    available_types: Sequence[str],
) -> Mapping[str, TypeProfile]:
    ordered_types = tuple(dict.fromkeys(available_types))
    if not ordered_types:
        return MappingProxyType({})

    rows = (
        db.query(LookupItem, ContractTypeProfile)
        .join(
            ContractTypeProfile,
            ContractTypeProfile.lookup_item_id == LookupItem.id,
        )
        .filter(
            LookupItem.category == "contract_type",
            LookupItem.value.in_(ordered_types),
            ContractTypeProfile.enabled.is_(True),
        )
        .all()
    )
    by_value: dict[str, TypeProfile] = {}
    for lookup, profile in rows:
        try:
            by_value[lookup.value] = TypeProfile(
                aliases=_decode_terms(profile.aliases_json),
                positive_signals=_decode_terms(profile.positive_signals_json),
                negative_signals=_decode_terms(profile.negative_signals_json),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
    return MappingProxyType(
        {value: by_value[value] for value in ordered_types if value in by_value}
    )


def _decode_terms(raw: str) -> tuple[str, ...]:
    values = json.loads(raw)
    if not isinstance(values, list):
        raise ValueError("合同类型规则必须是 JSON 数组")
    return normalize_terms(values)
