from __future__ import annotations
from typing import Any
from endfield_pcap.trace.formatting import (
    _UNKNOWN_ENEMY_KEY,
    _intish,
    _load_dungeon_enemy_hints,
    _parse_equip_suit_counts,
    _entity_attr_tokens,
)


class ActorEvents:
    def _handle_scene_info_skills(self, event: dict[str, Any], ts_ms: int) -> None:
        # SC_SELF_SCENE_INFO_SKILLS 携带每个角色的技能清单（skill_inst_id → template id）。
        # 施放包（SkillStartCast）只带 inst id，没有这份映射时零伤害技能（辅助大招等）
        # 在日志里只能落成 chr_xxx_skill_100849 这种运行时兜底名，下游无法归类。
        owner_template = str(event.get("owner_templateid") or "")
        owner_hint = self._character_from_template(owner_template) or ""
        skill_level_tokens: list[str] = []
        for skill in event.get("skills") or []:
            if not isinstance(skill, dict):
                continue
            skill_inst_id = _intish(skill.get("skill_inst_id"))
            if not skill_inst_id:
                continue
            resolved = self.skill_id_by_inst.get(skill_inst_id)
            if resolved is None:
                resolved = self._resolve_skill_template(
                    skill.get("template_str_id"),
                    skill.get("template_int_id"),
                    owner_hint=owner_hint,
                )
                if resolved:
                    self.skill_id_by_inst[skill_inst_id] = resolved
            skill_source = str(skill.get("skill_source") or "")
            if skill_source and skill_inst_id not in self.skill_source_by_inst:
                self.skill_source_by_inst[skill_inst_id] = skill_source
            # 技能等级落盘（供 parser v33 导出排轴 API 消费）：解析出真名用真名，
            # 否则用 int id 兜底，level 缺失的条目跳过。
            level = skill.get("level")
            if level is None:
                continue
            token_id = resolved or (
                str(skill.get("template_int_id")) if skill.get("template_int_id") is not None else ""
            )
            if token_id:
                skill_level_tokens.append(f"{token_id}:{level}")
        if owner_template and skill_level_tokens:
            signature = (owner_template, tuple(skill_level_tokens))
            if signature not in self._char_skills_emitted:
                self._char_skills_emitted.add(signature)
                self._line(
                    ts_ms,
                    (
                        f"CHAR_SKILLS owner={owner_template} "
                        f"ownerId={_intish(event.get('owner_inst_id')) or 'unknown'} "
                        f"count={len(skill_level_tokens)} skills=[{' '.join(skill_level_tokens)}]"
                    ),
                )

    def _handle_scene_info(self, event: dict[str, Any], ts_ms: int) -> None:
        members = []
        for item in event.get("char_list") or []:
            if not isinstance(item, dict):
                continue
            battle_id = _intish(item.get("battle_inst_id"))
            obj_id = _intish(item.get("id"))
            template = str(item.get("templateid") or "")
            if battle_id and template:
                self.id_to_name[battle_id] = template
            if obj_id and template:
                self.id_to_name[obj_id] = template
                members.append(f"{template}_{battle_id}")
                self.actor_alias_by_raw_id[obj_id] = template
            if battle_id and template:
                self.actor_alias_by_raw_id[battle_id] = template
                attrs = _entity_attr_tokens(item.get("attrs"))
                if attrs or item.get("level") is not None or item.get("hp") is not None:
                    self._line(
                        ts_ms,
                        (
                            f"ENTITY_STATS id={battle_id} template={template} kind=character "
                            f"level={item.get('level') if item.get('level') is not None else 'unknown'} "
                            f"hp={item.get('hp') if item.get('hp') is not None else 'unknown'} "
                            f"attrs=[{' '.join(attrs)}]"
                        ),
                    )
        if members:
            self._has_scene_squad = True
            self._line(ts_ms, f"SQUAD size={len(members)} members=[{' '.join(members)}]")

    def _handle_loadout(self, event: dict[str, Any], ts_ms: int) -> None:
        rows = event.get("rows")
        if not isinstance(rows, list) or not rows:
            return
        members = [
            f"{row.get('char')}_{row.get('char_inst_id')}"
            for row in rows
            if isinstance(row, dict) and row.get("char") and row.get("char_inst_id")
        ]
        if members and not self._has_scene_squad:
            self._line(ts_ms, f"SQUAD size={len(members)} members=[{' '.join(members)}]")
        self._refresh_loadout_skill_owners(rows)
        reason = str(event.get("reason") or "packet")
        if reason == "SC_SELF_SCENE_INFO":
            self.loadout_actor_order = [
                str(row.get("char") or "")
                for row in rows
                if isinstance(row, dict) and row.get("char")
            ]
            self._next_loadout_actor_index = 0
        else:
            self.loadout_actor_order = []
            self._next_loadout_actor_index = 0
        roster = [
            str(row.get("char_inst_id") or "")
            for row in rows
            if isinstance(row, dict) and row.get("char_inst_id")
        ]
        self._line(ts_ms, f"LOADOUT reason={reason} slotCount={len(rows)} memberCount={len(rows)} roster=[{' '.join(roster)}]")
        for row in rows:
            if not isinstance(row, dict):
                continue
            slot = int(_intish(row.get("slot")) or 0)
            char = str(row.get("char") or "")
            char_inst_id = int(_intish(row.get("char_inst_id")) or 0)
            char_level = int(_intish(row.get("char_level")) or 0)
            if char and char_inst_id and self.id_to_name.get(char_inst_id) is None:
                self.id_to_name[char_inst_id] = char
            if char and char_inst_id:
                self.actor_alias_by_raw_id[char_inst_id] = char
            potential = int(_intish(row.get("potential")) or 0)
            weapon_inst_id = int(_intish(row.get("weapon_inst_id")) or 0)
            weapon_template = str(row.get("weapon_template") or "unknown_weapon")
            weapon_sync_source = str(row.get("weapon_sync_source") or "missing")
            weapon_lv = int(_intish(row.get("weapon_lv")) or 0)
            refine = _intish(row.get("refine"))
            breakthrough = int(_intish(row.get("breakthrough")) or 0)
            weapon_base_atk = row.get("weapon_base_atk")
            weapon_base_atk_lv1 = row.get("weapon_base_atk_lv1")
            weapon_base_atk_max = row.get("weapon_base_atk_max")
            weapon_refine_stats = str(row.get("weapon_refine_stats") or "")
            weapon_refine_stats_source = str(row.get("weapon_refine_stats_source") or "unknown")
            attached_gem = int(_intish(row.get("attached_gem")) or 0)
            gem_weapon_id = int(_intish(row.get("gem_weapon_id")) or 0)
            gem_template = int(_intish(row.get("gem_template")) or 0)
            gem_terms = str(row.get("gem_terms") or "")
            weapon_source_skills = str(row.get("weapon_source_skills") or "")
            equip_inst_ids = str(row.get("equip_inst_ids") or "{}")
            equips = str(row.get("equips") or "{}")
            equip_complete = (f'equipsComplete={int(row["equipment_snapshot_complete"])} '
                              if type(row.get('equipment_snapshot_complete')) is bool else '')
            unplaced_equips = ('unplacedEquipInstIds=[' + ','.join(str(value) for value in row['unresolved_equip_inst_ids']) + '] '
                               if isinstance(row.get('unresolved_equip_inst_ids'), list) else '')
            equip_suit = str(row.get("equip_suit") or "{}")
            skill_int_ids = str(row.get("skill_int_ids") or "")
            self._line(
                ts_ms,
                (
                    f"LOADOUT slot={slot} char={char} slotCharInstId={char_inst_id} "
                    f"resolvedCharInstId={char_inst_id} character=packet charInfo.instId={char_inst_id} "
                    f"template={char} charLv={char_level} potential={potential} weaponInstId={weapon_inst_id} "
                    f"weaponTemplate={weapon_template} weaponLv={weapon_lv} refine={refine if refine is not None else 'unknown'} break={breakthrough} "
                    f"attachedGem={attached_gem} equipInsts={equip_inst_ids} equips={equips} "
                    f"{equip_complete}"
                    f"{unplaced_equips}"
                    f"equipSuit={equip_suit} skillIntIds=[{skill_int_ids}]"
                ),
            )
            self._line(
                ts_ms,
                (
                    f"LOADOUT_STATS slot={slot} char={char} weaponInstId={weapon_inst_id} "
                    f"weaponTemplate={weapon_template} weaponSync={weapon_sync_source} "
                    f"weaponBaseAtk={weapon_base_atk if weapon_base_atk is not None else 'unknown'} "
                    f"weaponBaseAtkLv1={weapon_base_atk_lv1 if weapon_base_atk_lv1 is not None else 'unknown'} "
                    f"weaponBaseAtkMax={weapon_base_atk_max if weapon_base_atk_max is not None else 'unknown'} "
                    f"weaponRefineStatsSource={weapon_refine_stats_source} "
                    f"weaponRefineStats={{{weapon_refine_stats}}} "
                    f"weaponSourceSkills={{{weapon_source_skills}}} "
                    f"gemInstId={attached_gem} gemWeaponId={gem_weapon_id} gemTemplate={gem_template} "
                    f"gemTerms={{{gem_terms}}}"
                ),
            )

    def _refresh_loadout_skill_owners(self, rows: list[Any]) -> None:
        owners_by_skill: dict[int, set[str]] = {}
        active_suits_by_char: dict[str, set[str]] = {}
        active_weapons_by_char: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            char = str(row.get("char") or "")
            if not char:
                continue
            weapon_template = str(row.get("weapon_template") or "")
            if weapon_template:
                active_weapons_by_char[char] = weapon_template
            active_suits_by_char[char] = _parse_equip_suit_counts(row.get("equip_suit"))
            for skill_int_id in self._parse_skill_int_ids(row.get("skill_int_ids")):
                owners_by_skill.setdefault(skill_int_id, set()).add(char)
        if not owners_by_skill:
            self.active_suits_by_char = active_suits_by_char
            self.active_weapons_by_char = active_weapons_by_char
            return
        self.skill_owner_by_int = {
            skill_int_id: next(iter(owners))
            for skill_int_id, owners in owners_by_skill.items()
            if len(owners) == 1
        }
        self.active_suits_by_char = active_suits_by_char
        self.active_weapons_by_char = active_weapons_by_char

    @staticmethod
    def _parse_skill_int_ids(value: Any) -> list[int]:
        if isinstance(value, (list, tuple, set)):
            result = []
            for item in value:
                number = _intish(item)
                if number is not None:
                    result.append(number)
            return result
        if not isinstance(value, str):
            return []
        text = value.strip().strip("[]")
        if not text:
            return []
        result = []
        for part in text.replace(";", ",").replace(" ", ",").split(","):
            number = _intish(part.strip())
            if number is not None:
                result.append(number)
        return result

    def _handle_object_enter(self, event: dict[str, Any], ts_ms: int) -> None:
        for item in event.get("objects") or []:
            if not isinstance(item, dict):
                continue
            battle_id = _intish(item.get("battle_inst_id"))
            obj_id = _intish(item.get("obj_id"))
            template = str(item.get("templateid") or "")
            if battle_id and template:
                self.id_to_name[battle_id] = template
            if obj_id and template:
                self.id_to_name[obj_id] = template
            attrs = _entity_attr_tokens(item.get("attrs"))
            if battle_id and template and (attrs or item.get("level") is not None or item.get("hp") is not None):
                kind = str(item.get("kind") or "object")
                self._line(
                    ts_ms,
                    (
                        f"ENTITY_STATS id={battle_id} template={template} kind={kind} "
                        f"level={item.get('level') if item.get('level') is not None else 'unknown'} "
                        f"hp={item.get('hp') if item.get('hp') is not None else 'unknown'} "
                        f"attrs=[{' '.join(attrs)}]"
                    ),
                )

    def _handle_sync_attr(self, event: dict[str, Any], ts_ms: int) -> None:
        battle_id = _intish(event.get("battle_inst_id"))
        obj_id = _intish(event.get("obj_id"))
        entity_id = battle_id or obj_id
        if not entity_id:
            return
        template = str(event.get("templateid") or "")
        if not template:
            template = self.id_to_name.get(entity_id) or (self.id_to_name.get(obj_id) if obj_id else "") or "unknown"
        if battle_id and template and template != "unknown":
            self.id_to_name[battle_id] = template
            self.actor_alias_by_raw_id[battle_id] = template
        if obj_id and template and template != "unknown":
            self.id_to_name[obj_id] = template
        attrs = _entity_attr_tokens(event.get("attrs"))
        if not attrs:
            return
        self._line(
            ts_ms,
            (
                f"ENTITY_ATTR_UPDATE id={entity_id} "
                f"obj={obj_id if obj_id is not None else 'unknown'} "
                f"template={template} attrs=[{' '.join(attrs)}]"
            ),
        )

    def _name_for_id(self, value: Any) -> str:
        battle_id = _intish(value)
        if not battle_id:
            return "?"
        existing = self.id_to_name.get(battle_id)
        if existing and existing != _UNKNOWN_ENEMY_KEY:
            return existing
        alias = self.actor_alias_by_raw_id.get(battle_id)
        if alias:
            return alias
        if existing:
            return existing
        return f"id_{battle_id}"

    def _actor_alias_by_id(self, battle_id: int | None) -> str:
        if not battle_id:
            return "?"
        existing = self.id_to_name.get(battle_id)
        if existing and existing != _UNKNOWN_ENEMY_KEY:
            return existing
        alias = self.actor_alias_by_raw_id.get(battle_id)
        if alias:
            return alias
        if existing:
            return existing
        return f"id_{battle_id}"

    def _name_for_event_id(self, battle_id: int | None) -> str:
        return self._name_for_id(battle_id)

    def _infer_actor_from_mapping(self, buff_num_id: int | None) -> str:
        return ""

    def _remember_actor_alias_for_buff(self, src_id: int | None, target_id: int | None, buff_num_id: int | None, buff_id: str) -> None:
        # Buff names and nearby actor IDs do not prove entity identity.
        return

    def _set_enemy_hint_from_dungeon_id(
        self,
        dungeon_id: str,
        source: str,
        *,
        clear_on_missing: bool = False,
    ) -> None:
        if not dungeon_id:
            return
        enemy_key = _load_dungeon_enemy_hints().get(dungeon_id)
        if enemy_key:
            self._set_enemy_hint(enemy_key, source)
        elif clear_on_missing:
            self._current_enemy_hint = ""
            self._current_enemy_hint_source = ""

    def _set_enemy_hint(self, enemy_key: str, source: str) -> None:
        if not enemy_key or enemy_key == _UNKNOWN_ENEMY_KEY:
            return
        priority = {"buff": 1, "game_mechanics": 2, "dungeon_context": 2}.get(source, 1)
        current_priority = {"buff": 1, "game_mechanics": 2, "dungeon_context": 2}.get(
            self._current_enemy_hint_source,
            0,
        )
        if self._current_enemy_hint and priority < current_priority:
            return
        self._current_enemy_hint = enemy_key
        self._current_enemy_hint_source = source
        self._upgrade_single_unknown_enemy_alias(enemy_key, source=source)

    def _enemy_hint_can_accept_buff_alias(self, enemy_key: str) -> bool:
        if not self._current_enemy_hint:
            return True
        if self._current_enemy_hint == enemy_key:
            return True
        return self._current_enemy_hint_source == "buff"

    def _upgrade_single_unknown_enemy_alias(self, enemy_key: str, *, source: str) -> None:
        return

    def _record_identity_inference(self, raw_id: int, enemy_key: str, *, source: str) -> None:
        if self._last_ts_ms is None:
            return
        self._line(
            self._last_ts_ms,
            f"IDENTITY_INFERENCE actorId={raw_id} template={enemy_key} source={source}",
        )

    def _maybe_map_next_loadout_actor(self, actor_id: int, ts_ms: int, *, source: str) -> None:
        return

    def _name_for_damage_target(self, value: Any, attacker_name: str) -> str:
        battle_id = _intish(value)
        if battle_id is None:
            return "?"
        return self.id_to_name.get(battle_id) or self.actor_alias_by_raw_id.get(battle_id) or f"id_{battle_id}"
