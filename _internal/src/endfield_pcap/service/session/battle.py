from __future__ import annotations
from typing import Any
from endfield_pcap.models import BattleLogEvent


class BattleEvents:
    def _emit_battle_events(self, message: Any, timestamp_ms: int) -> None:
        client_data = getattr(message, "client_data", None)
        if client_data is None:
            return
        emitted_clock_ticks: set[int] = set()
        for op in getattr(client_data, "op_list", []):
            op_type_name = self._field_enum_name(op, "op_type")
            if op_type_name is None:
                continue
            seq_id = int(getattr(op, "seq_id", 0)) or None
            client_tick_tms = int(getattr(op, "client_tick_tms", 0)) or None

            if (getattr(self, "rotation_clock_trace", False) and client_tick_tms is not None
                    and client_tick_tms > 0 and client_tick_tms not in emitted_clock_ticks):
                emitted_clock_ticks.add(client_tick_tms)
                self._emit_event(BattleLogEvent(
                    session_id=self.session_id, timestamp_ms=timestamp_ms,
                    event_type="GAME_CLOCK_TICK",
                    payload={"source": "CS_BATTLE_OP", "tick_ms": client_tick_tms, "seq_id": seq_id},
                ))

            if op_type_name == "BattleOpSkillAttach":
                attach_data = getattr(op, "skill_attach_op_data", None)
                if attach_data is None:
                    continue
                template_type, template_int_id, template_str_id = self._template_id_payload(
                    getattr(attach_data, "skill_id", None)
                )
                payload: dict[str, object | None] = {
                    "seq_id": seq_id,
                    "client_tick_tms": client_tick_tms,
                    "src_inst_id": int(getattr(attach_data, "src_inst_id", 0)) or None,
                    "skill_inst_id": int(getattr(attach_data, "skill_inst_id", 0)) or None,
                    "skill_lv": int(getattr(attach_data, "skill_lv", 0)) or None,
                    "skill_source": self._field_enum_name(attach_data, "skill_source"),
                    "template_type": template_type,
                    "template_int_id": template_int_id,
                }
                if template_str_id:
                    payload["template_str_id"] = template_str_id
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload=payload,
                    )
                )
                continue
            if op_type_name == "BattleOpSkillDetach":
                detach_data = getattr(op, "skill_detach_op_data", None)
                if detach_data is None:
                    continue
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "skill_inst_id": int(getattr(detach_data, "skill_inst_id", 0)) or None,
                        },
                    )
                )
                continue
            if op_type_name == "BattleOpSkillStartCast":
                cast_data = getattr(op, "skill_start_cast_op_data", None)
                if cast_data is None:
                    continue
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "owner_id": int(getattr(op, "owner_id", 0)) or None,
                            "skill_inst_id": int(getattr(cast_data, "inst_id", 0)) or None,
                        },
                    )
                )
                continue
            if op_type_name == "BattleOpSkillEndCast":
                cast_data = getattr(op, "skill_end_cast_op_data", None)
                if cast_data is None:
                    continue
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "owner_id": int(getattr(op, "owner_id", 0)) or None,
                            "skill_inst_id": int(getattr(cast_data, "inst_id", 0)) or None,
                        },
                    )
                )
                continue
            if op_type_name == "BattleOpTriggerAction":
                self._emit_trigger_action_event(op, seq_id, client_tick_tms, timestamp_ms)
                continue
            if op_type_name == 'BattleOpTriggerKeyword':
                if op.WhichOneof('op_data_impl') != 'trigger_keyword_op_data':
                    continue
                keyword = op.trigger_keyword_op_data
                self._emit_event(BattleLogEvent(
                    session_id=self.session_id, timestamp_ms=timestamp_ms, event_type=op_type_name,
                    payload={'seq_id': int(op.seq_id), 'client_tick_tms': int(op.client_tick_tms),
                             'owner_id': str(op.owner_id), 'generation': int(op.generation),
                             'buff_inst_id': str(keyword.buff_inst_id),
                             'add_buff_num_id': int(keyword.add_buff_num_id),
                             'modify': [{'config_index': int(row.config_index),
                                         'modify_value': float(row.modify_value)} for row in keyword.modify],
                             'operation_payload_case': op.WhichOneof('op_data_impl')},
                ))
                continue
            if op_type_name == "BattleOpSetBuffEnableState":
                state_data = getattr(op, 'set_buff_enable_state_op_data', None)
                if state_data is None:
                    continue
                self._emit_event(BattleLogEvent(
                    session_id=self.session_id, timestamp_ms=timestamp_ms, event_type=op_type_name,
                    payload={'seq_id': int(op.seq_id), 'client_tick_tms': int(op.client_tick_tms),
                             'owner_id': int(op.owner_id), 'generation': int(op.generation),
                             'states': {str(uid): enabled for uid, enabled in state_data.buff_inst_id_to_enable_state.items()}},
                ))
                continue
            if op_type_name == "BattleOpFinishBuff":
                finish_data = getattr(op, "finish_buff_op_data", None)
                if finish_data is None:
                    continue
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "buff_inst_id": int(getattr(finish_data, "buff_inst_id", 0)) or None,
                        },
                    )
                )
                continue
            if op_type_name == "BattleOpAddBuff":
                add_data = getattr(op, "add_buff_op_data", None)
                if add_data is None:
                    continue
                _, template_int_id, template_str_id = self._template_id_payload(getattr(add_data, "buff_id", None))
                payload: dict[str, object | None] = {
                    "seq_id": seq_id,
                    "client_tick_tms": client_tick_tms,
                    "operation_owner_id": str(op.owner_id) if hasattr(op, "owner_id") else None,
                    "generation": int(op.generation) if hasattr(op, "generation") else None,
                    "int_id": template_int_id,
                    "buff_inst_id": int(getattr(add_data, "buff_inst_id", 0)) or None,
                    "src_inst_id": int(getattr(add_data, "src_inst_id", 0)) or None,
                    "target_inst_id": int(getattr(add_data, "target_inst_id", 0)) or None,
                    "assigned_items": self._message_to_payload(getattr(add_data, "assigned_items", None)),
                }
                buff_template = getattr(add_data, "buff_id", None)
                if buff_template is not None and hasattr(buff_template, "WhichOneof"):
                    payload["buff_template_id"] = self._message_to_payload(buff_template, include_implicit_defaults=True)
                    payload["buff_template_id_case"] = buff_template.WhichOneof("id_impl")
                if template_str_id:
                    payload["str_id"] = template_str_id
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload=payload,
                    )
                )
                continue
            if op_type_name == "BattleOpEnablePassiveSkill":
                enable_data = getattr(op, "skill_enable_op_data", None)
                if enable_data is None:
                    continue
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "skill_inst_id": int(getattr(enable_data, "skill_inst_id", 0)) or None,
                        },
                    )
                )
                continue
            if op_type_name == "BattleOpEntityDie":
                die_data = getattr(op, "entity_die_op_data", None)
                if die_data is None:
                    continue
                entity_inst_id = int(getattr(die_data, "entity_inst_id", 0)) or None
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "entity_inst_id": entity_inst_id,
                        },
                    )
                )
                if (
                    self.merge_multi_phase_enemy_battles
                    and self.merged_battle_active
                    and entity_inst_id is not None
                    and entity_inst_id in self.tracked_enemy_inst_ids
                ):
                    self._emit_event(
                        BattleLogEvent(
                            session_id=self.session_id,
                            timestamp_ms=timestamp_ms,
                            event_type="BattleOpModifyBattleState",
                            payload={
                                "seq_id": seq_id,
                                "client_tick_tms": client_tick_tms,
                                "is_in_battle": False,
                            },
                        )
                    )
                    self.merged_battle_active = False
                    self.tracked_enemy_inst_ids.clear()
                continue
            if op_type_name == "BattleOpEntityValueModify":
                value_data = getattr(op, "entity_value_modify_data", None)
                if value_data is None:
                    continue
                template_type, template_int_id, template_str_id = self._template_id_payload(getattr(value_data, "template_id", None))
                orig_template_type, orig_template_int_id, orig_template_str_id = self._template_id_payload(
                    getattr(value_data, "original_source_template_id", None)
                )
                battle_info = getattr(value_data, "value", None)
                payload: dict[str, object | None] = {
                    "seq_id": seq_id,
                    "client_tick_tms": client_tick_tms,
                    "owner_id": int(getattr(op, "owner_id", 0)) or None,
                    "entity_inst_id": int(getattr(value_data, "entity_inst_id", 0)) or None,
                    "scene_num_id": int(getattr(value_data, "scene_num_id", 0)) or None,
                    "source": int(getattr(value_data, "source", 0)) or None,
                    "hp": float(getattr(battle_info, "hp", 0.0) or 0.0) if battle_info is not None else None,
                    "ultimatesp": float(getattr(battle_info, "ultimatesp", 0.0) or 0.0) if battle_info is not None else None,
                    "delta_value": self._read_float_presence(value_data, "delta_value"),
                    "template_type": template_type,
                    "template_int_id": template_int_id,
                    "orig_template_type": orig_template_type,
                    "orig_template_int_id": orig_template_int_id,
                }
                if template_str_id:
                    payload["template_str_id"] = template_str_id
                if orig_template_str_id:
                    payload["orig_template_str_id"] = orig_template_str_id
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload=payload,
                    )
                )
                continue
            if op_type_name == "BattleOpModifyBattleState":
                battle_state_data = getattr(op, "modify_battle_state_op_data", None)
                if battle_state_data is None:
                    continue
                is_in_battle = bool(getattr(battle_state_data, "is_in_battle", False))
                if self.merge_multi_phase_enemy_battles and self.tracked_enemy_templateid is not None:
                    if is_in_battle and not self.merged_battle_active:
                        self.merged_battle_active = True
                    else:
                        continue
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload={
                            "seq_id": seq_id,
                            "client_tick_tms": client_tick_tms,
                            "is_in_battle": is_in_battle,
                        },
                    )
                )
                if is_in_battle:
                    if self.squad_index:
                        self._emit_scene_info_event(timestamp_ms)
                    self._emit_loadout_event("BATTLE_START", timestamp_ms, force=True)
                continue
            if op_type_name == "BattleOpModifyPoiseValue":
                poise_data = getattr(op, "modify_poise_value_op_data", None)
                if poise_data is None:
                    continue
                template_type, template_int_id, template_str_id = self._template_id_payload(
                    getattr(poise_data, "template_id", None)
                )
                orig_template_type, orig_template_int_id, orig_template_str_id = self._template_id_payload(
                    getattr(poise_data, "original_source_template_id", None)
                )
                payload = {
                    "seq_id": seq_id,
                    "client_tick_tms": client_tick_tms,
                    "owner_id": int(getattr(op, "owner_id", 0)) or None,
                    "modify_type": self._field_enum_name(poise_data, "modify_type"),
                    "owner_type": self._field_enum_name(poise_data, "owner_type"),
                    "value": float(getattr(poise_data, "value", 0.0) or 0.0),
                    "cur_poise_value": float(getattr(poise_data, "cur_poise_value", 0.0) or 0.0),
                    "attacker_inst_id": int(getattr(poise_data, "attacker_inst_id", 0)) or None,
                    "action_id": int(getattr(poise_data, "action_id", 0)) or None,
                    "template_type": template_type,
                    "template_int_id": template_int_id,
                    "orig_template_type": orig_template_type,
                    "orig_template_int_id": orig_template_int_id,
                    "battle_report_info": self._message_to_payload(getattr(poise_data, "battle_report_info", None)),
                }
                if template_str_id:
                    payload["template_str_id"] = template_str_id
                if orig_template_str_id:
                    payload["orig_template_str_id"] = orig_template_str_id
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload=payload,
                    )
                )
                continue

            if op_type_name == "BattleOpUpdateAtbInfo":
                # 技力(atb)同步：主控角色的重击(连招末段)回技力 → reason=AddValue 的正 delta，
                # 归因到该角色。用于排轴区分主控重击 vs 非主控 AI 重击。
                atb_op = getattr(op, "update_atb_info_op_data", None)
                if atb_op is None:
                    continue
                atb_data = getattr(atb_op, "atb_data", None)
                template_type, template_int_id, template_str_id = self._template_id_payload(
                    getattr(atb_op, "template_id", None)
                )
                orig_template_type, orig_template_int_id, orig_template_str_id = self._template_id_payload(
                    getattr(atb_op, "original_source_template_id", None)
                )
                payload = {
                    "seq_id": seq_id,
                    "client_tick_tms": client_tick_tms,
                    "owner_id": int(getattr(op, "owner_id", 0)) or None,
                    "atb_value": float(getattr(atb_data, "atb_value", 0.0) or 0.0) if atb_data is not None else None,
                    "atb_recovery_speed": self._atb_recovery_speed(atb_data),
                    "reason": self._field_enum_name(atb_data, "reason") if atb_data is not None else None,
                    "delta_value": self._read_float_presence(atb_op, "delta_value"),
                    "template_type": template_type,
                    "template_int_id": template_int_id,
                    "orig_template_type": orig_template_type,
                    "orig_template_int_id": orig_template_int_id,
                }
                if template_str_id:
                    payload["template_str_id"] = template_str_id
                if orig_template_str_id:
                    payload["orig_template_str_id"] = orig_template_str_id
                self._emit_event(
                    BattleLogEvent(
                        session_id=self.session_id,
                        timestamp_ms=timestamp_ms,
                        event_type=op_type_name,
                        payload=payload,
                    )
                )
                continue
