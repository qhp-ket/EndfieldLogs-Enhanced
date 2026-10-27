"""Project canonical analysis results into the existing upload schema."""
from __future__ import annotations
from datetime import datetime
from typing import Any
from parser_core import parse_upload_battle_log_text
from uploader_core.payload.loadout import (
    _build_loadout_by_character_key,
    _is_character_key,
    _loadout_entries_with_fallback,
    _loadout_lookup_keys,
    _lookup_loadout_name,
    _lookup_loadout_payload,
    _resolve_loadout_character_key,
)


def _canonical_character_keys(
    parsed: dict,
    *,
    loadout_entries: list[dict],
) -> list[str]:
    battle_duration_ms = max(int(parsed["battle"]["duration_ms"]), 0)
    participant_by_key = {str(entry["character_key"]): entry for entry in parsed["participants"]}
    role_skill_keys = {str(entry["character_key"]) for entry in parsed["role_skill_stats"]}
    active_keys = set(participant_by_key)
    active_keys.update(role_skill_keys)

    for event in parsed["timeline_events"]:
        if event.get("lane_type") != "skill":
            continue
        try:
            ts_ms_from_start = int(event.get("ts_ms_from_start") or 0)
        except (TypeError, ValueError):
            ts_ms_from_start = 0
        if ts_ms_from_start > battle_duration_ms:
            continue
        source_key = event.get("source_character_key")
        target_key = event.get("target_character_key")
        source_character_key = str(source_key) if _is_character_key(source_key) else None
        target_character_key = str(target_key) if _is_character_key(target_key) else None

        if source_character_key and target_character_key and source_character_key == target_character_key:
            continue
        if source_character_key:
            active_keys.add(source_character_key)
        if target_character_key:
            active_keys.add(target_character_key)

    if not loadout_entries:
        return [
            str(entry["character_key"])
            for entry in parsed["battle"]["roster"]
            if str(entry["character_key"]) in active_keys
        ]

    loadout_order: list[str] = []
    for entry in sorted(loadout_entries, key=lambda item: int(item.get("slot") or 0)):
        char_key = _resolve_loadout_character_key(entry.get("char_key"), active_keys) or ""
        if char_key and char_key in active_keys and char_key not in loadout_order:
            loadout_order.append(char_key)

    extra_keys: list[str] = []
    for entry in parsed["battle"]["roster"]:
        character_key = str(entry["character_key"])
        if character_key in loadout_order or character_key in extra_keys:
            continue
        if character_key in active_keys:
            extra_keys.append(character_key)

    return loadout_order + extra_keys


def _timeline_effect_payload(effect: dict) -> dict:
    payload: dict = {
        "zone": effect.get("zone"),
        "element": effect.get("element"),
    }
    for source_key, target_key in (
        ("rate", "rate"),
        ("base_rate", "baseRate"),
        ("tick_rate", "tickRate"),
        ("max_rate", "maxRate"),
    ):
        value = effect.get(source_key)
        if value is None:
            continue
        payload[target_key] = value
    return payload


def _camelize_state_key(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(part[:1].upper() + part[1:] for part in parts[1:])


def _character_state_payload(value):
    if isinstance(value, list):
        return [_character_state_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            _camelize_state_key(str(key)): _character_state_payload(item)
            for key, item in value.items()
        }
    return value


def _contract_tag_payload(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    tag_id = value.get("tagId", value.get("tag_id"))
    score = value.get("score")
    try:
        tag_id_int = int(tag_id)
        score_int = int(score or 0)
    except (TypeError, ValueError):
        return None
    raw_group_id = value.get("groupId") if value.get("groupId") is not None else value.get("group_id")
    try:
        group_id_int = int(raw_group_id) if raw_group_id is not None else None
    except (TypeError, ValueError):
        group_id_int = None
    icon_id = value.get("iconId") or value.get("icon_id") or value.get("icon")
    icon_url = value.get("iconUrl") or value.get("icon_url") or value.get("iconPath") or value.get("icon_path")
    if not icon_url and isinstance(icon_id, str) and icon_id.startswith("icon_activity_contract_tag_"):
        icon_url = f"/images/contract-tag/{icon_id}.png"
    payload: dict[str, Any] = {
        "tagId": tag_id_int,
        "score": score_int,
        "name": value.get("name") or value.get("tagName") or value.get("tag_name"),
        "description": value.get("description"),
        "iconId": icon_id,
        "iconUrl": icon_url,
        "buffId": value.get("buffId") or value.get("buff_id"),
        "groupId": group_id_int,
        "conflictId": value.get("conflictId") or value.get("conflict_id"),
        "terms": value.get("terms") if isinstance(value.get("terms"), list) else [],
        "values": value.get("values") if isinstance(value.get("values"), dict) else {},
    }
    return payload


def _contract_tags_payload(values: object) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    return [payload for value in values if (payload := _contract_tag_payload(value)) is not None]


def _build_payload_from_segment(
    *,
    segment: dict,
    source_file_name: str,
    reference_date,
    proof: dict | None,
    raw_loadout_entries: list[dict] | None = None,
    raw_char_skill_levels: dict[str, dict[str, int]] | None = None,
    critical_attributes_override_by_actor: dict[str, dict] | None = None,
) -> dict:
    loadout_override_by_char = {
        str(entry.get("char_key") or entry.get("character_key") or ""): entry
        for entry in (raw_loadout_entries or [])
        if isinstance(entry, dict)
        and str(entry.get("char_key") or entry.get("character_key") or "")
    }
    parsed = parse_upload_battle_log_text(
        str(segment["content"]),
        file_name=source_file_name,
        first_hit_hint=segment.get("first_hit_hint"),
        last_hit_hint=segment.get("last_hit_hint"),
        reference_date=reference_date,
        loadout_override_by_char=loadout_override_by_char,
        critical_attributes_override_by_actor=critical_attributes_override_by_actor,
    )
    loadout_entries = _loadout_entries_with_fallback(
        proof,
        parsed.get("loadout"),
        raw_loadout_entries=raw_loadout_entries,
    )
    loadout_by_key = _build_loadout_by_character_key(proof, loadout_entries=loadout_entries)
    canonical_keys = _canonical_character_keys(parsed, loadout_entries=loadout_entries)
    canonical_key_set = set(canonical_keys)
    parsed_roster_by_key = {
        str(entry["character_key"]): entry
        for entry in parsed["battle"]["roster"]
    }
    parsed_participants_by_key = {
        str(entry["character_key"]): entry
        for entry in parsed["participants"]
    }
    loadout_name_by_key = {
        str(entry.get("char_key") or ""): str(entry.get("char_name") or "")
        for entry in loadout_entries
        if str(entry.get("char_key") or "")
    }

    # 技能等级（v33 排轴导出）：优先本段 CHAR_SKILLS，缺则用整份 trace 的全局提取
    # （bridge 在战前落盘，常在 battle 分段之外）；只保留本角色前缀的技能
    # （武器词条技能由 weapon.refine 表达，不重复导出）。
    char_skill_levels: dict[str, dict[str, int]] = dict(raw_char_skill_levels or {})
    for owner_key, entries in (parsed.get("char_skills") or {}).items():
        if isinstance(entries, list):
            char_skill_levels[str(owner_key)] = {
                str(item.get("skill_key")): int(item.get("level") or 0)
                for item in entries
                if item.get("skill_key") and int(item.get("level") or 0) > 0
            }

    roster: list[dict] = []
    for index, character_key in enumerate(canonical_keys, start=1):
        parsed_entry = parsed_roster_by_key.get(character_key, {})
        loadout_payload = _lookup_loadout_payload(loadout_by_key, character_key)
        skills: list[dict] = []
        for lookup_key in _loadout_lookup_keys(character_key):
            levels_for_char = char_skill_levels.get(lookup_key)
            if levels_for_char:
                skills = [
                    {"skillKey": skill_key, "level": level}
                    for skill_key, level in sorted(levels_for_char.items())
                    if skill_key.startswith(lookup_key)
                ]
                break
        roster.append(
            {
                "slot": index,
                "characterKey": character_key,
                "characterName": str(
                    parsed_entry.get("character_name")
                    or _lookup_loadout_name(loadout_name_by_key, character_key)
                    or character_key
                ),
                "accountDisplayName": None,
                "characterLevel": loadout_payload.get("characterLevel"),
                "characterPotential": loadout_payload.get("characterPotential"),
                "weapon": loadout_payload.get("weapon"),
                "equips": loadout_payload.get("equips", []),
                "skills": skills,
            }
        )

    participants = [
        {
            "characterKey": entry["character_key"],
            "characterName": entry["character_name"],
            "accountDisplayName": None,
            "totalDamage": entry["total_damage"],
            "dps": entry["dps"],
            "rdps": entry["rdps"],
            "maxHit": entry["max_hit"],
            "critRate": entry["crit_rate"],
        }
        for entry in parsed["participants"]
        if str(entry["character_key"]) in canonical_key_set
    ]

    timeline_events = [
        {
            "tsMsFromStart": event["ts_ms_from_start"],
            "laneType": event["lane_type"],
            "sourceCharacterKey": event["source_character_key"],
            "sourceCharacterName": event["source_character_name"],
            "targetCharacterKey": event["target_character_key"],
            "targetCharacterName": event["target_character_name"],
            "targetPlayerKey": event.get("target_player_key"),
            "targetEnemyKey": event.get("target_enemy_key"),
            "eventType": event["event_type"],
            "eventKey": event["event_key"],
            "eventGroupKey": event.get("event_group_key"),
            "eventName": event["event_name"],
            "value": event["value"],
            "damageElement": event.get("damage_element"),
            "damageSchool": event.get("damage_school"),
            "poiseDamage": event.get("poise_damage"),
            "rdpsContributions": [
                {
                    "characterKey": item["character_key"],
                    "characterName": item["character_name"],
                    "value": item["value"],
                }
                for item in event.get("rdps_contributions") or []
                if str(item["character_key"]) in canonical_key_set
            ],
            "hitContext": event.get("hit_context"),
            "durationMs": event["duration_ms"],
            "actualStartMsFromStart": event.get("actual_start_ms_from_start"),
            "actualEndMsFromStart": event.get("actual_end_ms_from_start"),
            "actualDurationMs": event.get("actual_duration_ms"),
            "effects": [_timeline_effect_payload(item) for item in event.get("effects") or []],
            "dynamicEffects": [_timeline_effect_payload(item) for item in event.get("dynamic_effects") or []],
            "important": event["important"],
        }
        for event in parsed["timeline_events"]
        if int(event["ts_ms_from_start"]) <= int(parsed["battle"]["duration_ms"])
        if (
            not _is_character_key(event.get("source_character_key"))
            or str(event.get("source_character_key")) in canonical_key_set
        )
        and (
            not _is_character_key(event.get("target_character_key"))
            or str(event.get("target_character_key")) in canonical_key_set
        )
    ]

    role_skill_stats = [
        {
            "characterKey": entry["character_key"],
            "characterName": entry["character_name"],
            "accountDisplayName": None,
            "skillKey": entry["skill_key"],
            "skillName": entry["skill_name"],
            "castCount": entry["cast_count"],
            "totalDamage": entry["total_damage"],
            "avgDamage": entry["avg_damage"],
            "maxDamage": entry["max_damage"],
        }
        for entry in parsed["role_skill_stats"]
        if str(entry["character_key"]) in canonical_key_set
    ]

    contract_tags = _contract_tags_payload(parsed["battle"].get("contract_tags") or parsed["battle"].get("contractTags"))
    contract_tag_score = parsed["battle"].get("contract_tag_score")
    if contract_tag_score is None and contract_tags:
        contract_tag_score = sum(int(tag.get("score") or 0) for tag in contract_tags)

    timer_end_seen = bool(
        parsed["battle"].get("timer_end_seen")
        or parsed["battle"].get("official_timer_end_seen")
    )
    clear_flag = bool(parsed["battle"].get("clear_flag")) and timer_end_seen
    rdps_damage_basis = parsed.get("rdps_damage_basis") or parsed["battle"].get("rdps_damage_basis") or {}
    loadout_fallback_used = any(bool(entry.get("_loadout_fallback_used")) for entry in loadout_entries)

    return {
        "battle": {
            "dungeonKey": parsed["battle"]["dungeon_key"],
            "dungeonName": parsed["battle"]["dungeon_name"],
            "bossKey": parsed["battle"]["boss_key"],
            "bossName": parsed["battle"]["boss_name"],
            # Internal analysis retains milliseconds for input alignment. The
            # existing uploader contract keeps its second-precision dates.
            "battleStartAt": datetime.fromisoformat(parsed["battle"]["battle_start_at"]).isoformat(timespec="seconds"),
            "battleEndAt": datetime.fromisoformat(parsed["battle"]["battle_end_at"]).isoformat(timespec="seconds"),
            "durationMs": parsed["battle"]["duration_ms"],
            "clearFlag": clear_flag,
            "totalDamage": parsed["battle"]["total_damage"],
            "totalDps": parsed["battle"]["total_dps"],
            "roster": roster,
            "battleFingerprint": parsed["battle"]["battle_fingerprint"],
            "parserVersion": parsed["battle"]["parser_version"],
            "rulesVersion": parsed["battle"]["rules_version"],
            "timeSource": parsed["battle"].get("time_source"),
            "timelineZeroSource": parsed["battle"].get("timeline_zero_source"),
            "timerStartSeen": parsed["battle"].get("timer_start_seen"),
            "timerEndSeen": parsed["battle"].get("timer_end_seen"),
            "officialTimerStartSeen": parsed["battle"].get("official_timer_start_seen"),
            "officialTimerEndSeen": parsed["battle"].get("official_timer_end_seen"),
            "officialTimerObservedElapsedMs": parsed["battle"].get(
                "official_timer_observed_elapsed_ms"
            ),
            "packetTimerElapsedMs": parsed["battle"].get("packet_timer_elapsed_ms"),
            "timerIntegrityOk": parsed["battle"].get("timer_integrity_ok"),
            "timerIntegrityReasons": list(parsed["battle"].get("timer_integrity_reasons") or []),
            "timerEvidence": parsed["battle"].get("timer_evidence"),
            "timerStartInferred": parsed["battle"].get("timer_start_inferred"),
            "timerWindowValid": parsed["battle"].get("timer_window_valid"),
            "rdpsPreflightOk": rdps_damage_basis.get("rdps_preflight_ok"),
            "rdpsStrictOk": rdps_damage_basis.get("rdps_strict_ok"),
            "rdpsPreflightBlockerCount": rdps_damage_basis.get("preflight_blocker_count"),
            "bossIdentitySource": parsed["battle"].get("boss_identity_source"),
            "dungeonContextId": parsed["battle"].get("dungeon_context_id"),
            "dungeonIdentitySource": parsed["battle"].get("dungeon_identity_source"),
            "loadoutFallbackUsed": loadout_fallback_used,
            "contractTagScore": contract_tag_score,
            "contractTags": contract_tags,
        },
        "participants": participants,
        "characterStates": [
            _character_state_payload(state)
            for state in parsed.get("character_states") or []
            if str(state.get("character_key") or "") in canonical_key_set
        ],
        "timelineEvents": timeline_events,
        "roleSkillStats": role_skill_stats,
        "casts": [
            {
                "tsMsFromStart": cast["ts_ms_from_start"],
                "endMsFromStart": cast.get("end_ms_from_start"),
                "characterKey": cast["character_key"],
                "skillKey": cast["skill_key"],
                "skillName": cast.get("skill_name"),
                "skillSource": cast.get("skill_source"),
                "recoversEnergy": bool(cast.get("recovers_energy")),
            }
            for cast in parsed.get("casts") or []
            if str(cast.get("character_key") or "") in canonical_key_set
        ],
    }
