"""Participant and skill counters reconstructed from ordered hit evidence."""
from __future__ import annotations

from collections import Counter, defaultdict
from parser_core.catalog.names import _resolve_character_name, _resolve_skill_name
from typing import Any


_VISUAL_HIT_GROUP_WINDOW_MS = 120


def _new_participant_totals() -> defaultdict[str, dict[str, Any]]:
    return defaultdict(
        lambda: {
            "character_key": None,
            "character_name": None,
            "total_damage": 0,
            "max_hit": 0,
            "crit_hits": 0,
            "hit_count": 0,
        }
    )


def _recompute_participant_visual_max_hits(
    hits: list[dict[str, Any]],
    participant_totals: defaultdict[str, dict[str, Any]],
) -> None:
    grouped_max: dict[str, int] = defaultdict(int)
    last_group: dict[tuple[str, str, str], dict[str, int]] = {}

    ordered_hits = sorted(
        hits,
        key=lambda item: (
            int(item.get("ts_ms") or 0),
            str(item.get("character_key") or ""),
            str(item.get("skill_key") or ""),
        ),
    )
    for hit in ordered_hits:
        character_key = str(hit.get("character_key") or "")
        if not character_key:
            continue
        target_key = str(hit.get("target_enemy_key") or "")
        skill_key = str(hit.get("skill_key") or "")
        ts_ms = int(hit.get("ts_ms") or 0)
        hit_value = int(hit.get("hit_value") or 0)
        group_key = (character_key, target_key, skill_key)
        current = last_group.get(group_key)
        if current is None or ts_ms - current["last_ts_ms"] > _VISUAL_HIT_GROUP_WINDOW_MS:
            current = {"sum": hit_value, "last_ts_ms": ts_ms}
            last_group[group_key] = current
        else:
            current["sum"] += hit_value
            current["last_ts_ms"] = ts_ms
        grouped_max[character_key] = max(grouped_max[character_key], current["sum"])

    for character_key, participant in participant_totals.items():
        participant["max_hit"] = max(int(participant.get("max_hit") or 0), int(grouped_max.get(character_key) or 0))


def _new_skill_totals() -> defaultdict[tuple[str, str], dict[str, Any]]:
    return defaultdict(
        lambda: {
            "character_key": None,
            "character_name": None,
            "skill_key": None,
            "skill_name": None,
            "total_damage": 0,
            "max_damage": 0,
            "hit_count": 0,
            "cast_count": 0,
        }
    )


def _rebuild_hit_totals(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
) -> tuple[
    defaultdict[str, dict[str, Any]],
    defaultdict[tuple[str, str], dict[str, Any]],
    list[str],
    set[str],
    Counter[str],
]:
    from parser_core.realtime.incremental import ACTIVE_ALLOCATION_CACHE
    live_cache = ACTIVE_ALLOCATION_CACHE.get()
    if live_cache is not None and live_cache.summary_mode:
        return live_cache.damage_totals.project(hits, buff_starts)
    participant_totals = _new_participant_totals()
    skill_totals = _new_skill_totals()
    roster_seen: set[str] = set()
    roster_order: list[str] = []
    enemy_counter: Counter[str] = Counter()

    for hit in hits:
        character_key = str(hit.get("character_key") or "")
        if not character_key:
            continue
        if character_key not in roster_seen:
            roster_seen.add(character_key)
            roster_order.append(character_key)
        enemy_key = str(hit.get("target_enemy_key") or "")
        if enemy_key:
            enemy_counter[enemy_key] += 1

        hit_value = int(hit.get("hit_value") or 0)
        crit_flag = int(hit.get("crit_flag") or 0)
        participant = participant_totals[character_key]
        participant["character_key"] = character_key
        participant["character_name"] = hit.get("character_name") or _resolve_character_name(character_key) or character_key
        participant["total_damage"] += hit_value
        participant["max_hit"] = max(participant["max_hit"], hit_value)
        participant["crit_hits"] += 1 if crit_flag else 0
        participant["hit_count"] += 1

        skill_key = str(hit.get("skill_key") or "unknown_skill")
        skill_entry = skill_totals[(character_key, skill_key)]
        skill_entry["character_key"] = character_key
        skill_entry["character_name"] = participant["character_name"]
        skill_entry["skill_key"] = skill_key
        skill_entry["skill_name"] = hit.get("skill_name") or _resolve_skill_name(skill_key) or skill_key
        skill_entry["total_damage"] += hit_value
        skill_entry["max_damage"] = max(skill_entry["max_damage"], hit_value)
        skill_entry["hit_count"] += 1
        if int(hit.get("hit_index") or 1) == 1:
            skill_entry["cast_count"] += 1

    for buff_record in buff_starts:
        for character_key in (buff_record.get("source_character_key"), buff_record.get("target_character_key")):
            if not character_key:
                continue
            character_key = str(character_key)
            if character_key not in roster_seen:
                roster_seen.add(character_key)
                roster_order.append(character_key)
            participant = participant_totals[character_key]
            participant["character_key"] = character_key
            participant["character_name"] = _resolve_character_name(character_key) or character_key

    _recompute_participant_visual_max_hits(hits, participant_totals)

    return participant_totals, skill_totals, roster_order, roster_seen, enemy_counter
