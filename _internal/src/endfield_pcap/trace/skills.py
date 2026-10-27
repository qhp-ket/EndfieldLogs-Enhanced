from __future__ import annotations
import json
from typing import Any
from endfield_pcap.trace.blackboard import consume_blackboard_action
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
        if consume_blackboard_action(self, event, action, action_type, ts_ms):
            return
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
