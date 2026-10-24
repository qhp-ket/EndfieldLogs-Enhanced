from __future__ import annotations
import copy
import json
from typing import Any
from endfield_pcap.data.loadout import (
    equip_piece_catalog,
    format_equip_stats,
    format_gem_terms,
    format_weapon_refine_stats,
    infer_weapon_refine_from_source_skills,
    weapon_base_atk,
    weapon_base_atk_bounds,
)
from endfield_pcap.models import BattleLogEvent


class LoadoutEvents:
    def _update_equip_puton(self, message: Any, timestamp_ms: int) -> None:
        char_id = int(getattr(message, "charid", 0) or 0)
        slot_id = int(getattr(message, "slotid", 0) or 0)
        equip_id = int(getattr(message, "equipid", 0) or 0)
        if char_id and char_id in self.char_bag_by_objid:
            char_info = self.char_bag_by_objid[char_id]
            equip_col = dict(char_info.get("equip_col") or {})
            equip_suit = self._str_int_map(getattr(message, "suitinfo", {}))
            previous_equip_id = int(equip_col.get(slot_id, 0) or 0)
            if previous_equip_id and previous_equip_id != equip_id and previous_equip_id in self.equip_by_inst_id:
                self.equip_by_inst_id[previous_equip_id]["equip_char_id"] = 0
            # The explicit new slot replaces this instance's old slot even
            # when the equipment moves within the same character.
            equip_col = {slot: value for slot, value in equip_col.items()
                         if int(value or 0) != equip_id or slot == slot_id}
            equip_col[slot_id] = equip_id
            char_info["equip_col"] = equip_col
            char_info["equip_suit"] = equip_suit
        for other_char_id, other_char_info in self.char_bag_by_objid.items():
            if other_char_id == char_id:
                continue
            other_equip_col = dict(other_char_info.get("equip_col") or {})
            removed_slots = [
                slot
                for slot, current_equip_id in other_equip_col.items()
                if int(current_equip_id or 0) == equip_id
            ]
            if not removed_slots:
                continue
            for slot in removed_slots:
                other_equip_col.pop(slot, None)
            other_char_info["equip_col"] = other_equip_col
        put_off_char_id = int(getattr(message, "put_off_charid", 0) or 0)
        if put_off_char_id and put_off_char_id in self.char_bag_by_objid:
            old_owner = self.char_bag_by_objid[put_off_char_id]
            old_owner_equip_col = dict(old_owner.get("equip_col") or {})
            removed_slots = [
                slot
                for slot, current_equip_id in old_owner_equip_col.items()
                if int(current_equip_id or 0) == equip_id
            ]
            for slot in removed_slots:
                old_owner_equip_col.pop(slot, None)
            old_owner["equip_col"] = old_owner_equip_col
            old_owner["equip_suit"] = self._str_int_map(getattr(message, "old_owner_suitinfo", {}))
        if equip_id and equip_id in self.equip_by_inst_id:
            self.equip_by_inst_id[equip_id]["equip_char_id"] = char_id
        self._emit_loadout_event("SC_EQUIP_PUTON", timestamp_ms)

    def _update_equip_putoff(self, message: Any, timestamp_ms: int) -> None:
        char_id = int(getattr(message, "charid", 0) or 0)
        slot_id = int(getattr(message, "slotid", 0) or 0)
        if char_id and char_id in self.char_bag_by_objid:
            char_info = self.char_bag_by_objid[char_id]
            equip_col = dict(char_info.get("equip_col") or {})
            equip_id = int(equip_col.pop(slot_id, 0) or 0)
            char_info["equip_col"] = equip_col
            char_info["equip_suit"] = self._str_int_map(getattr(message, "suitinfo", {}))
            if equip_id and equip_id in self.equip_by_inst_id:
                self.equip_by_inst_id[equip_id]["equip_char_id"] = 0
        self._emit_loadout_event("SC_EQUIP_PUTOFF", timestamp_ms)

    def _update_equip_enhance(self, message: Any, timestamp_ms: int) -> None:
        equip = getattr(message, "equip_data", None)
        if equip is not None:
            payload = self._equip_payload(equip)
            equip_id = int(payload.get("equipid") or getattr(message, "equip_inst_id", 0) or 0)
            if equip_id:
                previous = self.equip_by_inst_id.get(equip_id, {})
                if previous.get("template_string") and not payload.get("template_string"):
                    payload["template_string"] = previous["template_string"]
                payload["equipid"] = equip_id
                self.equip_by_inst_id[equip_id] = payload
        self._emit_loadout_event("SC_EQUIP_ENHANCE", timestamp_ms)

    @staticmethod
    def _weapon_source_skill_ids(char_info: dict[str, object] | None) -> set[int]:
        if not isinstance(char_info, dict):
            return set()
        result: set[int] = set()
        for item in char_info.get("weapon_source_skills") or []:
            if not isinstance(item, dict):
                continue
            skill_int_id = int(item.get("skill_int_id") or 0)
            if skill_int_id:
                result.add(skill_int_id)
        return result

    @classmethod
    def _replace_weapon_source_skills(
        cls,
        char_info: dict[str, object],
        source_skills: object,
    ) -> None:
        previous_skill_ids = cls._weapon_source_skill_ids(char_info)
        copied_skills = copy.deepcopy(list(source_skills or []))
        destination_potential = int(char_info.get("potential") or 0)
        next_skill_ids: list[int] = []
        for item in copied_skills:
            if not isinstance(item, dict):
                continue
            # BATTLE_MGR_INFO reports the current character potential on every
            # weapon source skill.  The weapon/refine data moves with the
            # weapon, while this owner-specific field must follow the receiver.
            item["potential_lv"] = destination_potential
            skill_int_id = int(item.get("skill_int_id") or 0)
            if skill_int_id and skill_int_id not in next_skill_ids:
                next_skill_ids.append(skill_int_id)

        current_skill_ids = [
            int(skill_int_id)
            for skill_int_id in char_info.get("skill_int_ids") or []
            if int(skill_int_id) and int(skill_int_id) not in previous_skill_ids
        ]
        for skill_int_id in next_skill_ids:
            if skill_int_id not in current_skill_ids:
                current_skill_ids.append(skill_int_id)
        char_info["skill_int_ids"] = current_skill_ids
        char_info["weapon_source_skills"] = copied_skills

    def _update_weapon_puton(self, message: Any, timestamp_ms: int) -> None:
        char_id = int(getattr(message, "charid", 0) or 0)
        weapon_id = int(getattr(message, "weaponid", 0) or 0)
        off_weapon_id = int(getattr(message, "offweaponid", 0) or 0)
        put_off_char_id = int(getattr(message, "put_off_charid", 0) or 0)

        receiver = self.char_bag_by_objid.get(char_id) if char_id else None
        previous_owner = (
            self.char_bag_by_objid.get(put_off_char_id)
            if put_off_char_id and put_off_char_id != char_id
            else None
        )
        receiver_previous_weapon_id = int(receiver.get("weapon_id") or 0) if receiver else 0
        previous_owner_weapon_id = int(previous_owner.get("weapon_id") or 0) if previous_owner else 0
        receiver_source_skills = copy.deepcopy(receiver.get("weapon_source_skills") or []) if receiver else []
        previous_owner_source_skills = (
            copy.deepcopy(previous_owner.get("weapon_source_skills") or []) if previous_owner else []
        )

        if receiver is not None:
            receiver["weapon_id"] = weapon_id
            if weapon_id != receiver_previous_weapon_id:
                if previous_owner is not None and previous_owner_weapon_id == weapon_id:
                    self._replace_weapon_source_skills(receiver, previous_owner_source_skills)
                else:
                    # Equipping from the bag provides no new BATTLE_MGR_INFO.
                    # Never retain the previous weapon's skills under the new
                    # template; a later full character sync will repopulate it.
                    self._replace_weapon_source_skills(receiver, [])

        if previous_owner is not None:
            previous_owner["weapon_id"] = off_weapon_id
            if off_weapon_id and receiver_previous_weapon_id == off_weapon_id:
                self._replace_weapon_source_skills(previous_owner, receiver_source_skills)
            else:
                self._replace_weapon_source_skills(previous_owner, [])

        if weapon_id:
            weapon = self.weapon_by_inst_id.setdefault(weapon_id, {"inst_id": weapon_id})
            weapon["equip_char_id"] = char_id
        if off_weapon_id:
            off_weapon = self.weapon_by_inst_id.setdefault(off_weapon_id, {"inst_id": off_weapon_id})
            off_weapon["equip_char_id"] = put_off_char_id if previous_owner is not None else 0
        self._emit_loadout_event("SC_WEAPON_PUTON", timestamp_ms)

    def _update_weapon_delta(self, class_name: str, message: Any, timestamp_ms: int) -> None:
        weapon_id = int(getattr(message, "weaponid", 0) or 0)
        if weapon_id:
            weapon = self.weapon_by_inst_id.setdefault(weapon_id, {"inst_id": weapon_id})
            if class_name in {"SC_WEAPON_ATTACH_GEM", "SC_WEAPON_DETACH_GEM"}:
                # Source skill totals from before the gem change cannot be
                # combined with the new gem. Await an explicit skill refresh.
                for char_info in self.char_bag_by_objid.values():
                    if int(char_info.get("weapon_id") or 0) == weapon_id:
                        self._replace_weapon_source_skills(char_info, [])
            if class_name == "SC_WEAPON_ADD_EXP":
                weapon["exp"] = int(getattr(message, "new_exp", 0) or 0)
                weapon["weapon_lv"] = int(getattr(message, "weapon_lv", 0) or 0)
            elif class_name == "SC_WEAPON_BREAKTHROUGH":
                weapon["breakthrough_lv"] = int(getattr(message, "breakthrough_lv", 0) or 0)
            elif class_name == "SC_WEAPON_REFINE_UPGRADE":
                weapon["refine_lv"] = int(getattr(message, "refine_lv", 0) or 0)
            elif class_name == "SC_WEAPON_ATTACH_GEM":
                gem_id = int(getattr(message, "gemid", 0) or 0)
                weapon["attach_gem_id"] = gem_id
                gem = self.gem_by_inst_id.get(gem_id)
                if gem:
                    gem["weapon_id"] = weapon_id
                    self.gem_by_weapon_id[weapon_id] = gem
            elif class_name == "SC_WEAPON_DETACH_GEM":
                gem_id = int(getattr(message, "detach_gemid", 0) or weapon.get("attach_gem_id") or 0)
                weapon["attach_gem_id"] = 0
                self.gem_by_weapon_id.pop(weapon_id, None)
                if gem_id and gem_id in self.gem_by_inst_id:
                    self.gem_by_inst_id[gem_id]["weapon_id"] = 0
        self._emit_loadout_event(class_name, timestamp_ms)

    @staticmethod
    def _format_enhance_map(values: dict[int, int]) -> str:
        if not values:
            return ""
        return ",".join(f"{key}:{values[key]}" for key in sorted(values))

    @staticmethod
    def _format_int_map(values: dict[Any, Any]) -> str:
        if not values:
            return "{}"
        parts = []
        for key in sorted(values, key=lambda item: str(item)):
            parts.append(f"[{key}]={values[key]}")
        return "{" + " ".join(parts) + "}"

    @staticmethod
    def _format_int_list(values: Any) -> str:
        out: list[int] = []
        for value in values or []:
            try:
                out.append(int(value))
            except (TypeError, ValueError):
                continue
        return ",".join(str(value) for value in sorted(set(out)))

    @staticmethod
    def _equip_slot_candidates(template: str) -> list[int]:
        return list(equip_piece_catalog().get(template, {}).get('valid_slots') or [])

    @classmethod
    def _infer_equip_slot(cls, template: str, used_slots: set[int]) -> int | None:
        candidates = cls._equip_slot_candidates(template)
        return candidates[0] if len(candidates) == 1 and candidates[0] not in used_slots else None

    @classmethod
    def _format_loadout_equip(cls, equip: dict[str, object], equip_id: int) -> str:
        template = str(equip.get("template_string") or equip.get("templateid") or equip_id)
        enhance = equip.get("enhance") if isinstance(equip.get("enhance"), dict) else {}
        enhance_text = cls._format_enhance_map({int(k): int(v) for k, v in dict(enhance).items()})
        stat_text = format_equip_stats(template, enhance if isinstance(enhance, dict) else {})
        equip_text = f"{template}|lv={enhance_text}" if enhance_text else template
        return f"{equip_text}|stats={stat_text}" if stat_text else equip_text

    def _loadout_char_ids(self) -> list[int]:
        current_ids = [char_id for char_id in self.current_team_char_ids if char_id in self.char_bag_by_objid]
        scene_ids = [char_id for char_id in self.scene_team_char_ids if char_id in self.char_bag_by_objid]
        dungeon_team = getattr(self, "dungeon_team_char_ids", None)
        dungeon_ids = [
            char_id
            for char_id in (dungeon_team or [])
            if char_id in self.char_bag_by_objid
        ]
        if scene_ids:
            if dungeon_ids and set(dungeon_ids) == set(scene_ids):
                return dungeon_ids
            if current_ids and set(current_ids) == set(scene_ids):
                return current_ids
            return scene_ids
        if dungeon_team is not None:
            return dungeon_ids
        return current_ids

    @classmethod
    def _format_weapon_source_skills(cls, values: Any) -> str:
        parts: list[str] = []
        for item in values or []:
            if not isinstance(item, dict):
                continue
            skill_int_id = int(item.get("skill_int_id") or 0)
            level = int(item.get("level") or 0)
            potential_lv = int(item.get("potential_lv") or 0)
            blackboard = item.get("blackboard") if isinstance(item.get("blackboard"), dict) else {}
            bb_text = cls._format_blackboard_values(blackboard)
            parts.append(f"{skill_int_id}:level={level}:potentialLv={potential_lv}:bb={{{bb_text}}}")
        return ";".join(parts)

    def _loadout_rows(self) -> list[dict[str, object]]:
        char_ids = self._loadout_char_ids()
        if not char_ids:
            return []
        rows: list[dict[str, object]] = []
        for slot, char_id in enumerate(char_ids):
            char_info = self.char_bag_by_objid.get(char_id)
            if not char_info:
                continue
            weapon_id = int(char_info.get("weapon_id") or 0)
            weapon = self.weapon_by_inst_id.get(weapon_id, {})
            equip_col = {int(k): int(v) for k, v in dict(char_info.get("equip_col") or {}).items()}
            equips: dict[int, str] = {}
            equip_inst_ids: dict[int, int] = {}
            used_slots: set[int] = set()
            used_equip_ids: set[int] = set()
            for equip_slot, equip_id in sorted(equip_col.items()):
                equip = self.equip_by_inst_id.get(equip_id, {})
                if not equip_id or equip_id in used_equip_ids:
                    continue
                equips[equip_slot] = self._format_loadout_equip(equip, equip_id)
                equip_inst_ids[equip_slot] = equip_id
                used_slots.add(equip_slot)
                used_equip_ids.add(equip_id)
            equipped_items = [
                (equip_id, equip)
                for equip_id, equip in self.equip_by_inst_id.items()
                if char_info.get('equipment_snapshot_complete') is not True
                and int(equip.get("equip_char_id") or 0) == char_id and int(equip_id) not in used_equip_ids
            ]
            for equip_id, equip in sorted(equipped_items, key=lambda item: str(item[1].get("template_string") or item[0])):
                template = str(equip.get("template_string") or equip.get("templateid") or equip_id)
                equip_slot = self._infer_equip_slot(template, used_slots)
                if equip_slot is None:
                    continue
                equips[equip_slot] = self._format_loadout_equip(equip, int(equip_id))
                equip_inst_ids[equip_slot] = int(equip_id)
                used_slots.add(equip_slot)
                used_equip_ids.add(int(equip_id))
            attached_gem_id = int(weapon.get("attach_gem_id") or 0)
            attached_gem = self.gem_by_inst_id.get(attached_gem_id) if attached_gem_id else None
            if attached_gem is None and weapon_id:
                attached_gem = self.gem_by_weapon_id.get(weapon_id)
                if attached_gem:
                    attached_gem_id = int(attached_gem.get("gem_id") or attached_gem.get("inst_id") or 0)
            weapon_lv = int(weapon.get("weapon_lv") or 0)
            weapon_template = str(weapon.get("template_string") or weapon.get("template_id") or weapon_id or "unknown_weapon")
            base_atk_bounds = weapon_base_atk_bounds(weapon_template)
            weapon_sync_source = str(weapon.get("sync_source") or "missing")
            raw_weapon_source_skills = char_info.get("weapon_source_skills")
            refine = int(weapon.get("refine_lv") or 0)
            if weapon_sync_source in {"template_only", "missing"}:
                refine = None
            inferred_refine = (
                infer_weapon_refine_from_source_skills(weapon_template, raw_weapon_source_skills,
                    gem_terms=attached_gem.get("terms") if attached_gem
                    and attached_gem_id > 0 and int(attached_gem.get("weapon_id") or 0) == weapon_id else None)
                if weapon_sync_source == "template_only"
                else None
            )
            if inferred_refine is not None:
                refine = inferred_refine
                weapon_sync_source = f"{weapon_sync_source}+source_skill_refine"
            weapon_source_skills = self._format_weapon_source_skills(raw_weapon_source_skills)
            weapon_refine_stats = weapon_source_skills or (
                format_weapon_refine_stats(weapon_template, refine) if refine is not None else ""
            )
            weapon_refine_stats_source = "server_weapon_skill" if weapon_source_skills else "weapon_data_refine"
            rows.append(
                {
                    "slot": slot,
                    "char": str(char_info.get("templateid") or ""),
                    "char_inst_id": char_id,
                    "char_level": int(char_info.get("level") or 0),
                    "potential": int(char_info.get("potential") or 0),
                    "weapon_inst_id": weapon_id,
                    "weapon_template": weapon_template,
                    "weapon_sync_source": weapon_sync_source,
                    "weapon_lv": weapon_lv,
                    "refine": refine,
                    "breakthrough": int(weapon.get("breakthrough_lv") or 0),
                    "weapon_base_atk": weapon_base_atk(weapon_template, weapon_lv),
                    "weapon_base_atk_lv1": base_atk_bounds.get("lv1"),
                    "weapon_base_atk_max": base_atk_bounds.get("max"),
                    "weapon_refine_stats": weapon_refine_stats,
                    "weapon_refine_stats_source": weapon_refine_stats_source,
                    "attached_gem": attached_gem_id,
                    "gem_weapon_id": int(attached_gem.get("weapon_id") or 0) if attached_gem else 0,
                    "gem_template": int(attached_gem.get("template_id") or 0) if attached_gem else 0,
                    "gem_terms": format_gem_terms(attached_gem),
                    "equip_inst_ids": self._format_int_map(equip_inst_ids),
                    "equips": self._format_int_map(equips),
                    "equipment_snapshot_complete": char_info.get('equipment_snapshot_complete') is True,
                    "unresolved_equip_inst_ids": sorted(int(equip_id) for equip_id, _ in equipped_items
                                                         if int(equip_id) not in used_equip_ids),
                    "equip_suit": self._format_int_map(dict(char_info.get("equip_suit") or {})),
                    "skill_int_ids": self._format_int_list(char_info.get("skill_int_ids")),
                    "weapon_source_skills": weapon_source_skills,
                }
            )
        return rows

    def _emit_loadout_event(self, reason: str, timestamp_ms: int, *, force: bool = False) -> None:
        rows = self._loadout_rows()
        if not rows:
            return
        signature = json.dumps(rows, ensure_ascii=False, sort_keys=True)
        if not force and signature == self._last_loadout_signature:
            return
        self._last_loadout_signature = signature
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="LOADOUT",
                payload={"reason": reason, "rows": rows},
            )
        )
