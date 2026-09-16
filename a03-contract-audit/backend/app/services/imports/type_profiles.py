from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.models import ContractTypeProfile, LookupItem


@dataclass(frozen=True)
class TypeProfile:
    aliases: tuple[str, ...] = ()
    positive_signals: tuple[str, ...] = ()
    negative_signals: tuple[str, ...] = ()


class ProfileNotFound(LookupError):
    pass


class ProfileVersionConflict(RuntimeError):
    pass


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


def load_profile_rows(
    db: Session,
) -> list[tuple[LookupItem, ContractTypeProfile]]:
    return (
        db.query(LookupItem, ContractTypeProfile)
        .join(
            ContractTypeProfile,
            ContractTypeProfile.lookup_item_id == LookupItem.id,
        )
        .filter(LookupItem.category == "contract_type")
        .order_by(LookupItem.sort_order, LookupItem.id)
        .all()
    )


def update_profile(
    db: Session,
    *,
    item_id: int,
    expected_version: int,
    aliases: Sequence[str],
    positive_signals: Sequence[str],
    negative_signals: Sequence[str],
    enabled: bool,
) -> tuple[LookupItem, ContractTypeProfile]:
    normalized_aliases = normalize_terms(aliases)
    normalized_positive = normalize_terms(positive_signals)
    normalized_negative = normalize_terms(negative_signals)
    result = db.execute(
        update(ContractTypeProfile)
        .where(
            ContractTypeProfile.lookup_item_id == item_id,
            ContractTypeProfile.version == expected_version,
        )
        .values(
            aliases_json=json.dumps(normalized_aliases, ensure_ascii=False),
            positive_signals_json=json.dumps(
                normalized_positive,
                ensure_ascii=False,
            ),
            negative_signals_json=json.dumps(
                normalized_negative,
                ensure_ascii=False,
            ),
            enabled=enabled,
            version=ContractTypeProfile.version + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        valid_lookup = db.query(LookupItem.id).filter(
            LookupItem.id == item_id,
            LookupItem.category == "contract_type",
        ).first()
        if valid_lookup is None:
            raise ProfileNotFound(item_id)
        raise ProfileVersionConflict(item_id)

    db.flush()
    row = (
        db.query(LookupItem, ContractTypeProfile)
        .join(
            ContractTypeProfile,
            ContractTypeProfile.lookup_item_id == LookupItem.id,
        )
        .filter(LookupItem.id == item_id)
        .one()
    )
    return row


def _decode_terms(raw: str) -> tuple[str, ...]:
    values = json.loads(raw)
    if not isinstance(values, list):
        raise ValueError("合同类型规则必须是 JSON 数组")
    return normalize_terms(values)
