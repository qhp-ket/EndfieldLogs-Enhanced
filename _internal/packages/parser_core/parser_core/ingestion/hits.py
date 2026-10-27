"""Ordered hit evidence and explicit buff lifetime observations."""
from __future__ import annotations

from parser_core.allocation.arts_strength import _is_arts_strength_damage_hit
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.display import _resolve_enemy_name
from parser_core.catalog.names import _resolve_character_name, _resolve_skill_name
from parser_core.catalog.skill_damage import _load_skill_action_damage_units, _resolve_skill_profile
from parser_core.effects.approval import _normalize_buff_id
from parser_core.effects.damage_types import _damage_school_from_element, _infer_skill_action_damage_element
from parser_core.effects.enemy_status import _apply_enemy_status_bb_overrides, _cap_enemy_overkill_damage, _enemy_hp_state_key
from parser_core.effects.packet_mapping import _canonical_packet_buff_id, _packet_mapping_applies, _packet_numeric_buff_hint
from parser_core.ingestion.entities import _attach_attacker_entity_stats, _attach_target_entity_stats, _entity_stats_snapshot_at
from parser_core.ingestion.fields import (
    _coerce_int,
    _coerce_optional_float,
    _coerce_optional_int,
    _duration_ms_from_seconds,
    _extract_fields,
    _safe_positive_rate,
)
from parser_core.ingestion.identity import _extract_character_key, _extract_enemy_key
from parser_core.ingestion.skill_identity import (
    _canonical_hit_skill_id,
    _canonical_hit_skill_id_from_cast_context,
    _recent_source_skill_context_for_buff,
    _resolve_skill_family_key,
)
from parser_core.ingestion.state import IngestionState
from typing import Any
import copy
import re


_COMBO_CONSUME_SKILL_ALIASES: dict[str, dict[str, Any]] = {
    "sk_wpn_lance_0010": {
        "family_skill_key": "chr_0015_lifeng_ultimate_skill",
        "group_type": 2,
    },
}

_HIT_SEQ_RE = re.compile(r"\bHP_V2\s+#(\d+)\b")

_WEAPON_BUFF_RE = re.compile(r"^buff_wpn_[a-z]+_\d+_")

def consume_hit_and_buff_lifecycle(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    current_buff_record: dict[str, Any] | None = None

    if " ATTR_MOD " in raw_line or " DMG_MOD " in raw_line:
        fields = _extract_fields(raw_line)
        buff_key = _normalize_buff_id(fields.get("buff"))
        ingestion.pending_attr_mods[buff_key].append(
            {
                "attr_type": str(fields.get("attrType") or ""),
                "bb_key": str(fields.get("bbKey") or ""),
                "use_key": str(fields.get("useKey") or "0"),
                "value": _safe_positive_rate(fields.get("val")),
            }
        )

    if " HP_V2 " in raw_line:
        fields = _extract_fields(raw_line)
        source_actor = _extract_character_key(fields.get("src"))
        attacker_actor = _extract_character_key(fields.get("atk"))
        if not source_actor and not attacker_actor and _extract_enemy_key(fields.get("src"), fields.get("atk")):
            # An explicitly identified enemy hit is outside player outgoing damage.
            return True
        character_key = source_actor or attacker_actor
        target_enemy_key = _extract_enemy_key(fields.get("tgt"))
        conflicting_actor = bool(source_actor and attacker_actor and source_actor != attacker_actor)
        if character_key is None or target_enemy_key is None or conflicting_actor:
            ingestion.unresolved_hits.append({
                "line_no": line_no, "ts_ms": ts_ms,
                "source_actor": fields.get("src"), "attacker_actor": fields.get("atk"),
                "target_actor": fields.get("tgt"), "raw_skill_key": fields.get("skill"),
                "packet_hit_value": fields.get("hit"),
                "reason": "conflicting_damage_actor" if conflicting_actor else "unresolved_damage_actor",
            })
            return True
        ingestion.enemy_counter[target_enemy_key] += 1

        character_name = _resolve_character_name(character_key) or character_key
        raw_hit_value = _coerce_int(fields.get("hit"))
        packet_hit_value = raw_hit_value if fields.get("hit") is not None else None
        packet_raw_value = _coerce_optional_float(fields.get("raw"))
        packet_final_value = _coerce_optional_float(fields.get("packetFinalValue"))
        has_enemy_hp_after = "eHP" in fields
        enemy_hp_after = _coerce_int(fields.get("eHP"))
        target_actor_id = fields.get("tgtId") if re.fullmatch(r"[1-9]\d*", fields.get("tgtId", "")) else None
        source_actor_id = fields.get("atkId") if re.fullmatch(r"[1-9]\d*", fields.get("atkId", "")) else None
        hp_state_key = _enemy_hp_state_key(target_enemy_key, target_actor_id)
        target_entity_stats = _entity_stats_snapshot_at(ingestion.entity_stats_timelines, target_actor_id, ts_ms)
        source_entity_stats = _entity_stats_snapshot_at(ingestion.entity_stats_timelines, source_actor_id, ts_ms)
        hit_value = _cap_enemy_overkill_damage(
            raw_hit_value,
            enemy_hp_after=enemy_hp_after if has_enemy_hp_after else None,
            previous_enemy_hp=ingestion.last_enemy_hp_by_target.get(hp_state_key),
        )
        damage_value_source = "packet_hit"
        if packet_hit_value is None:
            damage_value_source = "missing_packet_hit"
        elif hit_value != raw_hit_value:
            damage_value_source = "packet_hit_overkill_capped"
        if has_enemy_hp_after:
            ingestion.last_enemy_hp_by_target[hp_state_key] = enemy_hp_after
        crit_flag = _coerce_int(fields.get("critFlag"))
        raw_skill_key = fields.get("skill") or "unknown_skill"
        original_template_int_id = _coerce_int(fields.get("origTemplateIntId"), default=0) or None
        action_id = int(fields["actionId"]) if re.fullmatch(r"\d+", fields.get("actionId", "")) else None
        damage_unit_index = int(fields["damageUnitIndex"]) if re.fullmatch(r"\d+", fields.get("damageUnitIndex", "")) else None
        damage_unit_index_source = None
        skill_key = (
            _canonical_hit_skill_id_from_cast_context(
                raw_skill_key,
                character_key,
                ts_ms,
                original_template_int_id=original_template_int_id,
                target_enemy_key=target_enemy_key,
                recent_skill_casts_by_char=ingestion.recent_skill_casts_by_char,
                recent_numeric_buffs_by_source=ingestion.recent_numeric_buffs_by_source,
                action_id=action_id,
                damage_unit_index=damage_unit_index,
                template_type=fields.get("templateType"),
            )
            or _canonical_hit_skill_id(raw_skill_key, character_key)
        )
        skill_name = _resolve_skill_name(skill_key) or skill_key
        hit_index = _coerce_int(fields.get("hits"), default=1)
        skill_profile = _resolve_skill_profile(skill_key)
        skill_group_type = None
        skill_family_key = _resolve_skill_family_key(skill_key, skill_profile)
        if skill_profile is not None:
            try:
                skill_group_type = int(skill_profile.get("group_type"))
            except (TypeError, ValueError):
                skill_group_type = None
        alias_combo_consume = _COMBO_CONSUME_SKILL_ALIASES.get(skill_key)
        if alias_combo_consume is not None:
            skill_group_type = int(alias_combo_consume["group_type"])
            skill_family_key = str(alias_combo_consume["family_skill_key"])

        seq_match = _HIT_SEQ_RE.search(raw_line)
        seq = int(seq_match.group(1)) if seq_match else len(ingestion.hits) + 1
        dynamic_bb_values: dict[int, float] = {}
        for token in re.split(r"[,;]", str(fields.get("dynBB") or "")):
            key_text, separator, value_text = token.partition(":")
            key = _coerce_optional_int(key_text)
            value = _coerce_optional_float(value_text) if separator else None
            if key is not None and value is not None:
                dynamic_bb_values[key] = value
        calc_bb_values: dict[int, dict[str, float | str]] = {}
        for token in re.split(r"[,;]", str(fields.get("calcBB") or "")):
            group_text, separator, assignment = token.partition(":")
            group = _coerce_optional_int(group_text)
            key_text, assignment_separator, value_text = assignment.partition("=")
            if group is None or not separator or not assignment_separator or not key_text:
                continue
            numeric_value = _coerce_optional_float(value_text)
            calc_bb_values.setdefault(group, {})[key_text] = (
                numeric_value if numeric_value is not None else value_text
            )
        action_damage_element = _infer_skill_action_damage_element(
            skill_key,
            action_id,
            damage_unit_index,
        )
        static_damage_decorate_mask = None
        static_damage_decorate_mask_source = None
        damage_calculation = None
        if action_id is not None and damage_unit_index is not None:
            exact_units = [unit for unit in _load_skill_action_damage_units(str(skill_key)).get(action_id, [])
                           if type(unit.get('index')) is int and unit['index'] == damage_unit_index
                           and unit.get('damage_attribute_type') == 'hp']
            if len(exact_units) == 1 and exact_units[0].get('damage_attribute_type') == 'hp':
                unit = exact_units[0]
                if type(unit.get('damage_decorate_mask')) is int:
                    static_damage_decorate_mask = unit['damage_decorate_mask']
                    static_damage_decorate_mask_source = unit.get('damage_decorate_mask_source')
                damage_calculation = copy.deepcopy(unit.get('damage_calculation'))
        damage_element = action_damage_element
        damage_school = _damage_school_from_element(damage_element)
        hit = {
            "seq": seq,
            "line_no": line_no,
            "ts_ms": ts_ms,
            "character_key": character_key,
            "character_name": character_name,
            "target_enemy_key": target_enemy_key,
            "target_enemy_name": _resolve_enemy_name(target_enemy_key) or target_enemy_key,
            "raw_skill_key": raw_skill_key,
            "target_actor_id": target_actor_id,
            "source_actor_id": source_actor_id,
            "skill_key": skill_key,
            "skill_name": skill_name,
            "skill_level": _coerce_int(fields.get("skillLv"), default=0) or None,
            "template_int_id": _coerce_int(fields.get("templateIntId"), default=0) or None,
            "event_inst_id": fields.get("eventInstId") if re.fullmatch(r"[1-9]\d*", fields.get("eventInstId", "")) else None,
            "event_owner_id": fields.get("eventOwnerId") if re.fullmatch(r"[1-9]\d*", fields.get("eventOwnerId", "")) else None,
            "packet_seq_id": int(fields["packetSeq"]) if re.fullmatch(r"\d+", fields.get("packetSeq", "")) else None,
            "packet_session_id": fields.get('packetSessionId') or None,
            "packet_owner_id": (fields.get('packetOwnerId') if re.fullmatch(r'[1-9]\d*', fields.get('packetOwnerId', ''))
                                and int(fields['packetOwnerId']) < 2**64 else None),
            "packet_generation": (int(fields['packetGeneration']) if re.fullmatch(r'\d+', fields.get('packetGeneration', '')) else None),
            "client_tick_ms": int(fields["clientTick"]) if re.fullmatch(r"\d+", fields.get("clientTick", "")) else None,
            "action_id": action_id,
            "damage_unit_index": damage_unit_index,
            "damage_unit_index_source": damage_unit_index_source,
            "original_template_int_id": original_template_int_id,
            "dynamic_bb_signature": fields.get("dynBB"),
            "dynamic_bb_values": dynamic_bb_values,
            "calc_bb_signature": fields.get("calcBB"),
            "calc_bb_values": calc_bb_values,
            "damage_element": damage_element,
            "damage_school": damage_school,
            "damage_element_source": "official_action_unit" if damage_element else None,
            "damage_decorate_mask": None,
            "damage_decorate_mask_source": None,
            "static_damage_decorate_mask": static_damage_decorate_mask,
            "static_damage_decorate_mask_source": static_damage_decorate_mask_source,
            "damage_calculation": damage_calculation,
            "skill_group_type": skill_group_type,
            "skill_family_key": skill_family_key,
            "hit_value": hit_value,
            "raw_hit_value": raw_hit_value,
            "packet_hit_value": packet_hit_value,
            "packet_raw_value": packet_raw_value,
            "packet_final_value": packet_final_value,
            "damage_value_source": damage_value_source,
            "rdps_basis_value": hit_value,
            "rdps_basis_source": damage_value_source,
            "overkill_damage": max(0, raw_hit_value - hit_value),
            "enemy_hp_after": enemy_hp_after,
            "enemy_hp_after_observed": has_enemy_hp_after,
            "crit_flag": crit_flag,
            "critical_flag_observed": fields.get("critFlag") in {"0", "1"},
            "critical_observation": copy.deepcopy(ingestion.critical_stats_by_actor.get(source_actor_id)),
            "part_inst_id": _coerce_optional_int(fields.get("partInstId")),
            "hit_index": hit_index,
            "dpd_raw": None,
            "baseline": ingestion.baseline_by_character.get(character_key),
            "packet_modifier_seen": False,
            "packet_modifier_uids": {"attacker": [], "defender": []},
            "packet_attr_details": {"attacker": [], "defender": []},
        }
        _is_arts_strength_damage_hit(hit)
        _attach_target_entity_stats(hit, target_entity_stats)
        _attach_attacker_entity_stats(hit, source_entity_stats)
        # Scene snapshots are observations at their own timestamp. They do
        # not establish current-hit modifier state or passive coverage.
        ingestion.hits.append(hit)
        ingestion.hits_by_seq[seq] = hit
        if ingestion.loadout_by_char and character_key not in ingestion.loadout_by_char:
            # A battle actor outside the frozen loadout proves that the
            # client carried an old bag team across an empty dungeon-team
            # packet. Stop using that loadout for subsequent inference.
            ingestion.loadout_by_char.clear()
            ingestion.active_suits_by_char.clear()
            ingestion.active_weapons_by_char.clear()
        if character_key not in ingestion.roster_seen:
            ingestion.roster_seen.add(character_key)
            ingestion.roster_order.append(character_key)

        participant = ingestion.participant_totals[character_key]
        participant["character_key"] = character_key
        participant["character_name"] = character_name
        participant["total_damage"] += hit_value
        participant["max_hit"] = max(participant["max_hit"], hit_value)
        participant["crit_hits"] += 1 if crit_flag else 0
        participant["hit_count"] += 1

        skill_entry = ingestion.skill_totals[(character_key, skill_key)]
        skill_entry["character_key"] = character_key
        skill_entry["character_name"] = character_name
        skill_entry["skill_key"] = skill_key
        skill_entry["skill_name"] = skill_name
        skill_entry["total_damage"] += hit_value
        skill_entry["max_damage"] = max(skill_entry["max_damage"], hit_value)
        skill_entry["hit_count"] += 1
        if hit_index == 1:
            skill_entry["cast_count"] += 1

    elif " BUFF_START " in raw_line:
        fields = _extract_fields(raw_line)
        owner_value = str(fields.get("owner") or "")
        owner_key = _extract_character_key(owner_value)
        target_enemy_key = _extract_enemy_key(fields.get("owner"))
        raw_buff_key = _normalize_buff_id(fields.get("id"))
        raw_source_key = _extract_character_key(fields.get("src"))
        source_key = raw_source_key
        mapping_hint = _packet_numeric_buff_hint(raw_buff_key)
        mapping_rejected = False
        if mapping_hint and not _packet_mapping_applies(
            mapping_hint,
            owner_key=owner_key,
            source_key=source_key,
            active_suits_by_char=ingestion.active_suits_by_char,
            active_weapons_by_char=ingestion.active_weapons_by_char,
        ):
            mapping_rejected = True
            mapping_hint = {}
        buff_key = _canonical_packet_buff_id(
            raw_buff_key,
            owner_key=owner_key,
            source_key=source_key,
            active_suits_by_char=ingestion.active_suits_by_char,
            active_weapons_by_char=ingestion.active_weapons_by_char,
        )
        is_weapon_buff = bool(_WEAPON_BUFF_RE.match(buff_key))
        player_keys = [key for key in (source_key, owner_key) if key]
        if not player_keys and not target_enemy_key:
            ingestion.pending_buff_record = None
            return True
        for player_key in player_keys:
            if player_key not in ingestion.roster_seen:
                ingestion.roster_seen.add(player_key)
                ingestion.roster_order.append(player_key)
        if source_key:
            source_participant = ingestion.participant_totals[source_key]
            source_participant["character_key"] = source_key
            source_participant["character_name"] = _resolve_character_name(source_key) or source_key
        if owner_key:
            owner_participant = ingestion.participant_totals[owner_key]
            owner_participant["character_key"] = owner_key
            owner_participant["character_name"] = _resolve_character_name(owner_key) or owner_key
        attr_mods = ingestion.pending_attr_mods.pop(buff_key, [])
        if not attr_mods and raw_buff_key != buff_key:
            attr_mods = ingestion.pending_attr_mods.pop(raw_buff_key, [])
        source_skill_context = _recent_source_skill_context_for_buff(
            source_key,
            ts_ms,
            ingestion.recent_skill_casts_by_char,
        ) or {}
        raw_uid = str(fields.get("uid") or "")
        # uint32 max is the protocol's invalid/sentinel instance ID. Keep
        # these rows for diagnostics, but never create a live window from
        # them or evaluate them as a semantic buff instance.
        invalid_uid = raw_uid in {"0", "4294967295"}
        buff_record = {
            "uid": "" if invalid_uid else raw_uid,
            "uid_observation_only": invalid_uid,
            "line_no": line_no,
            "ts_ms": ts_ms,
            "source_character_key": source_key,
            "source_character_name": _resolve_character_name(source_key) or source_key,
            "source_weapon_template": ingestion.active_weapons_by_char.get(source_key),
            "source_skill_key": source_skill_context.get("source_skill_key"),
            "source_skill_family_key": source_skill_context.get("source_skill_family_key"),
            "raw_source_character_key": raw_source_key,
            "raw_source_character_name": _resolve_character_name(raw_source_key) or raw_source_key,
            "raw_source": fields.get("src"),
            "target_character_key": owner_key,
            "target_character_name": _resolve_character_name(owner_key) or owner_key,
            "target_enemy_key": target_enemy_key,
            "target_enemy_name": _resolve_enemy_name(target_enemy_key) or target_enemy_key,
            "owner_raw": owner_value,
            "target_actor_id": fields.get("ownerId") if re.fullmatch(r"[1-9]\d*", fields.get("ownerId", "")) else None,
            "source_actor_id": fields.get("srcId") if re.fullmatch(r"[1-9]\d*", fields.get("srcId", "")) else None,
            "event_key": buff_key,
            "raw_event_key": raw_buff_key,
            "packet_mapping": mapping_hint if mapping_hint else None,
            "packet_mapping_rejected": mapping_rejected,
            "raw_duration_ms": _duration_ms_from_seconds(fields.get("dur")),
            "end_ts_ms": None,
            "bb_keys": [row["bb_key"] for row in attr_mods if row["bb_key"]],
            "bb_values": {},
            "attr_types": [row["attr_type"] for row in attr_mods if row["attr_type"]],
            "attr_mods": attr_mods,
            "is_weapon_buff": is_weapon_buff,
            "instance_start_line_no": line_no,
            "enable_observations": [],
            "creation_observations": [],
            "attribute_refresh_snapshots": [],
            "_observed_bb_values": {},
        }
        _apply_enemy_status_bb_overrides(buff_record, context_enemy_hint=None)
        uid_key = str(buff_record.get("uid") or "")
        if uid_key:
            existing = ingestion.active_buff_starts_by_uid.get(uid_key)
            if existing is not None:
                # A new observation of a live UID changes its snapshot,
                # not the number of simultaneous Buff instances.
                buff_record['_previous_snapshot_record'] = existing
                buff_record['_previous_snapshot_boundary'] = {
                    'snapshot_end_ts_ms': existing.get('snapshot_end_ts_ms'),
                    'snapshot_end_line_no': existing.get('snapshot_end_line_no')}
                existing['snapshot_end_ts_ms'] = ts_ms
                existing['snapshot_end_line_no'] = line_no
                buff_record['snapshot_update'] = True
                buff_record['instance_start_line_no'] = existing.get('instance_start_line_no', existing['line_no'])
                buff_record['source_weapon_template'] = existing.get('source_weapon_template')
                identity_fields = ('source_actor_id', 'target_actor_id', 'source_character_key',
                                   'target_character_key', 'target_enemy_key')
                conflict = bool(existing.get('rdps_live_identity_conflict')) or any(
                    existing.get(key) and buff_record.get(key) and existing[key] != buff_record[key]
                    for key in identity_fields)
                known_roots = _load_current_buff_roots()
                if existing.get('event_key') in known_roots and buff_record['event_key'] in known_roots:
                    conflict = conflict or existing['event_key'] != buff_record['event_key']
                if conflict:
                    buff_record['rdps_live_identity_conflict'] = True
                else:
                    for key in (*identity_fields, 'source_skill_key', 'source_skill_family_key'):
                        if not buff_record.get(key) and existing.get(key):
                            buff_record[key] = existing[key]
                    # State history belongs to this live UID. Sharing it
                    # retains later observations while evaluation uses
                    # the hit's own operation/time boundary.
                    buff_record['enable_observations'] = existing['enable_observations']
                    buff_record['creation_observations'] = copy.deepcopy(existing.get('creation_observations') or [])
                    buff_record['attribute_refresh_snapshots'] = existing.get('attribute_refresh_snapshots', [])
                    if existing.get('_dynamic_pending_state') is not None:
                        buff_record['_dynamic_pending_state'] = copy.deepcopy(existing['_dynamic_pending_state'])
                        buff_record['_dynamic_seen_contexts'] = set(existing.get('_dynamic_seen_contexts') or [])
                    buff_record['_dynamic_unresolved_keys'] = set(existing.get('_dynamic_unresolved_keys') or [])
                    if existing.get('rdps_dynamic_identity_conflict'):
                        buff_record['rdps_dynamic_identity_conflict'] = True
                    if existing.get('rdps_conflicting_enable_state'):
                        buff_record['rdps_conflicting_enable_state'] = True
                    if existing.get('event_key') == buff_record['event_key']:
                        buff_record['bb_values'] = dict(existing.get('bb_values') or {})
                        buff_record['bb_keys'] = list(existing.get('bb_keys') or [])
                        buff_record['origin_observations'] = copy.deepcopy(existing.get('origin_observations') or [])
                        if not attr_mods:
                            buff_record['attr_mods'] = copy.deepcopy(existing.get('attr_mods') or [])
                            buff_record['attr_types'] = list(existing.get('attr_types') or [])
        ingestion.buff_starts.append(buff_record)
        if raw_buff_key.isdigit() and source_key:
            rows = ingestion.recent_numeric_buffs_by_source[str(source_key)]
            rows.append(buff_record)
            del rows[:-128]
        if uid_key:
            ingestion.active_buff_starts_by_uid[uid_key] = buff_record
        current_buff_record = buff_record

    elif " BUFF_END " in raw_line:
        fields = _extract_fields(raw_line)
        uid = str(fields.get("uid") or "")
        if uid:
            for unresolved in ingestion.unresolved_buff_actions:
                if unresolved.get('uid') == uid and unresolved.get('end_ts_ms') is None:
                    unresolved.update(end_ts_ms=ts_ms, end_line_no=line_no)
            buff_record = ingestion.active_buff_starts_by_uid.pop(uid, None)
            if buff_record is not None:
                buff_record["end_ts_ms"] = ts_ms
                buff_record["end_line_no"] = line_no
                current_buff_record = buff_record

    ingestion.pending_buff_record = current_buff_record
    return False
