"""Entity stat decoding, time-indexed snapshots and hit evidence attachment."""
from __future__ import annotations

from parser_core.ingestion.fields import (
    _coerce_optional_float,
    _coerce_optional_int,
    _extract_fields,
    _parse_prefixed_timestamp_ms,
)
import re
from typing import Any

from parser_core.critical_context import update_critical_observation
from parser_core.ingestion.state import IngestionState


def entity_stats_snapshot(template, kind, level, observations, *, timestamp_ms, attribute_list_present):
    """Fold already decoded attribute observations using the shared conflict rules."""
    attrs, basic_attrs, seen, invalid, invalid_tokens = {}, {}, set(), set(), []
    for attr_type, value, basic_value, invalid_token in observations:
        if attr_type is None:
            if invalid_token is not None:
                invalid_tokens.append(invalid_token)
            continue
        if attr_type in seen or value is None:
            invalid.add(attr_type)
            attrs.pop(attr_type, None)
            basic_attrs.pop(attr_type, None)
        elif attr_type not in invalid:
            attrs[attr_type] = value
            if basic_value is not None:
                basic_attrs[attr_type] = basic_value
        seen.add(attr_type)
    return {'template': template, 'kind': kind, 'level': level, 'attrs': attrs, 'basic_attrs': basic_attrs,
            'ts_ms': timestamp_ms, 'invalid_attr_types': sorted(invalid), 'invalid_attr_tokens': invalid_tokens,
            'attribute_list_present': attribute_list_present}


def _parse_entity_stats_snapshot(raw_line: str) -> tuple[str, dict[str, Any]] | None:
    if " ENTITY_STATS " not in raw_line:
        return None
    fields = _extract_fields(raw_line)
    entity_id = str(fields.get("id") or "")
    if not re.fullmatch(r"[1-9]\d*", entity_id):
        return None
    observations = []
    attrs_match = re.search(r"\battrs=\[(?P<attrs>[^\]]*)\]", raw_line)
    attrs_blob = attrs_match.group("attrs") if attrs_match else ""
    for token in attrs_blob.split():
        attr_type_text, separator, raw_values = token.partition(":")
        if not separator:
            observations.append((None, None, None, token))
            continue
        attr_type = _coerce_optional_int(attr_type_text)
        raw_value, basic_separator, raw_basic = raw_values.partition('/')
        value = _coerce_optional_float(raw_value)
        basic_value = _coerce_optional_float(raw_basic) if basic_separator else None
        observations.append((attr_type, value, basic_value, token if attr_type is None else None))
    return entity_id, entity_stats_snapshot(fields.get('template'), fields.get('kind'),
        _coerce_optional_int(fields.get('level')), observations,
        timestamp_ms=_parse_prefixed_timestamp_ms(raw_line), attribute_list_present=attrs_match is not None)


def _entity_stats_snapshot_at(
    timelines: dict[str, list[tuple[int, dict[str, Any]]]],
    entity_id: str | None,
    ts_ms: int,
) -> dict[str, Any] | None:
    rows = timelines.get(str(entity_id or ""))
    if not rows:
        return None
    chosen: dict[str, Any] | None = None
    chosen_ts: int | None = None
    for row_ts, row in rows:
        if row_ts <= ts_ms and (chosen_ts is None or row_ts >= chosen_ts):
            chosen, chosen_ts = row, row_ts
    return chosen


def _attach_target_entity_stats(hit: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
    if not isinstance(snapshot, dict):
        return
    if not hit.get("target_enemy_key") or snapshot.get("template") != hit.get("target_enemy_key"):
        hit["rdps_unresolved_target_binding"] = True
        return
    attrs = snapshot.get("attrs") if isinstance(snapshot.get("attrs"), dict) else {}
    hit["target_stats_snapshot_ts_ms"] = snapshot.get("ts_ms")
    hit["target_stats_snapshot_line_no"] = snapshot.get("line_no")
    hit["target_stats_invalid_attr_types"] = list(snapshot.get("invalid_attr_types") or [])
    defense = attrs.get(3)
    if defense is not None:
        hit["target_defense"] = defense
        hit["target_defense_source"] = "ENTITY_STATS.attr3"
    resistance_scalar_attrs = {
        # Native BattleFormula._GetDamageTypeResistanceValue multiplies the
        # resistance-point factor by DamageTakenScalar (enum 4-7, 48, 60).
        "physical": 4,
        "fire": 5,
        "pulse": 6,
        "cryst": 7,
        "natural": 48,
        "ether": 60,
    }
    resistance_point_attrs = {
        "physical": 94,
        "natural": 95,
        "cryst": 96,
        "pulse": 97,
        "fire": 98,
        "ether": 99,
    }
    scalars = {element: attrs[attr_type] for element, attr_type in resistance_scalar_attrs.items() if attrs.get(attr_type) is not None}
    points = {element: attrs[attr_type] for element, attr_type in resistance_point_attrs.items() if attrs.get(attr_type) is not None}
    if scalars:
        hit["target_resistance_scalars"] = scalars
        hit["target_resistance_source"] = "ENTITY_STATS.attr4_7_48_60"
    if points:
        hit["target_resistance_points"] = points
        hit["target_resistance_points_source"] = "ENTITY_STATS.attr94_99"


def _attach_attacker_entity_stats(hit: dict[str, Any], snapshot: dict[str, Any] | None) -> None:
    if not isinstance(snapshot, dict):
        return
    if snapshot.get("template") != hit.get("character_key") or snapshot.get("kind") != "character":
        hit["rdps_unresolved_attacker_binding"] = True
        return
    attrs = snapshot.get("attrs") if isinstance(snapshot.get("attrs"), dict) else {}
    if not attrs:
        return
    hit["attacker_stats_attrs"] = dict(attrs)
    hit['attacker_stats_basic_attrs'] = dict(snapshot.get('basic_attrs') or {})
    hit['attacker_stats_level'] = snapshot.get('level')
    hit["attacker_stats_source"] = "ENTITY_STATS"
    hit["attacker_stats_snapshot_ts_ms"] = snapshot.get("ts_ms")
    hit["attacker_stats_snapshot_line_no"] = snapshot.get("line_no")
    hit["attacker_stats_observed_attr_count"] = len(attrs)
    hit["attacker_stats_invalid_attr_types"] = list(snapshot.get("invalid_attr_types") or [])


def apply_entity_snapshot(ingestion: IngestionState, entity_id: str, snapshot: dict,
                          line_no: int, ts_ms: int, *, partial=False) -> None:
    snapshot['ts_ms'] = ts_ms
    if not partial:
        snapshot['line_no'] = line_no
        ingestion.entity_stats_timelines[entity_id].append((ts_ms, snapshot))
    update_critical_observation(ingestion.critical_stats_by_actor, entity_id, snapshot, line_no, partial=partial)


def consume_entity_observation(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    entity_stats_snapshot = _parse_entity_stats_snapshot(raw_line)
    if entity_stats_snapshot is not None:
        entity_id, snapshot = entity_stats_snapshot
        apply_entity_snapshot(ingestion, entity_id, snapshot, line_no, ts_ms)
        return True

    if " ENTITY_ATTR_UPDATE " in raw_line:
        update = _parse_entity_stats_snapshot(raw_line.replace(" ENTITY_ATTR_UPDATE ", " ENTITY_STATS ", 1))
        if update is not None:
            entity_id, snapshot = update
            apply_entity_snapshot(ingestion, entity_id, snapshot, line_no, ts_ms, partial=True)
        return True
    return False
