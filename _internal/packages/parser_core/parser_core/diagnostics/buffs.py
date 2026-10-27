"""Buff window audit and explanatory labels using shared effect rules."""
from __future__ import annotations
from typing import Any
from parser_core.effects.windows import _apply_buff_stack_limits
from parser_core.effects.enemy_status import _apply_enemy_status_bb_overrides
from parser_core.effects.stacking_rules import _buff_stack_limit
from parser_core.effects.classification import _equip_buff_matches_active_suits
from parser_core.effects.imbue import _build_special_combo_windows
from parser_core.effects.labels import _collect_buff_labels
from parser_core.effects.specifications import _collect_zone_effects
from parser_core.effects.windows import _dedupe_mirrored_buff_windows
from parser_core.effects.specifications import _extract_dynamic_effect_specs
from parser_core.effects.classification import _is_noise_buff
from parser_core.effects.windows import _merge_buff_windows
from parser_core.effects.lifecycle import _normalize_buff_duration_ms
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.packet_mapping import _packet_mapping_stack_limit
from parser_core.reporting.buffs import _packet_buff_semantic_candidates
from parser_core.effects.packet_mapping import _classify_packet_buff_record
from parser_core.effects.lifecycle import _resolve_weapon_buff_sources
from parser_core.ingestion.fields import _safe_positive_rate
from parser_core.effects.classification import _should_ignore_rate_buff
from parser_core.effects.classification import _weapon_buff_matches_active_weapon
from parser_core.diagnostics.explanation import (
    ZONE_LABELS,
    _format_ts_ms,
)


def _apply_enemy_target_bb_duration_override(record: dict[str, Any]) -> None:
    _apply_enemy_status_bb_overrides(record, context_enemy_hint=None)


def _build_buff_windows(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
    *,
    battle_end_ms: int,
    active_suits_by_char: dict[str, set[str]] | None = None,
    active_weapons_by_char: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    _resolve_weapon_buff_sources(buff_starts)

    buff_windows: list[dict[str, Any]] = []
    for buff_record in buff_starts:
        labels = _collect_buff_labels(buff_record)
        zone_effects = _collect_zone_effects(buff_record)
        dynamic_effects = _extract_dynamic_effect_specs(buff_record)
        if not zone_effects and not dynamic_effects:
            continue
        if not _equip_buff_matches_active_suits(
            buff_record.get("event_key"),
            buff_record.get("source_character_key"),
            active_suits_by_char,
        ):
            continue
        if not _weapon_buff_matches_active_weapon(
            buff_record.get("event_key"),
            buff_record.get("source_character_key"),
            active_weapons_by_char,
        ):
            continue

        start_ts_ms = int(buff_record["ts_ms"])
        buff_duration_ms = _normalize_buff_duration_ms(
            start_ts_ms,
            event_key=buff_record.get("event_key"),
            end_ts_ms=buff_record.get("end_ts_ms"),
            raw_duration_ms=buff_record.get("raw_duration_ms"),
            battle_end_ms=battle_end_ms,
        )
        buff_windows.append(
            {
                "start_ts_ms": start_ts_ms,
                "start_line_no": buff_record.get("line_no"),
                "start_time": _format_ts_ms(start_ts_ms),
                "end_ts_ms": start_ts_ms + buff_duration_ms,
                "end_time": _format_ts_ms(start_ts_ms + buff_duration_ms),
                "duration_ms": buff_duration_ms,
                "uid": buff_record.get("uid"),
                "source_character_key": buff_record.get("source_character_key"),
                "source_character_name": buff_record.get("source_character_name"),
                "raw_source_character_key": buff_record.get("raw_source_character_key"),
                "raw_source_character_name": buff_record.get("raw_source_character_name"),
                "raw_source": buff_record.get("raw_source"),
                "target_character_key": buff_record.get("target_character_key")
                or buff_record.get("target_enemy_key"),
                "target_character_name": buff_record.get("target_character_name")
                or buff_record.get("target_enemy_name"),
                "target_player_key": buff_record.get("target_character_key"),
                "target_enemy_key": buff_record.get("target_enemy_key"),
                "owner_raw": buff_record.get("owner_raw"),
                "target_actor_id": buff_record.get("target_actor_id"),
                "source_actor_id": buff_record.get("source_actor_id"),
                "event_key": buff_record.get("event_key"),
                "event_name": " / ".join(labels) if labels else str(buff_record.get("event_key") or ""),
                "zone_effects": zone_effects,
                "dynamic_effects": dynamic_effects,
                "modifier_count": len(buff_record.get("attr_mods") or []),
                "skill_family_key": None,
                "stack_limit": _packet_mapping_stack_limit(buff_record) or _buff_stack_limit(buff_record.get("event_key")),
            }
        )

    buff_windows = _dedupe_mirrored_buff_windows(_merge_buff_windows(buff_windows))
    buff_windows.extend(_build_special_combo_windows(hits, buff_starts, battle_end_ms=battle_end_ms))
    merged = _apply_buff_stack_limits(_dedupe_mirrored_buff_windows(_merge_buff_windows(buff_windows)))
    for window in merged:
        window["start_time"] = _format_ts_ms(int(window["start_ts_ms"]))
        window["end_time"] = _format_ts_ms(int(window["end_ts_ms"]))
    return merged


def _build_buff_record_index(buff_starts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    from parser_core.effects.lifecycle import _build_buff_record_index as build_index
    return build_index(buff_starts)


def _format_effect_summary(effects: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for effect in effects:
        zone = str(effect.get("zone") or "")
        zone_label = ZONE_LABELS.get(zone, zone)
        element = str(effect.get("element") or "all")
        rate = effect.get("rate")
        if rate is None and effect.get("base_rate") is not None:
            rate = effect.get("base_rate")
        try:
            base_rate = float(rate)
        except (TypeError, ValueError):
            base_rate = None
        element_text = "" if element == "all" else f"/{element}"
        if base_rate is None:
            row_text = f"{zone_label}{element_text} -"
        else:
            delayed_add_rate = float(effect.get("delayed_add_rate") or 0.0)
            delay_sec = float(effect.get("delay_sec") or 0.0)
            tick_rate = float(effect.get("tick_rate") or 0.0)
            max_rate = float(effect.get("max_rate") or 0.0)
            if delayed_add_rate > 0 and delay_sec > 0:
                row_text = (
                    f"{zone_label}{element_text} {base_rate * 100:.2f}%"
                    f" -> {(base_rate + delayed_add_rate) * 100:.2f}% @ {delay_sec:g}s"
                )
            elif tick_rate > 0 and max_rate > base_rate:
                row_text = (
                    f"{zone_label}{element_text} {base_rate * 100:.2f}%"
                    f" -> {max_rate * 100:.2f}% over time"
                )
            else:
                row_text = f"{zone_label}{element_text} {base_rate * 100:.2f}%"
        condition = effect.get("condition")
        if isinstance(condition, dict) and str(condition.get("type") or "") == "target_hp_ratio_lte":
            threshold = _safe_positive_rate(condition.get("threshold"))
            if threshold is not None:
                row_text = f"{row_text} (target HP <= {threshold * 100:.2f}%)"
        elif isinstance(condition, dict) and str(condition.get("type") or "") == "damage_type_in":
            elements = [str(item) for item in condition.get("elements") or [] if str(item or "")]
            if elements:
                row_text = f"{row_text} (damage type: {', '.join(elements)})"
        if row_text in seen:
            continue
        seen.add(row_text)
        rows.append(row_text)
    return rows


def _build_buff_audit_rows(
    buff_starts: list[dict[str, Any]],
    *,
    battle_end_ms: int,
    included_windows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    _resolve_weapon_buff_sources(buff_starts)
    included_uids = {
        str(window.get("uid") or "")
        for window in included_windows or []
        if window.get("uid")
    }
    for record in buff_starts:
        buff_id = _normalize_buff_id(record.get("event_key"))
        raw_buff_id = _normalize_buff_id(record.get("raw_event_key") or buff_id)
        packet_classification = _classify_packet_buff_record(record)
        semantic_candidates = _packet_buff_semantic_candidates(record)
        packet_mapping = record.get("packet_mapping") if isinstance(record.get("packet_mapping"), dict) else None
        labels = _collect_buff_labels(record)
        zone_effects = _collect_zone_effects(record)
        dynamic_effects = _extract_dynamic_effect_specs(record)
        effective_duration_ms = _normalize_buff_duration_ms(
            int(record.get("ts_ms") or 0),
            event_key=record.get("event_key"),
            end_ts_ms=record.get("end_ts_ms"),
            raw_duration_ms=record.get("raw_duration_ms"),
            battle_end_ms=battle_end_ms,
        )
        reasons: list[str] = []
        has_effects = bool(zone_effects or dynamic_effects)
        included = has_effects and (not included_uids or str(record.get("uid") or "") in included_uids)
        merged = has_effects and not included
        if _is_noise_buff(buff_id):
            reasons.append("配置为噪声/载体 buff")
        if _should_ignore_rate_buff(buff_id):
            reasons.append("规则忽略此类 rate wrapper")
        if not zone_effects and not dynamic_effects:
            reasons.append("无可识别正数效果")
        if not labels and (zone_effects or dynamic_effects):
            reasons.append("有效果但缺少展示标签")
        if merged:
            reasons.append("已被同一来源/目标/buff 的刷新链合并，不单独生效")
        if raw_buff_id.isdigit():
            if packet_mapping:
                reasons.append("numeric packet id 已通过上下文守卫映射")
            else:
                reasons.append(f"numeric packet id 未采纳：{packet_classification.get('label')}")
        status = "included" if included else "merged" if merged else "filtered"
        rows.append(
            {
                "status": status,
                "status_label": "纳入" if included else "合并" if merged else "过滤",
                "reasons": reasons,
                "line_no": record.get("line_no"),
                "uid": record.get("uid"),
                "event_key": buff_id,
                "raw_event_key": raw_buff_id,
                "event_name": " / ".join(labels) if labels else buff_id,
                "packet_mapping": packet_mapping,
                "packet_classification": packet_classification,
                "semantic_candidates": semantic_candidates,
                "source_character_key": record.get("source_character_key"),
                "source_character_name": record.get("source_character_name"),
                "raw_source": record.get("raw_source"),
                "target_character_key": record.get("target_character_key") or record.get("target_enemy_key"),
                "target_character_name": record.get("target_character_name") or record.get("target_enemy_name"),
                "owner_raw": record.get("owner_raw"),
                "start_ts_ms": record.get("ts_ms"),
                "start_time": record.get("time") or _format_ts_ms(int(record.get("ts_ms") or 0)),
                "end_ts_ms": int(record.get("ts_ms") or 0) + effective_duration_ms,
                "end_time": _format_ts_ms(int(record.get("ts_ms") or 0) + effective_duration_ms),
                "raw_end_time": _format_ts_ms(int(record["end_ts_ms"])) if record.get("end_ts_ms") is not None else None,
                "raw_duration_ms": record.get("raw_duration_ms"),
                "effective_duration_ms": effective_duration_ms,
                "bb_keys": sorted(set(str(key) for key in record.get("bb_keys") or [])),
                "bb_raw": dict(record.get("bb_raw") or {}),
                "attr_mods": list(record.get("attr_mods") or []),
                "zone_effects": zone_effects,
                "dynamic_effects": dynamic_effects,
                "effect_summary": _format_effect_summary(zone_effects + dynamic_effects),
            }
        )
    return sorted(rows, key=lambda item: (int(item.get("start_ts_ms") or 0), int(item.get("line_no") or 0)))
