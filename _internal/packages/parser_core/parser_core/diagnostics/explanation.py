"""Hit evidence decoding and diagnostic contribution explanations."""
from __future__ import annotations
import re
from typing import Any
from parser_core.effects.labels import _ATTR_TYPE_BUFF_LABELS
from parser_core.allocation.static_loadout import _ATTR_TYPE_TO_EFFECT
from parser_core.allocation.hit import _allocate_rdps_for_hit
from parser_core.ingestion.fields import _coerce_float
from parser_core.ingestion.fields import _parse_zone_values as _parse_runtime_zone_values
from parser_core.ingestion.fields import _parse_dpd_raw_line as _parse_runtime_dpd_raw_line
from parser_core.ingestion.skill_identity import _canonical_hit_skill_id
from parser_core.ingestion.skill_identity import _canonical_hit_skill_id_from_cast_context
from parser_core.catalog.names import _resolve_character_name
from parser_core.catalog.names import _runtime_skill_number
from parser_core.catalog.diagnostics import (
    _load_skill_action_graph_candidate_map,
)


ZONE_LABELS = {
    "atk": "攻击",
    "dmg_inc": "增伤",
    "fragile": "脆弱",
    "vuln_taken": "易伤",
    "amp": "增幅",
    "res": "减抗",
    "combo": "连击",
    "crit": "暴击",
}


ZONE_ORDER = {
    "atk": 0,
    "dmg_inc": 1,
    "fragile": 2,
    "vuln_taken": 3,
    "amp": 4,
    "res": 5,
    "combo": 6,
    "crit": 7,
}


ELEMENT_LABELS = {
    "physical": "物理",
    "fire": "灼热",
    "pulse": "电磁",
    "cryst": "寒冷",
    "natural": "自然",
    "spell": "法术",
}


DPD_ZONE_BUCKETS = {
    "dmg_inc": ("atk", 1),
    "amp": ("atk", 3),
    "combo": ("atk", 4),
    "vuln_taken": ("def", 1),
    "fragile": ("def", 5),
}


_HIT_SEQ_RE = re.compile(r"\bHP_V2\s+#(\d+)\b")


_ACTOR_MAP_RE = re.compile(r"\bACTOR_MAP\b")


_DPD_RAW_RE = re.compile(
    r'DPD_RAW\s+#(?P<seq>\d+).*?\bcalc=(?P<calc>[-\d.eE+]+)\s+'
    r'atkScale=(?P<atk_scale>[-\d.eE+]+)\s+blocked=(?P<blocked>\d+)\s+'
    r'damageType=(?P<damage_type>0x[0-9A-Fa-f]+|\S+)\s+'
    r'decorateMask=(?P<decorate_mask>0x[0-9A-Fa-f]+|\S+)\s+'
    r'collider="(?P<collider>[^"]*)"\s+'
    r'atkZones=\[(?P<atk_zones>[^\]]*)\]\s+defZones=\[(?P<def_zones>[^\]]*)\]'
)


_BASELINE_RE = re.compile(r"\bBASELINE\s+#(?P<seq>\d+)\s+(?P<body>.*)")


_PKT_MOD_RE = re.compile(r"\bPKT_MOD\s+#(?P<seq>\d+)\s+atk=\[(?P<atk>[^\]]*)\]\s+def=\[(?P<def>[^\]]*)\]")


_PKT_ATTR_RE = re.compile(r"\bPKT_ATTR\s+#(?P<seq>\d+)\s+atk=\[(?P<atk>[^\]]*)\]\s+def=\[(?P<def>[^\]]*)\]")


_BASELINE_KV_RE = re.compile(r"(-?\d+)=([-\d.eE+]+)")


def _action_graph_skill_candidates(
    skill_key: str,
    *,
    character_key: str | None,
) -> list[dict[str, Any]]:
    return []

    rows = _load_skill_action_graph_candidate_map().get(str(skill_key or ""), [])
    if not rows:
        return []
    if not character_key:
        return rows
    character_prefix = f"{character_key}_"
    return [
        row
        for row in rows
        if str(row.get("candidate_skill_id") or "").startswith(character_prefix)
    ]


def _skill_mapping_info(
    skill_key: str,
    *,
    character_key: str | None,
    target_enemy_key: str | None,
    damage_element: str | None,
    original_template_int_id: int | None,
    ts_ms: int,
    recent_actor_maps_by_char: dict[str, list[dict[str, Any]]],
    recent_skill_casts_by_char: dict[str, list[dict[str, Any]]],
    recent_numeric_buffs_by_source: dict[str, list[dict[str, Any]]],
    loadout_skill_ids_by_char: dict[str, set[str]],
    action_id: int | None = None,
    damage_unit_index: int | None = None,
    template_type: str | None = None,
) -> dict[str, Any]:
    canonical = _canonical_hit_skill_id_from_cast_context(
        skill_key, character_key, ts_ms, target_enemy_key=target_enemy_key,
        recent_skill_casts_by_char={}, recent_numeric_buffs_by_source={},
        action_id=action_id, damage_unit_index=damage_unit_index, template_type=template_type,
    ) or _canonical_hit_skill_id(skill_key, character_key)
    mapped = bool(canonical and canonical != skill_key)
    explicit = bool(canonical and canonical not in {"unknown_skill", "?"}
                    and not _runtime_skill_number(canonical))
    return {
        "status": "mapped" if mapped else "static" if explicit else "unmapped",
        "status_label": "已映射" if mapped else "静态 ID" if explicit else "未知",
        "raw_skill_key": skill_key,
        "canonical_skill_id": canonical if mapped or explicit else None,
        "evidence_kind": "NumIdStrTable" if mapped else "packet_string_id" if explicit else None,
        "candidates": [],
        "action_graph_candidates": [],
    }


def _parse_zone_values(blob: str | None) -> list[float | None]:
    return _parse_runtime_zone_values(blob)


def _parse_hex_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value, 16) if value.lower().startswith("0x") else int(value)
    except ValueError:
        return None


def _parse_dpd_raw_line(line: str) -> dict[str, Any] | None:
    parsed = _parse_runtime_dpd_raw_line(line)
    if parsed is None:
        return None
    return {
        **parsed,
        "damage_type": _parse_hex_int(parsed['damage_type_raw']),
        "decorate_mask": _parse_hex_int(parsed['decorate_mask_raw']),
    }


def _parse_baseline_line(line: str) -> tuple[int, dict[int, float]] | None:
    match = _BASELINE_RE.search(line)
    if not match:
        return None
    values = {
        int(key): _coerce_float(value)
        for key, value in _BASELINE_KV_RE.findall(match.group("body"))
    }
    return int(match.group("seq")), values


def _parse_packet_modifier_line(line: str) -> tuple[int, list[str], list[str]] | None:
    match = _PKT_MOD_RE.search(line)
    if not match:
        return None
    atk = [item for item in match.group("atk").split() if item]
    defender = [item for item in match.group("def").split() if item]
    return int(match.group("seq")), atk, defender


def _parse_packet_attr_line(line: str) -> tuple[int, list[str], list[str]] | None:
    match = _PKT_ATTR_RE.search(line)
    if not match:
        return None
    atk = [item for item in match.group("atk").split() if item]
    defender = [item for item in match.group("def").split() if item]
    return int(match.group("seq")), atk, defender


def _packet_attr_allowed_effects(tokens: list[str] | None) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for token in tokens or []:
        head = str(token).split(":", 1)[0]
        try:
            attr_type = int(head)
        except (TypeError, ValueError):
            continue
        mapping = _ATTR_TYPE_TO_EFFECT.get(attr_type)
        if mapping is None:
            continue
        zone, element = mapping
        allowed.add((str(zone), str(element or "all")))
    return allowed


def _format_ts_ms(ts_ms: int) -> str:
    millis = ts_ms % 1000
    total_seconds = ts_ms // 1000
    seconds = total_seconds % 60
    total_minutes = total_seconds // 60
    minutes = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _round4(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _dpd_bucket_for_zone(zone: str, dpd_raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if not dpd_raw:
        return None
    bucket = DPD_ZONE_BUCKETS.get(zone)
    if bucket is None:
        return None
    side, index = bucket
    values = dpd_raw.get("atk_zones") if side == "atk" else dpd_raw.get("def_zones")
    values = values or []
    if len(values) > index:
        return {"side": side, "index": index, "value": values[index]}
    return None


def _sort_zones(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: (ZONE_ORDER.get(str(item.get("zone")), 99), str(item.get("zone"))))


def _record_applicable_effect(
    *,
    window: dict[str, Any],
    effect: dict[str, Any],
    scope: str,
    rdps_credit: float | None = None,
) -> dict[str, Any]:
    source_key = window.get("source_character_key")
    raw_source_key = window.get("raw_source_character_key")
    return {
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
        "zone": str(effect.get("zone") or ""),
        "zone_label": ZONE_LABELS.get(str(effect.get("zone") or ""), str(effect.get("zone") or "")),
        "element": str(effect.get("element") or "all"),
        "rate": _round4(float(effect.get("rate") or 0.0)),
        "rdps_credit": _round4(rdps_credit),
    }


def _record_dpd_self_residual(
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
        "zone_label": ZONE_LABELS.get(zone, zone),
        "element": str(hit.get("damage_element") or "all"),
        "rate": _round4(rate),
        "rdps_credit": None,
    }


def _record_baseline_self(
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
    label = _ATTR_TYPE_BUFF_LABELS.get(attr_type) or ZONE_LABELS.get(zone, zone)
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
        "zone_label": ZONE_LABELS.get(zone, zone),
        "element": element,
        "rate": _round4(rate),
        "rdps_credit": None,
        "baseline_final": _round4(final_value),
        "baseline_captured": _round4(captured),
    }


def _explain_hit(
    hit: dict[str, Any],
    buff_windows: list[dict[str, Any]],
    buff_records_by_uid: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    allocation = _allocate_rdps_for_hit(
        hit,
        buff_windows,
        include_debug=True,
        buff_records_by_uid=buff_records_by_uid,
    )
    hit["zones"] = allocation.get("zones") or []
    hit["ignored_effects"] = allocation.get("ignored_effects") or []
    hit["product_external_multiplier"] = allocation.get("product_external_multiplier")
    hit["attacker_share"] = allocation.get("attacker_share")
    hit["external_pool"] = allocation.get("external_pool")
    hit["rdps_contributions"] = allocation.get("contributions_list") or []
    hit["external_sources"] = allocation.get("external_sources") or []
    hit["zone_summary"] = str(allocation.get("zone_summary") or "")
    hit["buff_source_summary"] = str(allocation.get("buff_source_summary") or "")
    hit["packet_modifier_uids"] = allocation.get("packet_modifier_uids") or {"attacker": [], "defender": []}
    hit["packet_modifier_details"] = allocation.get("packet_modifier_details") or []
    return hit
