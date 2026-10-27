from __future__ import annotations
from typing import Any
from endfield_pcap.trace.formatting import _intish, _floatish
from endfield_pcap.trace.damage_evidence import calculation_tokens, packet_identity_tokens as damage_packet_identity, write_damage_evidence
from endfield_pcap.trace.resources import handle_update_atb_info, handle_modify_poise_value, handle_battle_state


class DamageEvents:
    def _handle_update_atb_info(self, event: dict[str, Any], ts_ms: int) -> None:
        handle_update_atb_info(self, event, ts_ms)

    def _handle_modify_poise_value(self, event: dict[str, Any], ts_ms: int) -> None:
        handle_modify_poise_value(self, event, ts_ms)

    def _handle_battle_state(self, event: dict[str, Any], ts_ms: int) -> None:
        handle_battle_state(self, event, ts_ms)

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
            calc_tokens = calculation_tokens(detail)
            shared = 3 if is_crit else 2
            packet_identity_tokens = damage_packet_identity(event)
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
            write_damage_evidence(self, ts_ms, event, detail, detail_presence)
        if event_inst_id:
            self.recent_dynamic_bb_by_inst.pop(event_inst_id, None)
            self.recent_calc_bb_by_inst.pop(event_inst_id, None)
