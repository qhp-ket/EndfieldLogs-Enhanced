from __future__ import annotations
import json
import math
import re
from typing import Any
from endfield_pcap.trace.formatting import _intish, _floatish, _trace_string


class SkillEvents:
    def _handle_skill_attach(self, event: dict[str, Any], ts_ms: int) -> None:
        skill_inst_id = _intish(event.get("skill_inst_id"))
        src_inst_id = _intish(event.get("src_inst_id"))
        src_template = self.id_to_name.get(src_inst_id) if src_inst_id else None
        skill_template = self._resolve_skill_template(
            event.get("template_str_id"),
            event.get("template_int_id"),
            owner_hint=self._character_from_template(src_template) or "",
        )
        char_template = self._character_from_template(skill_template)
        if not char_template and src_inst_id:
            char_template = self._character_from_template(src_template)
            if char_template and skill_template and skill_template.startswith("skill_"):
                skill_template = f"{char_template}_{skill_template}"
        if skill_inst_id and skill_template:
            self.skill_id_by_inst[skill_inst_id] = skill_template
        skill_source = str(event.get("skill_source") or "")
        if skill_inst_id and skill_source:
            self.skill_source_by_inst[skill_inst_id] = skill_source
        if src_inst_id and char_template:
            if self.id_to_name.get(src_inst_id) is None:
                self.id_to_name[src_inst_id] = char_template
                self._line(ts_ms, f"ACTOR_MAP id={src_inst_id} template={char_template} source=skill_attach skill={skill_template}")

    def _handle_skill_detach(self, event: dict[str, Any]) -> None:
        skill_inst_id = _intish(event.get("skill_inst_id"))
        if skill_inst_id:
            self.skill_id_by_inst.pop(skill_inst_id, None)
            self.skill_source_by_inst.pop(skill_inst_id, None)

    def _handle_skill_start_cast(self, event: dict[str, Any], ts_ms: int) -> None:
        skill_inst_id = _intish(event.get("skill_inst_id"))
        if not skill_inst_id:
            return
        skill = self.skill_id_by_inst.get(skill_inst_id)
        owner_id = _intish(event.get("owner_id"))
        owner = self._name_for_id(owner_id)
        if not skill:
            skill = self._resolve_skill_template(None, skill_inst_id, owner_hint=self._character_from_template(owner) or "")
        char_template = self._character_from_template(skill) or self._character_from_template(owner)
        if owner_id and char_template and self.id_to_name.get(owner_id) is None:
            self.id_to_name[owner_id] = char_template
            owner = char_template
        seq = _intish(event.get("seq_id")) or 0
        client_tick = _intish(event.get("client_tick_tms")) or 0
        self._line(
            ts_ms,
            (
                f"SKILL_CAST_START seq={seq} startMs={client_tick} inst={skill_inst_id} "
                f"owner={owner} ownerId={owner_id if owner_id is not None else 'unknown'} "
                f"skill={skill or 'unknown_skill'} "
                f"skillSource={self.skill_source_by_inst.get(skill_inst_id) or 'unknown'} captureMs={ts_ms}"
            ),
        )

    def _handle_skill_end_cast(self, event: dict[str, Any], ts_ms: int) -> None:
        skill_inst_id = _intish(event.get("skill_inst_id"))
        if not skill_inst_id:
            return
        owner = self._name_for_id(event.get("owner_id"))
        skill = self.skill_id_by_inst.get(skill_inst_id) or self._resolve_skill_template(
            None,
            skill_inst_id,
            owner_hint=self._character_from_template(owner) or "",
        )
        seq = _intish(event.get("seq_id")) or 0
        client_tick = _intish(event.get("client_tick_tms")) or 0
        self._line(
            ts_ms,
            (
                f"SKILL_CAST_END seq={seq} endMs={client_tick} inst={skill_inst_id} "
                f"owner={owner} ownerId={event.get('owner_id') if event.get('owner_id') is not None else 'unknown'} "
                f"skill={skill or 'unknown_skill'} "
                f"skillSource={self.skill_source_by_inst.get(skill_inst_id) or 'unknown'}"
            ),
        )

    def _handle_trigger_action(self, event: dict[str, Any], ts_ms: int) -> None:
        action = event.get("action")
        if not isinstance(action, dict):
            return
        action_type = str(action.get("action_type") or "")
        if action_type in {"BattleActionModifyDynamicBlackboard", "BattleActionRefreshBuffAttrModifierValue",
                           "BattleActionReadSkillActionToBb"}:
            template = event.get("template_id")
            template = template if isinstance(template, dict) else {}
            template_cases = [key for key in ("int_id", "str_id") if key in template]
            template_case = template_cases[0] if len(template_cases) == 1 else None
            identity = {
                "schemaVersion": 1, "sessionId": event.get("session_id"),
                "operationSeq": event.get("seq_id"),
                "operationOwnerId": event.get("operation_owner_id"),
                "ownerType": event.get("owner_type"),
                "ownerId": event.get("trigger_owner_id"),
                "environmentInstId": event.get("trigger_inst_id"),
                "generation": event.get("generation"),
                "clientTickMs": (str(event["client_tick_tms"])
                                 if event.get("client_tick_tms") is not None else None),
                "templateType": template.get("type"), "templateIdCase": template_case,
                "templateIntId": template.get("int_id"), "templateStrId": template.get("str_id"),
                "actionId": action.get("action_id"), "triggerType": event.get("trigger_type"),
                "actionType": {"BattleActionModifyDynamicBlackboard": 7,
                               "BattleActionRefreshBuffAttrModifierValue": 31,
                               "BattleActionReadSkillActionToBb": 35}[action_type],
                "actionRuntimeCase": event.get("action_runtime_case"),
                "operationPayloadCase": event.get("operation_payload_case"),
            }
            # Older decoded NDJSON preserved these fields but not the later
            # envelope. Keep original names without inventing missing metadata.
            if all(event.get(key) is None for key in ('operation_owner_id', 'trigger_owner_id', 'trigger_inst_id', 'generation', 'template_id')):
                identity['eventContext'] = {key: event[key] for key in (
                    'owner_id', 'inst_id', 'owner_type', 'template_type',
                    'template_int_id', 'template_str_id', 'seq_id') if key in event}
            for field in ("operationOwnerId", "ownerId", "environmentInstId"):
                value = identity[field]
                if type(value) in (int, str):
                    identity[field] = str(value)
            if action_type == "BattleActionReadSkillActionToBb":
                # Preserve the packet's computed values and all detail rows.
                # The matching typed action defines their meaning (e.g. combo
                # layers/rate); this event alone does not authorize rDPS.
                runtime_field = "read_skill_setting_to_bb_action"
                runtime = action.get(runtime_field)
                errors = []
                if ({key for key in action if key.endswith("_action")} != {runtime_field}
                        or not isinstance(runtime, dict)
                        or not isinstance(runtime.get("runtime_details"), list)):
                    errors.append("invalid_skill_setting_runtime")
                if event.get("action_runtime_case") != runtime_field:
                    errors.append("skill_setting_runtime_presence_unverified")
                if event.get("operation_payload_case") != "trigger_action_op_data":
                    errors.append("trigger_operation_presence_unverified")
                if template_case is None or event.get("template_id_case") != template_case:
                    errors.append("invalid_template_oneof")
                identity["runtime"] = runtime
                identity["actionSerialization"] = event.get("action_serialization")
                identity["buffUid"] = (identity["environmentInstId"]
                    if type(identity["ownerType"]) in (int, str) and str(identity["ownerType"]) == "1"
                    and template.get("type") == "Buff"
                    and identity["environmentInstId"] not in (None, "0") else None)
                if errors:
                    identity["validationErrors"] = errors
                self._line(ts_ms, ("BB_READ_SKILL_SETTING_UNRESOLVED " if errors else "BB_READ_SKILL_SETTING ")
                           + json.dumps(identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                return
            if action_type == "BattleActionRefreshBuffAttrModifierValue":
                errors = []
                runtime_field = "refresh_buff_attr_modifier_value_action"
                runtime_fields = {key for key in action if key.endswith("_action")}
                if runtime_fields != {runtime_field} or action.get(runtime_field) != {}:
                    errors.append("invalid_refresh_runtime_oneof")
                if event.get("action_runtime_case") != runtime_field:
                    errors.append("refresh_runtime_presence_unverified")
                if event.get("operation_payload_case") != "trigger_action_op_data":
                    errors.append("trigger_operation_presence_unverified")
                if template_case is None or event.get("template_id_case") != template_case:
                    errors.append("invalid_template_oneof")
                if template_case == "int_id" and type(template.get("int_id")) is not int:
                    errors.append("invalid_template_int_id")
                if template_case == "str_id" and not isinstance(template.get("str_id"), str):
                    errors.append("invalid_template_str_id")
                if type(identity["ownerType"]) not in (int, str) or str(identity["ownerType"]) not in {"0", "1", "2", "3"}:
                    errors.append("invalid_ownerType")
                for field in ("operationOwnerId", "ownerId", "environmentInstId"):
                    value = identity[field]
                    if (not isinstance(value, str) or not value.isascii() or not value.isdecimal()
                            or not 0 <= int(value) < 2**64):
                        errors.append("invalid_" + field)
                for field in ("operationSeq", "generation", "actionId", "triggerType"):
                    if type(identity[field]) is not int:
                        errors.append("invalid_" + field)
                tick = event.get("client_tick_tms")
                if (type(tick) not in (int, str)
                        or not re.fullmatch(r"-?[0-9]+", str(tick))
                        or not -(2**63) <= int(tick) < 2**63):
                    errors.append("invalid_clientTickMs")
                if not isinstance(identity["sessionId"], str) or not identity["sessionId"]:
                    errors.append("missing_sessionId")
                # A skill or standalone environment can report this action too;
                # its environment ID must never be relabeled as a Buff UID.
                identity["buffUid"] = (identity["environmentInstId"]
                    if type(identity["ownerType"]) in (int, str) and str(identity["ownerType"]) == "1"
                    and template.get("type") == "Buff"
                    and identity["environmentInstId"] not in (None, "0") else None)
                if errors:
                    identity["validationErrors"] = errors
                self._line(ts_ms, ("BUFF_ATTR_REFRESH_UNRESOLVED " if errors else "BUFF_ATTR_REFRESH ")
                           + json.dumps(identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                return
        if action_type == "BattleActionModifyDynamicBlackboard":
            runtime_field = "modify_dynamic_blackboard_action"
            if ({key for key in action if key.endswith("_action")} != {runtime_field}
                    or event.get("action_runtime_case") not in (None, runtime_field)):
                return
            inst_id = _intish(event.get("inst_id"))
            action_id = int(_intish(action.get("action_id")) or 0)
            modify_action = action.get("modify_dynamic_blackboard_action")
            if inst_id and isinstance(modify_action, dict):
                raw_value = modify_action.get("client_value")
                value = None
                if type(raw_value) in (int, float):
                    try:
                        value = float(raw_value)
                    except (OverflowError, ValueError):
                        pass
                if value is not None and math.isfinite(value):
                    rows = self.recent_dynamic_bb_by_inst.setdefault(inst_id, [])
                    rows.append((action_id, value))
                    del rows[:-8]
                    self._write_blackboard_trace(
                        ts_ms,
                        "BB_MODIFY_DYNAMIC",
                        event,
                        action_id,
                        f"value={value!r} identity=" + json.dumps(
                            identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
                    )
        if action_type == "BattleActionSimpleCalcBb":
            inst_id = _intish(event.get("inst_id"))
            action_id = int(_intish(action.get("action_id")) or 0)
            calc_action = action.get("simple_calc_bb_action")
            if inst_id and isinstance(calc_action, dict):
                target_key = str(calc_action.get("client_target_key") or "")
                final_value = _floatish(calc_action.get("client_final_value"))
                if target_key and final_value is not None:
                    rows = self.recent_calc_bb_by_inst.setdefault(inst_id, [])
                    rows.append((action_id, target_key, final_value))
                    del rows[:-12]
                    value_a = _floatish(calc_action.get("client_value_a"))
                    value_b = _floatish(calc_action.get("client_value_b"))
                    parts = [
                        f"key={target_key}",
                        f"final={final_value!r}",
                    ]
                    if value_a is not None:
                        parts.append(f"valueA={value_a!r}")
                    if value_b is not None:
                        parts.append(f"valueB={value_b!r}")
                    self._write_blackboard_trace(
                        ts_ms,
                        "BB_SIMPLE_CALC",
                        event,
                        action_id,
                        " ".join(parts),
                    )
        if action_type == "BattleActionMultiModifyBb" or "multi_modify_bb_action" in action:
            action_id = int(_intish(action.get("action_id")) or 0)
            modify_action = action.get("multi_modify_bb_action")
            if isinstance(modify_action, dict):
                key = str(modify_action.get("key") or "")
                value = _floatish(modify_action.get("value"))
                if key or value is not None:
                    parts = []
                    if key:
                        parts.append(f"key={key}")
                    if value is not None:
                        parts.append(f"value={value:.6g}")
                    self._write_blackboard_trace(
                        ts_ms,
                        "BB_MULTI_MODIFY",
                        event,
                        action_id,
                        " ".join(parts),
                    )
        if action_type == "BattleActionSetBlackboardFromPreset" or "set_blackboard_from_preset_action" in action:
            action_id = int(_intish(action.get("action_id")) or 0)
            preset_action = action.get("set_blackboard_from_preset_action")
            if isinstance(preset_action, dict):
                modified_value = preset_action.get("modified_value")
                if modified_value:
                    self._write_blackboard_trace(
                        ts_ms,
                        "BB_SET_PRESET",
                        event,
                        action_id,
                        f"modifiedValue={_trace_string(modified_value)}",
                    )
        if action_type == "BattleActionLaunchProjectile" or "launch_projectile_action" in action:
            self._handle_launch_projectile(ts_ms, event, action.get("launch_projectile_action") or {})
        if action_type == "BattleActionSpawnAbilityEntity" or "spawn_ability_entity_action" in action:
            self._handle_spawn_ability_entity(ts_ms, event, action.get("spawn_ability_entity_action") or {})
        if action_type == "BattleActionDamage" or "damage_action" in action:
            self._write_damage(ts_ms, event, action.get("damage_action") or {})
        if action_type == "BattleActionFinishBuff" or "finish_buff_action" in action:
            self._write_finish_buffs(ts_ms, action.get("finish_buff_action") or {})

    def _trigger_skill_template(self, event: dict[str, Any], owner_name: str = "") -> str:
        skill = str(event.get("template_str_id") or "")
        if skill:
            return skill
        number = _intish(event.get("template_int_id"))
        if number is None:
            return "unknown_skill"
        namespace = str(event.get("template_type") or "").lower()
        if namespace == "buff":
            return self.resolver.resolve_buff(int_id=number)
        if namespace == "skill":
            return self.resolver.resolve_skill(int_id=number) or f"skill_{number}"
        return f"skill_{number}"

    def _write_blackboard_trace(
        self,
        ts_ms: int,
        label: str,
        event: dict[str, Any],
        action_id: int,
        extra: str,
    ) -> None:
        inst_id = _intish(event.get("inst_id"))
        owner_id = _intish(event.get("owner_id"))
        owner = self._name_for_id(owner_id)
        skill = self._trigger_skill_template(event, owner)
        seq = _intish(event.get("seq_id")) or 0
        client_tick = _intish(event.get("client_tick_tms")) or 0
        self._line(
            ts_ms,
            (
                f"{label} seq={seq} tick={client_tick} inst={inst_id if inst_id is not None else 'unknown'} "
                f"ownerId={owner_id if owner_id is not None else 'unknown'} owner={owner} "
                f"packetSessionId={event.get('session_id') or 'unknown'} "
                f"skill={skill} actionId={action_id} {extra}"
            ),
        )

    def _handle_spawn_ability_entity(self, ts_ms: int, event: dict[str, Any], spawn_action: Any) -> None:
        if not isinstance(spawn_action, dict):
            return
        owner_id = _intish(event.get("owner_id"))
        owner = self._name_for_id(owner_id)
        skill = self._trigger_skill_template(event, owner)
        action_payload = event.get("action") if isinstance(event.get("action"), dict) else {}
        action_id = int(_intish(action_payload.get("action_id")) or 0)
        seq = _intish(event.get("seq_id")) or 0
        client_tick = _intish(event.get("client_tick_tms")) or 0
        inst_id = _intish(event.get("inst_id"))
        template_int_id = _intish(event.get("template_int_id"))
        details = spawn_action.get("details") or []
        if not isinstance(details, list):
            return
        for detail in details:
            if not isinstance(detail, dict):
                continue
            entity_id = _intish(detail.get("client_ability_entity_id"))
            source_id = _intish(detail.get("source_id")) or owner_id
            source = self._name_for_id(source_id)
            pos = detail.get("init_pos") if isinstance(detail.get("init_pos"), dict) else {}
            rot = detail.get("rotation") if isinstance(detail.get("rotation"), dict) else {}
            pos_text = ",".join(
                str(_floatish(pos.get(axis)) if _floatish(pos.get(axis)) is not None else "unknown")
                for axis in ("x", "y", "z")
            )
            rot_text = ",".join(
                str(_floatish(rot.get(axis)) if _floatish(rot.get(axis)) is not None else "unknown")
                for axis in ("x", "y", "z")
            )
            self._line(
                ts_ms,
                (
                    f"ABILITY_ENTITY_SPAWN seq={seq} tick={client_tick} actionId={action_id} "
                    f"inst={inst_id if inst_id is not None else 'unknown'} skill={skill} "
                    f"templateIntId={template_int_id if template_int_id is not None else 'unknown'} "
                    f"ownerId={owner_id if owner_id is not None else 'unknown'} owner={owner} "
                    f"sourceId={source_id if source_id is not None else 'unknown'} source={source} "
                    f"entityId={entity_id if entity_id is not None else 'unknown'} "
                    f"pos={pos_text} rot={rot_text}"
                ),
            )

    def _handle_launch_projectile(self, ts_ms: int, event: dict[str, Any], launch_action: Any) -> None:
        if not isinstance(launch_action, dict):
            return
        source_id = _intish(launch_action.get("source_id")) or _intish(event.get("owner_id"))
        source_name = self.id_to_name.get(source_id) if source_id else ""
        skill = self._resolve_skill_template(
            event.get("template_str_id"),
            event.get("template_int_id"),
            owner_hint=self._character_from_template(source_name) or "",
        )
        char_template = self._character_from_template(skill)
        if not char_template and source_id:
            char_template = self._character_from_template(source_name)
        if not char_template:
            return
        if source_id and self.id_to_name.get(source_id) is None:
            self.id_to_name[source_id] = char_template
            self._line(ts_ms, f"ACTOR_MAP id={source_id} template={char_template} source=launch_source skill={skill}")
        for detail in launch_action.get("details") or []:
            if not isinstance(detail, dict):
                continue
            projectile_id = (
                _intish(detail.get("client_projectile_id"))
                or _intish(detail.get("projectile_id"))
                or _intish(detail.get("inst_id"))
            )
            trigger_skill = self._trigger_skill_template(event, self._name_for_id(_intish(event.get('owner_id'))))
            if (projectile_id and trigger_skill == 'buff_chr_0036_jsspsi_xianjing_inkhurteffect'
                    and (event.get('action') or {}).get('action_id') == 14):
                self._line(ts_ms, 'INK_RELEASE ' + json.dumps({
                    'schema_version': 1, 'template_key': trigger_skill, 'action_id': 14,
                    'session_id': event.get('session_id'), 'operation_seq': event.get('seq_id'),
                    'client_tick_ms': event.get('client_tick_tms'),
                    'buff_uid': str(event.get('inst_id')), 'owner_id': str(event.get('owner_id')),
                    'source_actor_id': str(source_id), 'projectile_id': str(projectile_id),
                }, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
            if projectile_id and self.id_to_name.get(projectile_id) is None:
                self.id_to_name[projectile_id] = char_template
                self._line(ts_ms, f"ACTOR_MAP id={projectile_id} template={char_template} source=launch_projectile skill={skill}")
