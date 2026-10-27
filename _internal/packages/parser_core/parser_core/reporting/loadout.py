"""Select battle loadout snapshots and reconcile observed weapon changes."""
from __future__ import annotations

from parser_core.catalog.names import _load_num_id_str_skill_map
from parser_core.ingestion.loadout import _WEAPON_LOADOUT_STATE_FIELDS
from parser_core.ingestion.loadout import _loadout_weapon_source_skill_ids
from parser_core.ingestion.loadout import _loadout_with_weapon_state
from parser_core.ingestion.loadout import _merge_tracked_loadout_state
import copy
from typing import Any


def _select_loadout_snapshot_for_battle(
    loadout_groups: list[dict[str, Any]],
    fallback_by_char: dict[str, dict[str, Any]],
    *,
    anchor_ms: int | None,
    anchor_line_no: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Apply observed loadout updates in source order up to the battle boundary."""
    groups = [group for group in loadout_groups if isinstance(group.get('rows'), dict) and group['rows']]
    if not groups:
        return {key: dict(value) for key, value in fallback_by_char.items()}
    eligible = [group for group in groups if anchor_ms is None
                or (type(group.get('ts_ms')) is int and (group['ts_ms'] < anchor_ms
                    or (group['ts_ms'] == anchor_ms and (anchor_line_no is None
                        or int(group.get('line_no') or 0) <= anchor_line_no))))]
    if not eligible:
        return {}
    state: dict[str, dict[str, Any]] = {}
    selected_rows: dict[str, Any] = {}
    for group in eligible:
        selected_rows = group['rows']
        for key, value in selected_rows.items():
            if not isinstance(value, dict):
                continue
            character_key = str(key)
            state[character_key] = _merge_tracked_loadout_state(state.get(character_key, {}), value)
    # Restrict output to the observed snapshot's character keys. Do not merge
    # future fallback state into the historical battle or rank packet reasons.
    return {str(key): state[str(key)] for key in selected_rows if str(key) in state}


def _loadout_without_mismatched_weapon_skills(row: dict[str, Any]) -> dict[str, Any]:
    weapon_template = str(row.get("weapon_template") or "")
    if not weapon_template.startswith("wpn_"):
        return row
    expected_main_skill = f"sk_{weapon_template}"
    skill_id_map = _load_num_id_str_skill_map()
    main_skills = {
        skill_id_map.get(str(item.get("skill_id") or ""), str(item.get("skill_id") or ""))
        for item in row.get("weapon_source_skills") or row.get("weapon_refine_stats") or []
        if isinstance(item, dict)
    }
    main_skills = {skill_id for skill_id in main_skills if skill_id.startswith("sk_wpn_")}
    if not main_skills or expected_main_skill in main_skills:
        return row

    sanitized = copy.deepcopy(row)
    stale_source_ids = _loadout_weapon_source_skill_ids(sanitized)
    sanitized["weapon_source_skills"] = []
    sanitized["weapon_refine_stats"] = []
    if sanitized.get("weapon_refine_source") == "source_skill":
        sanitized["weapon_refine"] = None
        sanitized["weapon_refine_source"] = None
    sanitized["skill_int_ids"] = [
        int(skill_int_id)
        for skill_int_id in sanitized.get("skill_int_ids") or []
        if int(skill_int_id) and int(skill_int_id) not in stale_source_ids
    ]
    return sanitized


def _repair_weapon_puton_loadout_groups(
    loadout_groups: list[dict[str, Any]],
    fallback_by_char: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Repair the partial state emitted by the old SC_WEAPON_PUTON handler.

    The legacy client updated only the receiver's weapon instance.  When a
    weapon was moved from another character, the previous owner retained the
    same instance and both characters retained their pre-swap weapon skills.
    The surrounding loadout groups contain enough information to reconstruct
    the atomic swap deterministically.
    """

    raw_state_by_char: dict[str, dict[str, Any]] = {}
    corrected_state_by_char: dict[str, dict[str, Any]] = {}

    for group in loadout_groups:
        rows = group.get("rows")
        if not isinstance(rows, dict):
            continue
        raw_rows = {
            str(char_key): copy.deepcopy(row)
            for char_key, row in rows.items()
            if isinstance(row, dict)
        }
        corrected_rows = copy.deepcopy(raw_rows)
        reason = str(group.get("reason") or "")

        if reason != "SC_SYNC_CHAR_BAG_INFO":
            # Equipment/scene/battle snapshots repeat the cached weapon state.
            # Carry an earlier correction forward while the raw instance for
            # that character has not changed.
            for char_key, raw_row in raw_rows.items():
                previous_raw = raw_state_by_char.get(char_key)
                previous_corrected = corrected_state_by_char.get(char_key)
                if not previous_raw or not previous_corrected:
                    continue
                if all(
                    previous_raw.get(field) == previous_corrected.get(field)
                    for field in _WEAPON_LOADOUT_STATE_FIELDS
                ):
                    continue
                if str(raw_row.get("weapon_inst_id") or "") == str(
                    previous_raw.get("weapon_inst_id") or ""
                ):
                    corrected_rows[char_key] = _loadout_with_weapon_state(
                        raw_row,
                        previous_corrected,
                    )

        state_updates: dict[str, dict[str, Any]] = {}
        if reason == "SC_WEAPON_PUTON":
            for receiver_key, raw_receiver in raw_rows.items():
                previous_raw_receiver = raw_state_by_char.get(receiver_key)
                previous_corrected_receiver = corrected_state_by_char.get(receiver_key)
                if not previous_raw_receiver or not previous_corrected_receiver:
                    continue
                new_weapon_inst_id = str(raw_receiver.get("weapon_inst_id") or "")
                if not new_weapon_inst_id or new_weapon_inst_id == str(
                    previous_raw_receiver.get("weapon_inst_id") or ""
                ):
                    continue

                previous_owner_key = next(
                    (
                        char_key
                        for char_key, previous_row in corrected_state_by_char.items()
                        if char_key != receiver_key
                        and str(previous_row.get("weapon_inst_id") or "") == new_weapon_inst_id
                    ),
                    None,
                )
                if previous_owner_key is None:
                    corrected_rows[receiver_key] = _loadout_without_mismatched_weapon_skills(
                        corrected_rows[receiver_key]
                    )
                    continue

                previous_owner_state = corrected_state_by_char[previous_owner_key]
                corrected_receiver = _loadout_with_weapon_state(
                    raw_receiver,
                    previous_owner_state,
                )
                owner_destination = corrected_rows.get(
                    previous_owner_key,
                    corrected_state_by_char[previous_owner_key],
                )
                corrected_previous_owner = _loadout_with_weapon_state(
                    owner_destination,
                    previous_corrected_receiver,
                )
                corrected_rows[receiver_key] = corrected_receiver
                if previous_owner_key in corrected_rows:
                    corrected_rows[previous_owner_key] = corrected_previous_owner
                else:
                    state_updates[previous_owner_key] = corrected_previous_owner

        for char_key, row in list(corrected_rows.items()):
            corrected_rows[char_key] = _loadout_without_mismatched_weapon_skills(row)
        group["rows"] = corrected_rows
        # A logical snapshot can arrive as adjacent LOADOUT / LOADOUT_STATS
        # records (and therefore as separate groups).  Preserve the fields
        # from both halves while advancing the raw/corrected state machines.
        for char_key, row in raw_rows.items():
            raw_state_by_char[char_key] = _merge_tracked_loadout_state(
                raw_state_by_char.get(char_key), row
            )
        for char_key, row in corrected_rows.items():
            corrected_state_by_char[char_key] = _merge_tracked_loadout_state(
                corrected_state_by_char.get(char_key), row
            )
        for char_key, row in state_updates.items():
            corrected_state_by_char[char_key] = _merge_tracked_loadout_state(
                corrected_state_by_char.get(char_key), row
            )

    repaired_fallback = {
        str(char_key): copy.deepcopy(row)
        for char_key, row in fallback_by_char.items()
        if isinstance(row, dict)
    }
    for char_key, row in corrected_state_by_char.items():
        repaired_fallback[char_key] = _merge_tracked_loadout_state(
            repaired_fallback.get(char_key), row
        )
    return repaired_fallback
