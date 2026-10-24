from __future__ import annotations
import json
import re
from typing import Any
from endfield_pcap.trace.formatting import (
    _intish,
    _floatish,
    _trace_string,
    _modifier_uid_tokens,
    _attr_info_tokens,
)


class DamageEvents:
    def _handle_update_atb_info(self, event: dict[str, Any], ts_ms: int) -> None:
        # 技力(atb)更新：主控角色重击(连招末段)回技力 = reason=AddValue 的正 delta。
        # 排轴据此区分主控重击 vs 非主控 AI 重击。owner 归到角色，source 归到触发技能。
        owner_id = _intish(event.get("owner_id"))
        owner = self._name_for_id(owner_id)
        owner_hint = self._character_from_template(owner) or ""
        source_skill = self._resolve_skill_template(
            event.get("template_str_id"),
            event.get("template_int_id"),
            owner_hint=owner_hint,
        )
        orig_source_skill = self._resolve_skill_template(
            event.get("orig_template_str_id"),
            event.get("orig_template_int_id"),
            owner_hint=owner_hint,
        )
        seq = _intish(event.get("seq_id")) or 0
        client_tick = _intish(event.get("client_tick_tms")) or 0
        atb_value = _floatish(event.get("atb_value"))
        recovery_speed = _floatish(event.get("atb_recovery_speed"))
        delta = _floatish(event.get("delta_value"))
        parts = [
            "ATB_UPDATE",
            f"seq={seq}",
            f"tick={client_tick}",
            f"owner={owner}",
            f"ownerId={owner_id if owner_id is not None else 'unknown'}",
            f"reason={event.get('reason') or 'unknown'}",
            f"atb={atb_value:.6g}" if atb_value is not None else "atb=unknown",
            f"recoverySpeed={recovery_speed:.6g}" if recovery_speed is not None else "recoverySpeed=unknown",
            f"delta={delta:.6g}" if delta is not None else "delta=unknown",
            f"source={source_skill or event.get('template_str_id') or 'unknown'}",
            f"origSource={orig_source_skill or event.get('orig_template_str_id') or 'unknown'}",
        ]
        self._line(ts_ms, " ".join(parts))

    def _handle_modify_poise_value(self, event: dict[str, Any], ts_ms: int) -> None:
        attacker_id = _intish(event.get("attacker_inst_id"))
        attacker = self._name_for_id(attacker_id)
        owner_hint = self._character_from_template(attacker) or ""
        source_skill = self._resolve_skill_template(
            event.get("template_str_id"),
            event.get("template_int_id"),
            owner_hint=owner_hint,
        )
        original_source_skill = self._resolve_skill_template(
            event.get("orig_template_str_id"),
            event.get("orig_template_int_id"),
            owner_hint=owner_hint,
        )
        seq = _intish(event.get("seq_id")) or 0
        client_tick = _intish(event.get("client_tick_tms")) or 0
        template_int_id = _intish(event.get("template_int_id"))
        orig_template_int_id = _intish(event.get("orig_template_int_id"))
        action_id = _intish(event.get("action_id"))
        value = _floatish(event.get("value"))
        cur_poise_value = _floatish(event.get("cur_poise_value"))
        parts = [
            "POISE_V1",
            f"seq={seq}",
            f"tick={client_tick}",
            f"type={event.get('modify_type') or 'unknown'}",
            f"value={value:.6g}" if value is not None else "value=unknown",
            f"cur={cur_poise_value:.6g}" if cur_poise_value is not None else "cur=unknown",
            f"attacker={attacker}",
            f"attackerId={attacker_id if attacker_id is not None else 'unknown'}",
            f"ownerType={event.get('owner_type') or 'unknown'}",
            f"sourceType={event.get('template_type') or 'unknown'}",
            f"source={source_skill or event.get('template_str_id') or 'unknown'}",
            f"sourceInt={template_int_id if template_int_id is not None else 'unknown'}",
            f"origSourceType={event.get('orig_template_type') or 'unknown'}",
            f"origSource={original_source_skill or event.get('orig_template_str_id') or 'unknown'}",
            f"origSourceInt={orig_template_int_id if orig_template_int_id is not None else 'unknown'}",
            f"actionId={action_id if action_id is not None else 'unknown'}",
        ]
        self._line(ts_ms, " ".join(parts))

    def _handle_battle_state(self, event: dict[str, Any], ts_ms: int) -> None:
        is_in_battle = bool(event.get("is_in_battle"))
        if is_in_battle and not self._battle_active:
            is_war_echo_continuation = (
                self._official_timer_required() and self._official_timer_expected
            )
            self._challenge_pass_confirmed = False
            self._battle_active = True
            if self._official_timer_required():
                self._official_timer_expected = True
                self._official_timer_game_id = self._activity_id()
                if self._official_timer_observed_start_ts_ms is None:
                    self._official_timer_observed_start_ts_ms = ts_ms
            self._battle_start_ts_ms = ts_ms
            seq = _intish(event.get("seq_id")) or 0
            raw_client_tick = _intish(event.get("client_tick_tms"))
            client_tick = raw_client_tick or 0
            self._battle_start_client_tick_ms = raw_client_tick
            if self._current_dungeon_context is not None and not self._battle_dungeon_context_emitted:
                self._write_dungeon_context(ts_ms, self._current_dungeon_context)
                self._battle_dungeon_context_emitted = True
            if is_war_echo_continuation:
                self._line(
                    ts_ms,
                    (
                        "BATTLE_PHASE_START "
                        f"seq={seq} source=BattleOpModifyBattleState "
                        f"gameId={self._activity_id()}"
                    ),
                )
                return
            timer_source = "PacketBattleState" if raw_client_tick is not None else "BattleOpModifyBattleState"
            official = 1 if raw_client_tick is not None else 0
            self._line(
                ts_ms,
                f"GAME_TIMER_START seq={seq} source={timer_source} startMs={client_tick} expireMs=0 official={official}",
            )
        elif not is_in_battle and self._battle_active and self._official_timer_required():
            self._line(
                ts_ms,
                (
                    "OFFICIAL_TIMER_AWAIT source=BattleOpModifyBattleState "
                    f"gameId={self._activity_id()} "
                    f"officialStartSeen={1 if self._official_timer_active else 0}"
                ),
            )
            self._clear_packet_battle_window()
        elif not is_in_battle and self._battle_active:
            self._battle_active = False
            seq = _intish(event.get("seq_id")) or 0
            raw_client_tick = _intish(event.get("client_tick_tms"))
            client_tick = raw_client_tick or 0
            start_tick = self._battle_start_client_tick_ms if self._battle_start_client_tick_ms is not None else client_tick
            packet_elapsed_ms = (
                client_tick - start_tick
                if raw_client_tick is not None and self._battle_start_client_tick_ms is not None
                else None
            )
            wall_elapsed_ms = max(ts_ms - self._battle_start_ts_ms, 0) if self._battle_start_ts_ms is not None else 0
            if packet_elapsed_ms is not None and packet_elapsed_ms >= 0:
                timer_source = "PacketBattleState"
                official = 1
                elapsed_ms = wall_elapsed_ms
            else:
                timer_source = "BattleOpModifyBattleState"
                official = 0
                elapsed_ms = wall_elapsed_ms
            packet_elapsed_token = (
                f" packetElapsedMs={packet_elapsed_ms}"
                if packet_elapsed_ms is not None and packet_elapsed_ms >= 0
                else ""
            )
            wall_elapsed_token = (
                f" wallElapsedMs={wall_elapsed_ms}"
                if wall_elapsed_ms > 0 and wall_elapsed_ms != elapsed_ms
                else ""
            )
            self._line(
                ts_ms,
                (
                    f"GAME_TIMER_END seq={seq} source={timer_source} "
                    f"elapsedMs={elapsed_ms} startMs={start_tick} endMs={client_tick} "
                    f"expireMs=0 sane={1 if elapsed_ms > 0 else 0} official={official}"
                    f"{packet_elapsed_token}{wall_elapsed_token}"
                ),
            )
            self._battle_start_ts_ms = None
            self._battle_start_client_tick_ms = None
            self._battle_dungeon_context_emitted = False

    def _write_damage(self, ts_ms: int, event: dict[str, Any], damage_action: Any) -> None:
        if not isinstance(damage_action, dict):
            return
        attacker_id = _intish(damage_action.get("attacker_id")) or _intish(event.get("owner_id"))
        attacker = self._name_for_id(attacker_id)
        skill = self._trigger_skill_template(event, attacker)
        skill_level = int(_intish(event.get("level")) or 0)
        template_int_id = int(_intish(event.get("template_int_id")) or 0)
        action_payload = event.get("action") if isinstance(event.get("action"), dict) else {}
        action_id = _intish(action_payload.get("action_id"))
        original_template = damage_action.get("original_source_template_id")
        original_template_int_id = int(_intish((original_template or {}).get("int_id")) or 0) if isinstance(original_template, dict) else 0
        original_source_skill = self._resolve_skill_template(
            (original_template or {}).get("str_id") if isinstance(original_template, dict) else None,
            original_template_int_id,
        )
        # Only the explicit original-source template is identity evidence for
        # an otherwise unknown attacker ID. The event's display skill alone
        # must not fabricate an actor mapping.
        actor_template = self._character_from_template(original_source_skill)
        if attacker_id and actor_template and self.id_to_name.get(attacker_id) is None:
            self.id_to_name[attacker_id] = actor_template
            self._line(
                ts_ms,
                f"ACTOR_MAP id={attacker_id} template={actor_template} "
                f"source=damage_original_skill skill={original_source_skill or skill}",
            )
        attacker = self._name_for_id(attacker_id)
        event_inst_id = int(_intish(event.get("inst_id")) or 0)
        dynamic_bb_rows = list(self.recent_dynamic_bb_by_inst.get(event_inst_id, [])) if event_inst_id else []
        dynamic_bb_text = ",".join(f"{bb_action}:{bb_value:.6g}" for bb_action, bb_value in dynamic_bb_rows)
        calc_bb_rows = list(self.recent_calc_bb_by_inst.get(event_inst_id, [])) if event_inst_id else []
        calc_bb_text = ",".join(
            f"{bb_action}:{bb_key}={bb_value:.6g}"
            for bb_action, bb_key, bb_value in calc_bb_rows
        )
        details = damage_action.get("details") or []
        if not isinstance(details, list):
            return
        detail_presence_rows = event.get("damage_detail_presence") if isinstance(event.get("damage_detail_presence"), list) else []
        for detail_index, detail in enumerate(details):
            if not isinstance(detail, dict):
                continue
            raw_value = abs(_floatish(detail.get("value")) or 0.0)
            hit = int(raw_value + 0.5)
            if hit <= 0:
                continue
            target_id = _intish(detail.get("target_id"))
            target = self._name_for_damage_target(target_id, attacker)
            cur_hp = _floatish(detail.get("cur_hp")) or 0.0
            is_crit = bool(detail.get("is_crit"))
            damage_unit_index = _intish(detail.get("damage_unit_index"))
            part_inst_id = int(_intish(detail.get("part_inst_id")) or 0)
            detail_presence = (
                detail_presence_rows[detail_index]
                if detail_index < len(detail_presence_rows) and isinstance(detail_presence_rows[detail_index], dict)
                else {}
            )
            calc_args = detail.get("calculate_damage_check_args")
            calc_tokens: list[str] = []
            if isinstance(calc_args, dict):
                calc_field_names = {
                    "client_calc_result_value": "clientCalc",
                    "client_final_damage_scale": "clientFinalScale",
                    "client_attack_value": "clientAttack",
                    "client_crit_add_scale": "clientCritAdd",
                    "client_def_attr_defender_def": "clientDef",
                    "client_def_resistance": "clientDefResistance",
                    "client_dmg_type_resistance": "clientDmgTypeResistance",
                    "client_defender_poise_factor": "clientPoiseFactor",
                    "client_ignite_damage_scalar": "clientIgniteScalar",
                    "client_final_value": "clientFinalValue",
                    "client_weak_damage_scalar": "clientWeakScalar",
                    "client_shelter_damage_scalar": "clientShelterScalar",
                    "client_physical_infliction_damage_scalar": "clientPhysicalInflictionScalar",
                }
                for field_name, token_name in calc_field_names.items():
                    value = _floatish(calc_args.get(field_name))
                    if value is not None:
                        calc_tokens.append(f"{token_name}={value:.6g}")
            shared = 3 if is_crit else 2
            packet_identity_tokens = []
            if isinstance(event.get('session_id'), str) and event['session_id']:
                packet_identity_tokens.append('packetSessionId=' + _trace_string(event['session_id']))
            packet_owner = event.get('operation_owner_id')
            if (type(packet_owner) in (int, str) and re.fullmatch(r'[0-9]+', str(packet_owner))
                    and 0 <= int(packet_owner) < 2**64):
                packet_identity_tokens.append('packetOwnerId=' + str(packet_owner))
            if type(event.get('generation')) is int and 0 <= event['generation'] < 2**32:
                packet_identity_tokens.append('packetGeneration=' + str(event['generation']))
            self.hit_seq += 1
            self._line(
                ts_ms,
                (
                    f'HP_V2 #{self.hit_seq} hit={hit} cum={hit} raw={raw_value:.2f} '
                    f"packetFinalValue={raw_value:.17g} "
                    f'pHP=0 eHP={cur_hp:.0f} skill="{skill}" hits=1 '
                    f"skillLv={skill_level if skill_level > 0 else 'unknown'} "
                    f"templateIntId={template_int_id if template_int_id > 0 else 'unknown'} "
                    f"templateType={event.get('template_type') or 'unknown'} "
                    f"actionId={action_id if action_id is not None else 'unknown'} "
                    f"origTemplateIntId={original_template_int_id if original_template_int_id > 0 else 'unknown'} "
                    f"damageUnitIndex={damage_unit_index if damage_unit_index is not None else 'unknown'} "
                    f"partInstId={part_inst_id if part_inst_id > 0 else 'unknown'} "
                    f"dynBB={dynamic_bb_text if dynamic_bb_text else 'unknown'} "
                    f"calcBB={calc_bb_text if calc_bb_text else 'unknown'} "
                    f"src={attacker} tgt={target} atk={attacker} "
                    f"atkId={attacker_id if attacker_id else 'unknown'} "
                    f"tgtId={target_id if target_id else 'unknown'} seg=0 "
                    f"shared={shared} critFlag={1 if is_crit else 0} critDmg=-1.0000"
                    " "
                    f"eventInstId={event_inst_id if event_inst_id > 0 else 'unknown'} "
                    f"eventOwnerId={_intish(event.get('owner_id')) or 'unknown'} "
                    f"packetSeq={event.get('seq_id') if type(event.get('seq_id')) is int else 'unknown'} "
                    f"clientTick={event.get('client_tick_tms') if type(event.get('client_tick_tms')) is int else 'unknown'} "
                    f"{(' '.join(packet_identity_tokens) + ' ') if packet_identity_tokens else ''}"
                    f"{(' ' + ' '.join(calc_tokens)) if calc_tokens else ''}"
                ),
            )
            modifier_args = detail.get("modifier_args") if isinstance(detail.get("modifier_args"), dict) else {}
            atk_mods = _modifier_uid_tokens(modifier_args, "attacker_modifiers")
            def_mods = _modifier_uid_tokens(modifier_args, "defender_modifiers")
            if atk_mods or def_mods:
                self._line(
                    ts_ms,
                    f"PKT_MOD #{self.hit_seq} atk=[{' '.join(atk_mods)}] def=[{' '.join(def_mods)}]",
                )
                # Keep each handle's processor index and debug arguments;
                # UID-only display tokens cannot identify the applied entry.
                self._line(ts_ms, f"PKT_MOD_DETAIL #{self.hit_seq} " + json.dumps({
                    'attacker': modifier_args.get('attacker_modifiers') or [],
                    'defender': modifier_args.get('defender_modifiers') or [],
                    'packetSessionId': event.get('session_id'),
                    'packetSeq': event.get('seq_id'),
                    'damageUnitIndex': detail.get('damage_unit_index'),
                    'partInstId': detail.get('part_inst_id'),
                }, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            battle_report_info = detail.get("battle_report_info") if isinstance(detail.get("battle_report_info"), dict) else {}
            report_present = (detail_presence.get('has_battle_report_info')
                              if type(detail_presence.get('has_battle_report_info')) is bool
                              else True if isinstance(detail.get('battle_report_info'), dict) else None)
            if type(report_present) is bool:
                self._line(ts_ms, f"PKT_ATTR_INFO #{self.hit_seq} " + json.dumps({
                    'reportPresent': report_present, 'packetSeq': event.get('seq_id'),
                    'packetSessionId': event.get('session_id'),
                }, ensure_ascii=False, separators=(',', ':')))
            atk_attrs = _attr_info_tokens(battle_report_info, "attacker_attr_modify_info")
            def_attrs = _attr_info_tokens(battle_report_info, "defender_attr_modify_info")
            if atk_attrs or def_attrs:
                self._line(
                    ts_ms,
                    f"PKT_ATTR #{self.hit_seq} atk=[{' '.join(atk_attrs)}] def=[{' '.join(def_attrs)}]",
                )
            if detail_presence:
                has_calc_check = bool(detail_presence.get("has_calculation_check_args"))
                has_calc = bool(detail_presence.get("has_calculate_damage_check_args"))
                proc_count = int(_intish(detail_presence.get("processor_debug_args_count")) or 0)
                has_att_dbg = bool(detail_presence.get("has_attacker_attr_modifier_debug_data"))
                has_def_dbg = bool(detail_presence.get("has_defender_attr_modifier_debug_data"))
                atk_mod_dbg_handles = int(_intish(detail_presence.get("attacker_modifier_debug_handle_count")) or 0)
                def_mod_dbg_handles = int(_intish(detail_presence.get("defender_modifier_debug_handle_count")) or 0)
                atk_mod_dbg_args = int(_intish(detail_presence.get("attacker_modifier_debug_arg_entry_count")) or 0)
                def_mod_dbg_args = int(_intish(detail_presence.get("defender_modifier_debug_arg_entry_count")) or 0)
                if (
                    has_calc_check
                    or has_calc
                    or proc_count
                    or has_att_dbg
                    or has_def_dbg
                    or atk_mod_dbg_handles
                    or def_mod_dbg_handles
                    or atk_mod_dbg_args
                    or def_mod_dbg_args
                ):
                    self._line(
                        ts_ms,
                        (
                            f"PKT_DBG #{self.hit_seq} "
                            f"calcCheck={1 if has_calc_check else 0} "
                            f"calcArgs={1 if has_calc else 0} "
                            f"procArgs={proc_count} "
                            f"attDbg={1 if has_att_dbg else 0} "
                            f"defDbg={1 if has_def_dbg else 0} "
                            f"atkModDbgHandles={atk_mod_dbg_handles} "
                            f"defModDbgHandles={def_mod_dbg_handles} "
                            f"atkModDbgArgs={atk_mod_dbg_args} "
                            f"defModDbgArgs={def_mod_dbg_args}"
                        ),
                    )
        if event_inst_id:
            self.recent_dynamic_bb_by_inst.pop(event_inst_id, None)
            self.recent_calc_bb_by_inst.pop(event_inst_id, None)
