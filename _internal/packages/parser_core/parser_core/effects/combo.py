"""Build observed combo consume windows and hidden-rule evidence."""
from __future__ import annotations

from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.labels import _GENERIC_COMBO_TRIGGER_BUFF_ID
from parser_core.effects.lifecycle import _buff_record_end_ts_ms
from parser_core.effects.registry import _rdps_registry_verified_effect_entry
from parser_core.ingestion.hits import _COMBO_CONSUME_SKILL_ALIASES
import re
from typing import Any


_HIDDEN_COMBO_RULES = (
    {
        "rule_key": "karin_hidden_combo",
        "buff_patterns": (
            re.compile(r"buff_chr_0019_karin_talent_2_combo", re.IGNORECASE),
            re.compile(r"buff_chr_0019_karin_potential_5_combo", re.IGNORECASE),
        ),
        "skill_group_rates": {
            1: 0.30,
            2: 0.20,
        },
        "cast_window_ms": 5000,
    },
)


_GENERIC_COMBO_IMBUE_BUFF_IDS = {
    "buff_common_affixes_skillimbue",
    "buff_common_affixes_skillimbue_atk",
}


_COMBO_TOTAL_RATES_BY_GROUP_TYPE = {
    1: (0.30, 0.45, 0.60, 0.75),
    2: (0.20, 0.30, 0.40, 0.50),
}


_COMBO_TRIGGER_GROUP_WINDOW_MS = 20


_COMBO_CONSUME_MAX_WINDOW_MS = 5000


def _resolve_combo_consume_context(hit: dict[str, Any]) -> tuple[int, str] | None:
    skill_key = str(hit.get("skill_key") or "")
    alias = _COMBO_CONSUME_SKILL_ALIASES.get(skill_key)
    if alias is not None:
        return int(alias["group_type"]), str(alias["family_skill_key"])

    try:
        group_type = int(hit.get("skill_group_type"))
    except (TypeError, ValueError):
        group_type = None
    family_key = str(hit.get("skill_family_key") or skill_key)
    if group_type in {1, 2} and family_key:
        return group_type, family_key

    return None


def _combo_marginal_layer_rates(group_type: int, stack_count: int) -> list[float]:
    total_rates = _COMBO_TOTAL_RATES_BY_GROUP_TYPE.get(group_type)
    if not total_rates or stack_count <= 0:
        return []
    capped_count = min(int(stack_count), len(total_rates))
    marginal_rates: list[float] = []
    previous_total = 0.0
    for total_rate in total_rates[:capped_count]:
        marginal_rates.append(max(0.0, float(total_rate) - previous_total))
        previous_total = float(total_rate)
    return marginal_rates


def _matches_hidden_combo_rule(buff_id: str) -> dict[str, Any] | None:
    for rule in _HIDDEN_COMBO_RULES:
        if any(pattern.search(buff_id) for pattern in rule["buff_patterns"]):
            return rule
    return None


def _build_hidden_combo_windows(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
    *,
    battle_end_ms: int,
) -> list[dict[str, Any]]:
    combo_windows: list[dict[str, Any]] = []
    ordered_hits = sorted(hits, key=lambda item: item["ts_ms"])

    for buff_record in buff_starts:
        source_key = buff_record.get("source_character_key")
        target_key = buff_record.get("target_character_key")
        buff_id = _normalize_buff_id(buff_record.get("event_key"))
        rule = _matches_hidden_combo_rule(buff_id)
        if not source_key or not target_key or rule is None:
            continue

        buff_start_ms = int(buff_record["ts_ms"])
        buff_end_ms = _buff_record_end_ts_ms(buff_record, battle_end_ms)

        for hit in ordered_hits:
            if hit["character_key"] != target_key:
                continue
            if not (buff_start_ms <= hit["ts_ms"] <= buff_end_ms):
                continue

            combo_context = _resolve_combo_consume_context(hit)
            if combo_context is None:
                continue
            combo_group_type, skill_family_key = combo_context
            rate = rule["skill_group_rates"].get(combo_group_type)
            if rate is None or rate <= 0:
                continue

            combo_windows.append(
                {
                    "start_ts_ms": hit["ts_ms"],
                    "end_ts_ms": min(hit["ts_ms"] + int(rule["cast_window_ms"]), battle_end_ms),
                    "duration_ms": min(int(rule["cast_window_ms"]), max(battle_end_ms - hit["ts_ms"], 1)),
                    "source_character_key": source_key,
                    "source_character_name": buff_record.get("source_character_name"),
                    "target_character_key": target_key,
                    "target_character_name": buff_record.get("target_character_name"),
                    "target_player_key": target_key,
                    "target_enemy_key": None,
                    "event_key": f"{buff_id}::{skill_family_key}",
                    "event_name": "连击增伤",
                    "zone_effects": [{"zone": "combo", "element": "all", "rate": rate}],
                    "skill_family_key": skill_family_key,
                }
            )
            break

    return combo_windows


def _build_combo_consume_windows(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
    *,
    battle_end_ms: int,
) -> list[dict[str, Any]]:
    combo_windows: list[dict[str, Any]] = []
    ordered_hits = sorted(hits, key=lambda item: item["ts_ms"])
    trigger_records: list[dict[str, Any]] = []
    consume_records: list[dict[str, Any]] = []

    for buff_record in buff_starts:
        buff_id = _normalize_buff_id(buff_record.get("event_key"))
        source_key = buff_record.get("source_character_key")
        target_key = buff_record.get("target_character_key")
        if not source_key or not target_key:
            continue

        if buff_id in _GENERIC_COMBO_IMBUE_BUFF_IDS:
            consume_records.append(
                {
                    "buff_record": buff_record,
                    "source_key": source_key,
                    "target_key": target_key,
                    "start_ms": int(buff_record["ts_ms"]),
                }
            )
            continue

        if buff_id != _GENERIC_COMBO_TRIGGER_BUFF_ID:
            continue

        buff_start_ms = int(buff_record["ts_ms"])
        buff_end_ms = _buff_record_end_ts_ms(buff_record, battle_end_ms)
        trigger_records.append(
            {
                "buff_record": buff_record,
                "source_key": source_key,
                "target_key": target_key,
                "start_ms": buff_start_ms,
                "end_ms": buff_end_ms,
            }
        )

    trigger_records.sort(
        key=lambda record: (
            int(record["start_ms"]),
            str(record["source_key"] or ""),
            str(record["target_key"] or ""),
        )
    )
    trigger_groups: list[dict[str, Any]] = []
    for record in trigger_records:
        group = next(
            (
                candidate
                for candidate in reversed(trigger_groups)
                if candidate["source_key"] == record["source_key"]
                and abs(int(record["start_ms"]) - int(candidate["start_ms"])) <= _COMBO_TRIGGER_GROUP_WINDOW_MS
            ),
            None,
        )
        if group is None:
            group = {
                "source_key": record["source_key"],
                "start_ms": record["start_ms"],
                "records": [],
            }
            trigger_groups.append(group)
        group["records"].append(record)

    indexed_hits = list(enumerate(ordered_hits))
    matched_layers: list[dict[str, Any]] = []
    for group in trigger_groups:
        group_start_ms = min(int(record["start_ms"]) for record in group["records"])
        group_end_ms = max(int(record["end_ms"]) for record in group["records"])
        group_source_key = group["source_key"]

        consume_candidates = [
            record
            for record in consume_records
            if record["source_key"] == group_source_key
            and group_start_ms < int(record["start_ms"]) <= group_end_ms + _COMBO_TRIGGER_GROUP_WINDOW_MS
        ]
        if not consume_candidates:
            continue

        consume_record = min(
            consume_candidates,
            key=lambda record: (int(record["start_ms"]), str(record["target_key"] or "")),
        )
        consume_ts_ms = int(consume_record["start_ms"])
        target_key = consume_record["target_key"]
        source_key = consume_record["source_key"]

        hit_candidate: tuple[int, dict[str, Any], tuple[int, str]] | None = None
        for hit_index, hit in indexed_hits:
            if hit["character_key"] != target_key:
                continue
            if not (consume_ts_ms <= hit["ts_ms"] <= consume_ts_ms + _COMBO_CONSUME_MAX_WINDOW_MS):
                continue
            combo_context = _resolve_combo_consume_context(hit)
            if combo_context is None:
                continue
            hit_candidate = (hit_index, hit, combo_context)
            break

        if hit_candidate is None:
            continue

        hit_index, _hit, combo_context = hit_candidate
        combo_group_type, skill_family_key = combo_context
        matched_layers.append(
            {
                "consume_record": consume_record,
                "consume_ts_ms": consume_ts_ms,
                "target_key": target_key,
                "source_key": source_key,
                "source_record": group["records"][0]["buff_record"],
                "group_start_ms": group_start_ms,
                "hit_index": hit_index,
                "combo_group_type": combo_group_type,
                "skill_family_key": skill_family_key,
            }
        )

    consume_groups: dict[tuple[int, str, int, int, str], list[dict[str, Any]]] = {}
    for layer in matched_layers:
        group_key = (
            int(layer["consume_ts_ms"]),
            str(layer["target_key"] or ""),
            int(layer["hit_index"]),
            int(layer["combo_group_type"]),
            str(layer["skill_family_key"] or ""),
        )
        consume_groups.setdefault(group_key, []).append(layer)

    for layers in consume_groups.values():
        layers.sort(key=lambda layer: (int(layer["group_start_ms"]), str(layer["source_key"] or "")))
        marginal_rates = _combo_marginal_layer_rates(int(layers[0]["combo_group_type"]), len(layers))
        if not marginal_rates:
            continue

        capped_layers = layers[: len(marginal_rates)]
        total_rate = round(sum(marginal_rates), 6)
        rates_by_source: dict[str, dict[str, Any]] = {}
        for layer, rate in zip(capped_layers, marginal_rates):
            if rate <= 0:
                continue
            source_key = str(layer["source_key"] or "")
            if not source_key:
                continue
            bucket = rates_by_source.setdefault(
                source_key,
                {
                    "rate": 0.0,
                    "layers": [],
                    "first_layer": layer,
                },
            )
            bucket["rate"] = float(bucket["rate"]) + float(rate)
            bucket["layers"].append(layer)

        for source_key, bucket in rates_by_source.items():
            rate = round(float(bucket["rate"]), 6)
            if rate <= 0:
                continue
            first_layer = bucket["first_layer"]
            consume_record = first_layer["consume_record"]
            consume_buff_record = consume_record["buff_record"]
            source_buff_record = first_layer["source_record"]
            consume_ts_ms = int(first_layer["consume_ts_ms"])
            target_key = str(first_layer["target_key"] or "")
            skill_family_key = str(first_layer["skill_family_key"] or "")
            window_end_ms = min(consume_ts_ms + _COMBO_CONSUME_MAX_WINDOW_MS, battle_end_ms)
            projection_key = f"{_GENERIC_COMBO_TRIGGER_BUFF_ID}::{skill_family_key}"
            approval = _rdps_registry_verified_effect_entry({
                'event_key': projection_key, 'source_character_key': source_key, 'target_character_key': target_key})
            if not approval or not any(spec.get('zone') == 'combo' and spec.get('element') == 'all'
                                       for spec in approval.get('effects') or []):
                continue
            combo_windows.append(
                {
                    "start_ts_ms": consume_ts_ms,
                    "end_ts_ms": window_end_ms,
                    "duration_ms": max(window_end_ms - consume_ts_ms, 1),
                    "source_character_key": source_key,
                    "source_character_name": source_buff_record.get("source_character_name"),
                    "target_character_key": target_key,
                    "target_character_name": consume_buff_record.get("target_character_name"),
                    "target_player_key": target_key,
                    "target_enemy_key": None,
                    "event_key": projection_key,
                    "event_name": "连击增伤",
                    "zone_effects": [{"zone": "combo", "element": "all", "rate": rate,
                                      "external_rdps_allowed": True,
                                      "rdps_whitelist_keys": list(approval.get('_rdps_whitelist_keys') or [])}],
                    "skill_family_key": skill_family_key,
                    "combo_stack_count": len(capped_layers),
                    "combo_layer_count": len(bucket["layers"]),
                    "combo_total_rate": total_rate,
                    "combo_rate_model": "ordered_marginal_stack",
                }
            )

    return combo_windows
