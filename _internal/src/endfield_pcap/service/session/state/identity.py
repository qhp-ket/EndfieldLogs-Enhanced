from __future__ import annotations
import logging
from typing import Any
from endfield_pcap.data.loadout import infer_weapon_refine_from_source_skills
from endfield_pcap.models import BattleLogEvent
from endfield_pcap.service.session.helpers import _optional_int


LOGGER = logging.getLogger(__name__)


class IdentityEvents:
    @staticmethod
    def _template_key(template_type: str | None, template_int_id: int | None, template_str_id: str | None) -> str | None:
        if template_str_id:
            prefix = (template_type or "unknown").lower()
            return f"{prefix}:str:{template_str_id}"
        if template_int_id is not None:
            prefix = (template_type or "unknown").lower()
            return f"{prefix}:int:{template_int_id}"
        return None

    def _cache_scene_skill_levels(self, battle_inst_id: int, battle_info: Any) -> None:
        per_battle: dict[str, int] = {}
        for skill in getattr(battle_info, "skill_list", []):
            skill_id = getattr(skill, "skill_id", None)
            template_type, template_int_id, template_str_id = self._template_id_payload(skill_id)
            key = self._template_key(template_type, template_int_id, template_str_id)
            if key is None:
                continue
            level = int(getattr(skill, "level", 1) or 1)
            per_battle[key] = level
            self.global_skill_levels[key] = level
        if per_battle:
            self.skill_levels_by_battle_inst[battle_inst_id] = per_battle
        member = getattr(self, "squad_index", {}).get(battle_inst_id)
        char_info = getattr(self, "char_bag_by_objid", {}).get(member.obj_id) if member and member.obj_id else None
        if char_info and char_info.get("templateid") == member.templateid:
            weapon_id = int(char_info.get("weapon_id") or 0)
            weapon = self.weapon_by_inst_id.get(weapon_id, {})
            weapon_template = str(weapon.get("template_string") or "")
            scene_weapon_skills = self._weapon_source_skills(battle_info)
            gem_id = int(weapon.get("attach_gem_id") or 0)
            gem = getattr(self, "gem_by_inst_id", {}).get(gem_id) if gem_id else None
            if gem is None:
                gem = getattr(self, "gem_by_weapon_id", {}).get(weapon_id)
                gem_id = int(gem.get("gem_id") or gem.get("inst_id") or 0) if gem else 0
            gem_terms = (gem.get("terms") if gem and gem_id > 0
                         and int(gem.get("weapon_id") or 0) == weapon_id else None)
            # A scene refresh contains the new weapon's actual source skills.
            # Bind it through the declared squad owner and equipped instance;
            # another weapon's main skill cannot establish this refinement.
            if (weapon_id
                    and infer_weapon_refine_from_source_skills(weapon_template, char_info.get("weapon_source_skills"), gem_terms=gem_terms) is None
                    and infer_weapon_refine_from_source_skills(weapon_template, scene_weapon_skills, gem_terms=gem_terms) is not None):
                self._replace_weapon_source_skills(char_info, scene_weapon_skills)

    def _remove_entities(self, message: Any) -> None:
        for item in getattr(message, "obj_list", []):
            obj_id = int(getattr(item, "obj_id", 0))
            if not obj_id:
                continue
            battle_inst_id = self.obj_to_battle.pop(obj_id, None)
            if battle_inst_id is not None:
                self.entity_index.pop(battle_inst_id, None)
                self.squad_index.pop(battle_inst_id, None)
                detached = self.server_skill_state_by_owner_inst.pop(battle_inst_id, {})
                for skill_inst_id in detached:
                    self.server_skill_owner_by_skill_inst.pop(skill_inst_id, None)

    def _resolve_display_name(self, templateid: str | None) -> str | None:
        if templateid is None:
            return None
        return self.name_index.get(templateid, templateid)

    @classmethod
    def _extract_endmin_variant(cls, text: str | None) -> str | None:
        if not text:
            return None
        for variant in cls.ENDMIN_VARIANTS:
            if variant in text:
                return variant
        return None

    @classmethod
    def _infer_endmin_variant(cls, battle_info: Any) -> str | None:
        if battle_info is None:
            return None

        for buff in getattr(battle_info, "buff_list", []):
            variant = cls._extract_endmin_variant(str(getattr(buff, "stacking_group_id", "")) or None)
            if variant is not None:
                return variant

        for group in getattr(battle_info, "stacking_group_list", []):
            variant = cls._extract_endmin_variant(str(getattr(group, "stacking_key", "")) or None)
            if variant is not None:
                return variant

        for skill in getattr(battle_info, "skill_list", []):
            for node_id in getattr(skill, "talent_node_ids", []):
                variant = cls._extract_endmin_variant(str(node_id))
                if variant is not None:
                    return variant
            blackboard = getattr(getattr(skill, "blackboard", None), "blackboard", None)
            if blackboard is None:
                continue
            for value in blackboard.values():
                variant = cls._extract_endmin_variant(str(getattr(value, "str_value", "")) or None)
                if variant is not None:
                    return variant

        return None

    def _resolve_scene_templateid(self, common_info: Any, battle_info: Any) -> str | None:
        templateid = str(getattr(common_info, "templateid", "")) or None
        if templateid != "chr_9000_endmin":
            return templateid
        return self._infer_endmin_variant(battle_info) or templateid

    def _emit_scene_info_event(
        self,
        timestamp_ms: int,
        *,
        dungeon_context: dict[str, object | None] | None = None,
        message: Any | None = None,
    ) -> None:
        members = sorted(self.squad_index.values(), key=lambda item: item.squad_index)
        LOGGER.info(
            "squad update members=%s",
            [(member.squad_index, member.display_name, member.battle_inst_id) for member in members],
        )
        payload: dict[str, object | None] = {
            "dungeon": dungeon_context,
            "char_list": [
                {
                    "id": member.obj_id,
                    "templateid": member.templateid,
                    "battle_inst_id": member.battle_inst_id,
                    "display_name": member.display_name or self._resolve_display_name(member.templateid),
                    "potential_level": self._potential_level_for_template(member.templateid),
                    "is_leader": member.is_leader,
                    "squad_index": member.squad_index,
                    "level": member.level,
                    "hp": member.hp,
                    "attrs": member.attrs,
                }
                for member in members
            ],
        }
        if message is not None:
            payload["scene_num_id"] = _optional_int(getattr(message, "scene_num_id", None))
            payload["scene_id"] = str(getattr(message, "scene_id", "") or "") or None
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="SC_SELF_SCENE_INFO",
                payload=payload,
            )
        )

    def _potential_level_for_template(self, templateid: str | None) -> int:
        if templateid is None:
            return 0
        level = self.char_potential_levels.get(templateid)
        if level is not None:
            return level
        if templateid in self.ENDMIN_VARIANTS:
            return self.char_potential_levels.get("chr_9000_endmin", 0)
        return 0

    def _skill_level_for_trigger(
        self,
        op: Any,
        trigger_data: Any,
        template_type: str | None,
        template_int_id: int | None,
        template_str_id: str | None,
        action: Any,
    ) -> int | None:
        key = self._template_key(template_type, template_int_id, template_str_id)
        if key is None:
            return None
        owner_ids: list[int] = []
        damage_action = getattr(action, "damage_action", None)
        attacker_id = int(getattr(damage_action, "attacker_id", 0)) if damage_action is not None else 0
        if attacker_id:
            owner_ids.append(attacker_id)
        trigger_owner = int(getattr(trigger_data, "owner_id", 0) or 0)
        if trigger_owner:
            owner_ids.append(trigger_owner)
        op_owner = int(getattr(op, "owner_id", 0) or 0)
        if op_owner:
            owner_ids.append(op_owner)
        distinct_owner_ids = set(owner_ids)
        if len(distinct_owner_ids) > 1:
            return None
        if not distinct_owner_ids:
            return None
        return self.skill_levels_by_battle_inst.get(owner_ids[0], {}).get(key)
