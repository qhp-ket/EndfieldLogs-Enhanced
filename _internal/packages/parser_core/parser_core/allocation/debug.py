"""Project allocation explanations and source contribution rows."""
from __future__ import annotations

from parser_core.allocation.shares import _round4
from parser_core.allocation.static_loadout import _RDPS_DEBUG_ZONE_LABELS
from parser_core.catalog.names import _resolve_character_name
from parser_core.effects.labels import _ATTR_TYPE_BUFF_LABELS
import copy
from typing import Any


_RDPS_DEBUG_ZONE_ORDER = {
    "atk": 0,
    "dmg_inc": 1,
    "fragile": 2,
    "vuln_taken": 3,
    "amp": 4,
    "res": 5,
    "combo": 6,
    "crit": 7,
    "arts_strength": 8,
    "prod_dmg_inc": 9,
    "prod_vuln_taken": 10,
}


def _sort_rdps_debug_zones(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            _RDPS_DEBUG_ZONE_ORDER.get(str(item.get("zone") or ""), 99),
            str(item.get("zone") or ""),
        ),
    )


def _rdps_debug_record_applicable_effect(
    *,
    window: dict[str, Any],
    effect: dict[str, Any],
    scope: str,
    rdps_credit: float | None = None,
) -> dict[str, Any]:
    source_key = window.get("source_character_key")
    raw_source_key = window.get("raw_source_character_key")
    zone = str(effect.get("zone") or "")
    row = {
        "scope": scope,
        "source_character_key": source_key,
        "source_character_name": window.get("source_character_name")
        or _resolve_character_name(source_key)
        or source_key,
        "raw_source_character_key": raw_source_key,
        "raw_source_character_name": window.get("raw_source_character_name")
        or _resolve_character_name(raw_source_key)
        or raw_source_key,
        "raw_source": window.get("raw_source"),
        "target_character_key": window.get("target_character_key"),
        "target_character_name": window.get("target_character_name"),
        "owner_raw": window.get("owner_raw"),
        "event_key": window.get("event_key"),
        "event_name": window.get("event_name"),
        "uid": window.get("uid"),
        "uid_aliases": list(window.get("uid_aliases") or []),
        "start_ts_ms": window.get("start_ts_ms"),
        "start_time": window.get("start_time"),
        "end_ts_ms": window.get("end_ts_ms"),
        "end_time": window.get("end_time"),
        "zone": zone,
        "zone_label": _RDPS_DEBUG_ZONE_LABELS.get(zone, zone),
        "element": str(effect.get("element") or "all"),
        "rate": _round4(effect.get("rate") or 0.0),
        "rdps_credit": _round4(rdps_credit),
    }
    condition = effect.get("condition")
    if isinstance(condition, dict):
        row["condition"] = dict(condition)
    for key in ('rdps_whitelist_keys', 'external_rdps_allowed', 'keyword_origin', 'recipient_side', 'converted_attribute'):
        if key in effect:
            row[key] = copy.deepcopy(effect[key])
    return row


def _rdps_debug_record_dpd_self_residual(
    *,
    hit: dict[str, Any],
    zone: str,
    rate: float,
) -> dict[str, Any]:
    attacker_key = str(hit.get("character_key") or "")
    attacker_name = str(hit.get("character_name") or _resolve_character_name(attacker_key) or attacker_key)
    return {
        "scope": "self",
        "source_character_key": attacker_key,
        "source_character_name": attacker_name,
        "raw_source_character_key": attacker_key,
        "raw_source_character_name": attacker_name,
        "raw_source": "DPD_RAW",
        "target_character_key": attacker_key,
        "target_character_name": attacker_name,
        "owner_raw": "DPD_RAW",
        "event_key": "__dpd_self_residual__",
        "event_name": "自身基线/未归因（DPD残差）",
        "uid": None,
        "start_ts_ms": None,
        "start_time": None,
        "end_ts_ms": None,
        "end_time": None,
        "zone": zone,
        "zone_label": _RDPS_DEBUG_ZONE_LABELS.get(zone, zone),
        "element": str(hit.get("damage_element") or "all"),
        "rate": _round4(rate),
        "rdps_credit": None,
    }


def _rdps_debug_record_baseline_self(
    *,
    hit: dict[str, Any],
    attr_type: int,
    zone: str,
    element: str,
    rate: float,
    final_value: float,
    captured: float,
) -> dict[str, Any]:
    attacker_key = str(hit.get("character_key") or "")
    attacker_name = str(hit.get("character_name") or _resolve_character_name(attacker_key) or attacker_key)
    label = _ATTR_TYPE_BUFF_LABELS.get(attr_type) or _RDPS_DEBUG_ZONE_LABELS.get(zone, zone)
    return {
        "scope": "self",
        "source_character_key": attacker_key,
        "source_character_name": attacker_name,
        "raw_source_character_key": attacker_key,
        "raw_source_character_name": attacker_name,
        "raw_source": "BASELINE",
        "target_character_key": attacker_key,
        "target_character_name": attacker_name,
        "owner_raw": "BASELINE",
        "event_key": f"__baseline_attr_{attr_type}__",
        "event_name": f"自身属性基线（{label} / attrType={attr_type}）",
        "uid": None,
        "start_ts_ms": None,
        "start_time": None,
        "end_ts_ms": None,
        "end_time": None,
        "zone": zone,
        "zone_label": _RDPS_DEBUG_ZONE_LABELS.get(zone, zone),
        "element": element,
        "rate": _round4(rate),
        "rdps_credit": None,
        "baseline_final": _round4(final_value),
        "baseline_captured": _round4(captured),
    }


def _rdps_debug_record_static_self(
    *,
    hit: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    attacker_key = str(hit.get("character_key") or "")
    attacker_name = str(hit.get("character_name") or _resolve_character_name(attacker_key) or attacker_key)
    zone = str(entry.get("zone") or "")
    source_type = str(entry.get("source_type") or "static")
    source_name = str(entry.get("source_name") or "静态来源")
    return {
        "scope": "self",
        "source_character_key": attacker_key,
        "source_character_name": attacker_name,
        "raw_source_character_key": attacker_key,
        "raw_source_character_name": attacker_name,
        "raw_source": source_type,
        "target_character_key": attacker_key,
        "target_character_name": attacker_name,
        "owner_raw": source_type,
        "event_key": f"__static_self_{source_type}__",
        "event_name": f"自身静态基线（{source_name} / {entry.get('label') or zone}）",
        "uid": None,
        "start_ts_ms": None,
        "start_time": None,
        "end_ts_ms": None,
        "end_time": None,
        "zone": zone,
        "zone_label": _RDPS_DEBUG_ZONE_LABELS.get(zone, zone),
        "element": str(entry.get("element") or "all"),
        "rate": _round4(entry.get("rate") or 0.0),
        "rdps_credit": None,
        "note": entry.get("note"),
    }


def _rdps_contribution_rows(
    contributions_map: dict[str, float],
    *,
    sort_by_value: bool,
) -> list[dict[str, Any]]:
    items = sorted(
        contributions_map.items(),
        key=(lambda item: (-item[1], item[0])) if sort_by_value else (lambda item: item[0]),
    )
    return [
        {
            "character_key": character_key,
            "character_name": _resolve_character_name(character_key) or character_key,
            "value": value,
        }
        for character_key, value in items
        if value > 0.0
    ]


def _rdps_debug_record_arts_effect_provenance(
    *,
    effect_window: dict[str, Any],
    effect: dict[str, Any],
    source_key: str,
    rate: float,
    provenance: dict[str, Any] | None,
    scope: str,
) -> dict[str, Any]:
    debug_effect = dict(effect)
    debug_effect["rate"] = rate
    debug_window = dict(effect_window)
    debug_window["source_character_key"] = source_key
    debug_window["source_character_name"] = _resolve_character_name(source_key) or source_key
    record = _rdps_debug_record_applicable_effect(window=debug_window, effect=debug_effect, scope=scope)
    if provenance:
        record.update(
            {
                "derived_from_zone": "arts_strength",
                "effect_source_character_key": provenance.get("effect_source_character_key"),
                "arts_strength_points": _round4(provenance.get("arts_strength_points") or 0.0),
                "arts_strength_self_points": _round4(provenance.get("arts_strength_self_points") or 0.0),
                "arts_strength_external_points": _round4(provenance.get("arts_strength_external_points") or 0.0),
                "effect_rdps_whitelist_keys": list(effect.get('rdps_whitelist_keys') or []),
                "rdps_whitelist_keys": list(provenance.get('arts_strength_whitelist_keys') or []),
            }
        )
    return record
