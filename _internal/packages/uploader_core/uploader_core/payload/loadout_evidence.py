"""Recover battle-specific loadout snapshots from ordered trace evidence."""
from __future__ import annotations
import re
from typing import Any
from parser_core.ingestion.identity import _SQUAD_MEMBER_RE
from parser_core.ingestion.loadout import _parse_char_skills_line
from parser_core.ingestion.loadout import _merge_loadout_snapshot as _parser_merge_loadout_snapshot
from parser_core.ingestion.loadout import _merge_tracked_loadout_state as _parser_merge_tracked_loadout_state
from parser_core.ingestion.loadout import _parse_loadout_slot_snapshot
from parser_core.ingestion.loadout import _parse_loadout_stats_snapshot
from parser_core.reporting.loadout import _repair_weapon_puton_loadout_groups


def _raw_text_loadout_state(raw_content: str) -> tuple[list[dict], dict[str, dict]]:
    groups: list[dict] = []
    entries_by_key: dict[str, dict] = {}
    current_group: dict | None = None
    squad_actor_keys: dict[str, str] = {}
    for line_index, raw_line in enumerate(raw_content.splitlines()):
        if " SQUAD " in raw_line:
            members = [(match.group(2), match.group(1)) for match in _SQUAD_MEMBER_RE.finditer(raw_line)]
            squad_actor_keys = dict(members) if len({pair[0] for pair in members}) == len(members) else {}
        reason_match = re.search(r"\bLOADOUT reason=([^\s]+)", raw_line)
        if reason_match:
            current_group = {
                "ts_ms": line_index,
                "line_index": line_index,
                "timestamp": raw_line[:13],
                "reason": reason_match.group(1),
                "index": len(groups),
                "rows": {},
            }
            groups.append(current_group)
            continue

        snapshot: dict[str, Any] | None = None
        if " LOADOUT_STATS " in raw_line or "LOADOUT_STATS " in raw_line:
            snapshot = _parse_loadout_stats_snapshot(raw_line,
                allow_bound_gem=bool(current_group and current_group.get("timestamp") == raw_line[:13]
                    and current_group.get("reason") in {"SC_SYNC_CHAR_BAG_INFO", "SC_SELF_SCENE_INFO"}))
        elif " LOADOUT slot=" in raw_line or "LOADOUT slot=" in raw_line:
            snapshot = _parse_loadout_slot_snapshot(raw_line)
        elif " CHAR_SKILLS " in raw_line:
            parsed_skills = _parse_char_skills_line(raw_line)
            if parsed_skills is not None:
                snapshot = _parse_loadout_stats_snapshot(
                    raw_line, loadout_context=entries_by_key.get(parsed_skills[0]),
                    squad_actor_keys=squad_actor_keys,
                )
            if snapshot is not None:
                current_group = {
                    "ts_ms": line_index, "line_index": line_index, "timestamp": raw_line[:13],
                    "reason": "CHAR_SKILLS", "index": len(groups),
                    "rows": {key: dict(entries_by_key[key]) for key in set(squad_actor_keys.values()) if key in entries_by_key},
                }
                groups.append(current_group)
        if snapshot is None:
            continue
        char_key = str(snapshot.get("character_key") or snapshot.get("char_key") or "")
        if not char_key:
            continue
        timestamp = raw_line[:13]
        if current_group is None or current_group.get("timestamp") != timestamp:
            current_group = {
                "ts_ms": line_index,
                "line_index": line_index,
                "timestamp": timestamp,
                "reason": "",
                "index": len(groups),
                "rows": {},
            }
            groups.append(current_group)
        group_rows = current_group["rows"]
        group_rows[char_key] = _parser_merge_loadout_snapshot(
            group_rows.get(char_key, {"character_key": char_key}),
            snapshot,
        )
        entries_by_key[char_key] = _parser_merge_tracked_loadout_state(
            entries_by_key.get(char_key, {}),
            snapshot,
        )

    repaired_fallback = _repair_weapon_puton_loadout_groups(groups, entries_by_key)
    return groups, repaired_fallback


def _sorted_loadout_entries(entries_by_key: dict[str, dict]) -> list[dict]:
    return sorted(
        (dict(entry) for entry in entries_by_key.values() if isinstance(entry, dict)),
        key=lambda entry: (int(entry.get("slot") or 0), str(entry.get("character_key") or "")),
    )


def _raw_text_loadout_entries(raw_content: str) -> list[dict]:
    _groups, repaired_fallback = _raw_text_loadout_state(raw_content)
    return _sorted_loadout_entries(repaired_fallback)


def _raw_loadout_entries_for_segment(
    loadout_groups: list[dict],
    fallback_by_char: dict[str, dict],
    segment: dict,
) -> list[dict]:
    first_hit_line_index = segment.get("first_hit_line_index")
    if first_hit_line_index is None:
        return _sorted_loadout_entries(fallback_by_char)
    eligible = [
        group
        for group in loadout_groups
        if group.get("rows")
        and int(group.get("line_index") or 0) <= int(first_hit_line_index)
    ]
    if not eligible:
        return []
    selected = max(
        eligible,
        key=lambda group: (int(group.get("line_index") or 0), int(group.get("index") or 0)),
    )
    rows = selected.get("rows")
    if not isinstance(rows, dict):
        return []
    # A battle-start packet may be a delta (for example, one changed equip
    # slot). Rebuild only the characters present in the selected battle group
    # from preceding raw-log snapshots; do not carry previous teammates.
    merged_rows: dict[str, dict] = {}
    selected_keys = {str(key) for key in rows}
    for group in sorted(
        eligible,
        key=lambda item: (int(item.get("line_index") or 0), int(item.get("index") or 0)),
    ):
        group_rows = group.get("rows")
        if not isinstance(group_rows, dict):
            continue
        for char_key in selected_keys:
            snapshot = group_rows.get(char_key)
            if isinstance(snapshot, dict):
                merged_rows[char_key] = _parser_merge_tracked_loadout_state(
                    merged_rows.get(char_key, {"character_key": char_key}),
                    snapshot,
                )
    return _sorted_loadout_entries(merged_rows)
