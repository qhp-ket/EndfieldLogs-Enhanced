"""Explanation phase of per-hit allocation."""
from __future__ import annotations

from collections import defaultdict
from math import log
from parser_core.allocation.arts_strength import _arts_strength_damage_multiplier
from parser_core.allocation.context import HitAllocation
from parser_core.allocation.debug import _RDPS_DEBUG_ZONE_ORDER
from parser_core.allocation.debug import _sort_rdps_debug_zones
from parser_core.allocation.packet_evidence import _dpd_bucket_value_for_zone
from parser_core.allocation.shares import _round4
from parser_core.allocation.static_loadout import _RDPS_DEBUG_ZONE_LABELS
from parser_core.catalog.names import _resolve_character_name
from parser_core.effects.labels import _collect_buff_labels
from parser_core.effects.packet_mapping import _DPD_ZONE_BUCKETS
from typing import Any


def project_allocation_explanation(state: HitAllocation) -> dict[str, Any]:
    zone_external_share: dict[str, float] = defaultdict(float)
    log_total = sum(log(value) for value in state.m_values.values()) if state.product_external > 1.0 else 0.0
    if log_total > 0 and state.external_pool > 0:
        for zone in state.external_by_zone:
            if zone not in state.m_values:
                continue
            zone_external_share[zone] = state.external_pool * (log(state.m_values[zone]) / log_total)

    zones: list[dict[str, Any]] = []
    for zone in sorted(
        set(state.self_by_zone) | set(state.self_factor_by_zone) | set(state.external_by_zone),
        key=lambda key: (_RDPS_DEBUG_ZONE_ORDER.get(key, 99), key),
    ):
        self_rate = (state.self_factor_by_zone.get(zone, 1.0) - 1.0
                     if zone.startswith('prod_') else state.self_by_zone.get(zone, 0.0))
        external_rate = state.external_sum_by_zone.get(
            zone,
            sum(rate for _, rate, _ in state.external_by_zone.get(zone, [])),
        )
        total_rate = self_rate + external_rate
        total_multiplier = (
            state.self_factor_by_zone.get(zone, 1.0) * state.m_values.get(zone, 1.0)
            if zone.startswith('prod_')
            else
            state.resistance_numerator / 100.0
            if zone == 'res' and state.resistance_numerator is not None
            else
            _arts_strength_damage_multiplier(total_rate) ** (state.hit.get('arts_strength_damage_factor_count') or 1)
            if zone == "arts_strength"
            else 1.0 + total_rate
        )
        if zone.startswith('prod_'):
            total_rate = total_multiplier - 1.0
        bucket_value = _dpd_bucket_value_for_zone(zone, state.hit.get("dpd_raw"))
        zones.append(
            {
                "zone": zone,
                "zone_label": _RDPS_DEBUG_ZONE_LABELS.get(zone, zone),
                "self_rate": _round4(self_rate),
                "external_rate": _round4(external_rate),
                "total_rate": _round4(total_rate),
                "total_multiplier": _round4(total_multiplier),
                "external_multiplier": _round4(state.m_values.get(zone, 1.0)),
                **({'rate_unit': 'resistance_points', 'effective_resistance': state.effective_resistance,
                    'effective_resistance_source': state.resistance_source,
                    'without_external_resistance': state.effective_resistance + external_rate}
                   if zone == 'res' and state.effective_resistance is not None else {}),
                "zone_external_share": _round4(zone_external_share.get(zone, 0.0)),
                "dpd_bucket": (
                    {
                        "side": _DPD_ZONE_BUCKETS[zone][0],
                        "index": _DPD_ZONE_BUCKETS[zone][1],
                        "value": _round4(bucket_value),
                    }
                    if zone in _DPD_ZONE_BUCKETS and bucket_value is not None
                    else None
                ),
                "contributors": sorted(
                    state.contributors_by_zone.get(zone, []),
                    key=lambda item: (
                        0 if item.get("scope") == "external" else 1,
                        -float(item.get("rate") or 0.0),
                        str(item.get("source_character_name") or ""),
                        str(item.get("event_key") or ""),
                    ),
                ),
            }
        )

    external_sources: dict[str, dict[str, Any]] = {}
    for contributors in state.external_by_zone.values():
        for source_key, _rate, record in contributors:
            current = external_sources.setdefault(
                source_key,
                {
                    "character_key": source_key,
                    "character_name": (record or {}).get("source_character_name") or _resolve_character_name(source_key) or source_key,
                    "effect_count": 0,
                    "rdps_credit": 0.0,
                },
            )
            current["effect_count"] += 1
            if record is not None:
                current["rdps_credit"] += float(record.get("rdps_credit") or 0.0)

    modifier_details: list[dict[str, Any]] = []
    record_index = state.buff_records_by_uid if isinstance(state.buff_records_by_uid, dict) else {}
    for side, uids in (("attacker", sorted(state.attacker_modifier_uids)), ("defender", sorted(state.defender_modifier_uids))):
        for uid in uids:
            candidates = record_index.get(uid) or []
            if isinstance(candidates, dict):
                candidates = [candidates]
            stamp = (state.hit_ts_ms, state.hit_line_no)
            matched_records = [row for row in candidates
                if stamp >= (int(row.get('ts_ms') or 0), int(row.get('line_no') or 0))
                and (row.get('end_ts_ms') is None or stamp < (int(row['end_ts_ms']), int(row.get('end_line_no') or 0)))
                and (row.get('snapshot_end_ts_ms') is None or stamp < (int(row['snapshot_end_ts_ms']), int(row.get('snapshot_end_line_no') or 0)))
                and (state.hit_line_no or state.hit_ts_ms not in (row.get('ts_ms'), row.get('end_ts_ms'), row.get('snapshot_end_ts_ms')))]
            record = matched_records[0] if len(matched_records) == 1 else None
            if not isinstance(record, dict):
                modifier_details.append(
                    {
                        "side": side,
                        "uid": uid,
                        "event_key": "",
                        "event_name": "",
                        "source_character_name": "",
                        "target_name": "",
                        "bb_values": {},
                    }
                )
                continue
            target_name = (
                record.get("target_character_name")
                or record.get("target_enemy_name")
                or record.get("owner_raw")
                or ""
            )
            modifier_details.append(
                {
                    "side": side,
                    "uid": uid,
                    "event_key": record.get("event_key"),
                    "event_name": " / ".join(_collect_buff_labels(record)) or record.get("event_key") or "",
                    "source_character_key": record.get("source_character_key"),
                    "source_character_name": record.get("source_character_name"),
                    "target_key": record.get("target_character_key") or record.get("target_enemy_key"),
                    "target_name": target_name,
                    "bb_values": dict(record.get("bb_values") or {}),
                    "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                }
            )

    state.result.update(
        {
            "zones": _sort_rdps_debug_zones(zones),
            "ignored_effects": state.ignored_effects,
            "product_external_multiplier": _round4(state.product_external),
            "attacker_share": _round4(state.attacker_share),
            "external_pool": _round4(state.external_pool),
            "external_sources": sorted(
                (
                    {
                        **value,
                        "rdps_credit": _round4(value["rdps_credit"]),
                    }
                    for value in external_sources.values()
                ),
                key=lambda item: (-float(item.get("rdps_credit") or 0.0), str(item.get("character_name") or "")),
            ),
            "zone_summary": " / ".join(
                f"{zone['zone_label']} x{float(zone['external_multiplier']):.4f}"
                for zone in _sort_rdps_debug_zones(zones)
                if float(zone.get("external_multiplier") or 1.0) > 1.0001
            ),
            "buff_source_summary": " / ".join(
                f"{source['character_name']} +{float(source['rdps_credit']):.1f}"
                for source in sorted(
                    (
                        {
                            **value,
                            "rdps_credit": _round4(value["rdps_credit"]),
                        }
                        for value in external_sources.values()
                    ),
                    key=lambda item: (-float(item.get("rdps_credit") or 0.0), str(item.get("character_name") or "")),
                )
                if float(source.get("rdps_credit") or 0.0) > 0.0001
            ),
            "packet_modifier_uids": {
                "attacker": sorted(state.attacker_modifier_uids),
                "defender": sorted(state.defender_modifier_uids),
            },
            "packet_modifier_details": modifier_details,
        }
    )
    return state.result
