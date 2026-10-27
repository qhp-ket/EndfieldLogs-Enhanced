"""Match observed cast intervals and group hit statistics without changing timestamps."""
from __future__ import annotations

from collections import defaultdict
from parser_core.catalog.names import _canonical_packet_skill_id
from parser_core.catalog.names import _resolve_character_name
from parser_core.catalog.names import _resolve_skill_name
from parser_core.catalog.skill_damage import _resolve_skill_profile
from parser_core.ingestion.skill_identity import _canonical_num_table_skill_id
from parser_core.ingestion.skill_identity import _resolve_skill_family_key
from parser_core.ingestion.skills import _is_generic_runtime_skill_id
import re
from typing import Any


_TIMELINE_SKILL_GROUP_GAP_MS = 1200


_TIMELINE_ULTIMATE_GROUP_GAP_MS = 5000


_CAST_CHILD_ENTITY_RE = re.compile(
    r"(?:projhit|abilityrange|indicator|blocked|_bomb|_field|_sheep)",
    re.IGNORECASE,
)


def _cast_skill_family_key(cast: dict[str, Any]) -> str:
    cast_skill = str(cast.get("skill") or "")
    if not cast_skill:
        return ""
    if str(cast.get("skill_source") or "").lower() == "summon":
        return ""
    if _CAST_CHILD_ENTITY_RE.search(cast_skill):
        return ""

    cast_character_key = str(cast.get("source_character_key") or "")
    canonical_skill = _canonical_packet_skill_id(cast_skill)
    if _is_generic_runtime_skill_id(canonical_skill) or re.fullmatch(r".*_skill_\d+", canonical_skill):
        canonical_skill = _canonical_num_table_skill_id(canonical_skill, cast_character_key) or canonical_skill

    skill_profile = _resolve_skill_profile(canonical_skill)
    family_key = _resolve_skill_family_key(canonical_skill, skill_profile)
    return family_key


def _build_cast_start_index(skill_casts: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for cast in sorted(skill_casts, key=lambda item: int(item.get("ts_ms") or 0)):
        character_key = str(cast.get("source_character_key") or "")
        family_key = _cast_skill_family_key(cast)
        if not character_key or not family_key:
            continue
        index[(character_key, family_key)].append(cast)
    return index


def _matching_cast_for_hit(
    hit: dict[str, Any],
    cast_start_index: dict[tuple[str, str], list[dict[str, Any]]],
) -> dict[str, Any] | None:
    character_key = str(hit.get("character_key") or "")
    family_key = str(hit.get("skill_family_key") or hit.get("skill_key") or "").lower()
    if not character_key or not family_key:
        return None

    hit_ts = int(hit.get("ts_ms") or 0)
    for cast in reversed(cast_start_index.get((character_key, family_key), [])):
        cast_ts = int(cast.get("ts_ms") or 0)
        delta_ms = hit_ts - cast_ts
        if delta_ms < -50:
            continue
        if delta_ms > 12000:
            break
        return cast
    return None


def _timeline_skill_group_gap_ms(hit: dict[str, Any]) -> int:
    skill_key = str(hit.get("skill_key") or "").lower()
    family_key = str(hit.get("skill_family_key") or "").lower()
    if "_ultimate_skill" in family_key or "_ultimate_skill" in skill_key or "_ult_attack" in skill_key:
        return _TIMELINE_ULTIMATE_GROUP_GAP_MS
    return _TIMELINE_SKILL_GROUP_GAP_MS


def _assign_skill_timeline_group_keys(hits: list[dict[str, Any]]) -> None:
    latest_group_state: dict[tuple[str, str, str], dict[str, int]] = {}
    next_group_index: defaultdict[tuple[str, str, str], int] = defaultdict(int)

    for order_index, hit in sorted(
        enumerate(hits),
        key=lambda item: (int(item[1].get("ts_ms") or 0), item[0]),
    ):
        _ = order_index
        base_event_key = str(hit.get("skill_family_key") or hit.get("skill_key") or "")
        if not base_event_key:
            hit["timeline_group_key"] = None
            continue

        state_key = (
            str(hit.get("character_key") or ""),
            base_event_key,
            str(hit.get("target_enemy_key") or ""),
        )
        hit_ts_ms = int(hit.get("ts_ms") or 0)
        state = latest_group_state.get(state_key)
        if state is None or hit_ts_ms - state["last_ts_ms"] > _timeline_skill_group_gap_ms(hit):
            next_group_index[state_key] += 1

        group_index = next_group_index[state_key]
        latest_group_state[state_key] = {"last_ts_ms": hit_ts_ms}
        hit["timeline_group_key"] = f"{base_event_key}::{state_key[2] or 'unknown-target'}::{group_index}"


def _build_role_skill_stats_from_timeline_groups(
    hits: list[dict[str, Any]],
    roster_order: list[str],
) -> list[dict[str, Any]]:
    cast_totals: defaultdict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "character_key": None,
            "character_name": None,
            "skill_key": None,
            "skill_name": None,
            "total_damage": 0,
        }
    )

    for index, hit in enumerate(hits):
        character_key = str(hit.get("character_key") or "")
        if not character_key:
            continue
        skill_key = str(hit.get("skill_family_key") or hit.get("skill_key") or "unknown_skill")
        cast_key = str(hit.get("timeline_group_key") or f"{skill_key}::hit-{index}")
        cast_entry = cast_totals[(character_key, skill_key, cast_key)]
        cast_entry["character_key"] = character_key
        cast_entry["character_name"] = hit.get("character_name") or _resolve_character_name(character_key) or character_key
        cast_entry["skill_key"] = skill_key
        cast_entry["skill_name"] = hit.get("skill_name") or _resolve_skill_name(skill_key) or skill_key
        cast_entry["total_damage"] += int(hit.get("hit_value") or 0)

    skill_totals: defaultdict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "character_key": None,
            "character_name": None,
            "skill_key": None,
            "skill_name": None,
            "total_damage": 0,
            "max_damage": 0,
            "cast_count": 0,
        }
    )

    for (character_key, skill_key, _), cast_entry in cast_totals.items():
        cast_damage = int(cast_entry["total_damage"] or 0)
        skill_entry = skill_totals[(character_key, skill_key)]
        skill_entry["character_key"] = character_key
        skill_entry["character_name"] = cast_entry["character_name"]
        skill_entry["skill_key"] = skill_key
        skill_entry["skill_name"] = cast_entry["skill_name"]
        skill_entry["total_damage"] += cast_damage
        skill_entry["max_damage"] = max(int(skill_entry["max_damage"] or 0), cast_damage)
        skill_entry["cast_count"] += 1

    role_skill_stats = []
    for character_key in roster_order:
        character_skills = [
            entry
            for (entry_character_key, _), entry in skill_totals.items()
            if entry_character_key == character_key
        ]
        character_skills.sort(key=lambda item: (-item["total_damage"], item["skill_key"]))
        for entry in character_skills:
            cast_count = max(int(entry["cast_count"] or 0), 1)
            role_skill_stats.append(
                {
                    "character_key": character_key,
                    "character_name": entry["character_name"],
                    "skill_key": entry["skill_key"],
                    "skill_name": entry["skill_name"],
                    "cast_count": cast_count,
                    "total_damage": entry["total_damage"],
                    "avg_damage": round(entry["total_damage"] / cast_count, 2),
                    "max_damage": entry["max_damage"],
                }
            )

    return role_skill_stats
