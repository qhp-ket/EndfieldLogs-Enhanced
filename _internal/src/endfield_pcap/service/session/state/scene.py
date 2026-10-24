from __future__ import annotations
import logging
from datetime import datetime
from typing import Any
from endfield_pcap.models import BattleLogEvent, EntityInfo, SquadMember
from endfield_pcap.service.session.helpers import _attrs_payload, _proto_has_field, _optional_int


LOGGER = logging.getLogger(__name__)


class SceneEvents:
    def _update_entity_index(self, message: Any, timestamp_ms: int | None = None) -> None:
        detail = getattr(message, "detail", None)
        if detail is None:
            return
        objects: list[dict[str, object | None]] = []
        for detail_kind, detail_obj, common_info, battle_info in self._iter_detail_objects(detail):
            battle_inst_id = int(getattr(battle_info, "battle_inst_id", 0) or 0) if battle_info is not None else 0
            if not battle_inst_id:
                continue
            obj_id = int(getattr(common_info, "id", 0)) or None
            templateid = str(getattr(common_info, "templateid", "")) or None
            info = EntityInfo(
                battle_inst_id=battle_inst_id,
                obj_id=obj_id,
                templateid=templateid,
                entity_type=int(getattr(common_info, "type", 0)) or None,
            )
            self.entity_index[info.battle_inst_id] = info
            if info.obj_id is not None:
                self.obj_to_battle[info.obj_id] = info.battle_inst_id
            objects.append(
                {
                    "kind": str(detail_kind).removesuffix("_list") or "object",
                    "obj_id": obj_id,
                    "battle_inst_id": battle_inst_id,
                    "templateid": templateid,
                    "entity_type": info.entity_type,
                    "level": int(getattr(detail_obj, "level", 0) or 0) or None,
                    "hp": float(getattr(common_info, "hp", 0.0) or 0.0) if common_info is not None else None,
                    "attrs": _attrs_payload(detail_obj),
                }
            )
            if (
                self.merge_multi_phase_enemy_battles
                and self.tracked_enemy_templateid is not None
                and info.templateid == self.tracked_enemy_templateid
            ):
                self.tracked_enemy_inst_ids.add(info.battle_inst_id)
            self._cache_scene_skill_levels(battle_inst_id, battle_info)
        if objects:
            self._emit_event(
                BattleLogEvent(
                    session_id=self.session_id,
                    timestamp_ms=timestamp_ms or int(datetime.now().timestamp() * 1000),
                    event_type="SC_OBJECT_ENTER_VIEW",
                    payload={"objects": objects},
                )
            )

    def _sync_entity_attrs(self, message: Any, timestamp_ms: int) -> None:
        obj_id = int(getattr(message, "obj_id", 0) or 0)
        attrs = _attrs_payload(message)
        if not obj_id or not attrs:
            return
        battle_inst_id = self.obj_to_battle.get(obj_id)
        if battle_inst_id is None and obj_id in self.entity_index:
            battle_inst_id = obj_id
        entity_info = self.entity_index.get(battle_inst_id) if battle_inst_id is not None else None
        member = self.squad_index.get(battle_inst_id) if battle_inst_id is not None else None
        templateid = entity_info.templateid if entity_info is not None else None
        if templateid is None and member is not None:
            templateid = member.templateid
        if member is not None:
            merged = {int(item.get("attr_type", 0) or 0): dict(item) for item in member.attrs}
            for item in attrs:
                attr_type = int(item.get("attr_type", 0) or 0)
                if attr_type:
                    merged[attr_type] = dict(item)
            member.attrs = [merged[key] for key in sorted(merged)]
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="SC_SYNC_ATTR",
                payload={
                    "obj_id": obj_id,
                    "battle_inst_id": battle_inst_id,
                    "templateid": templateid,
                    "attrs": attrs,
                },
            )
        )

    def _handle_enter_dungeon(self, message: Any, timestamp_ms: int) -> None:
        self.scene_team_char_ids = []
        char_team = list(getattr(message, "char_team", []) or [])
        explicit_team_ids = [
            obj_id
            for item in char_team
            if (obj_id := int(getattr(item, "obj_id", 0) or 0))
        ]
        self.dungeon_team_char_ids = explicit_team_ids or None
        dungeon_id = str(getattr(message, "dungeon_id", "") or "").strip()
        if dungeon_id:
            self._emit_dungeon_context(
                timestamp_ms,
                source="CS_ENTER_DUNGEON",
                dungeon_id=dungeon_id,
                char_team_count=len(char_team),
            )
        if not self.merge_multi_phase_enemy_battles:
            return
        templateid = self.multi_phase_dungeon_map.get(dungeon_id)
        if not templateid:
            self.tracked_dungeon_id = None
            self.tracked_enemy_templateid = None
            self.tracked_enemy_inst_ids.clear()
            self.merged_battle_active = False
            return
        self.tracked_dungeon_id = dungeon_id
        self.tracked_enemy_templateid = templateid
        self.tracked_enemy_inst_ids.clear()
        for info in self.entity_index.values():
            if info.templateid == templateid:
                self.tracked_enemy_inst_ids.add(info.battle_inst_id)

    def _scene_dungeon_context_payload(self, message: Any) -> dict[str, object | None] | None:
        if not _proto_has_field(message, "dungeon"):
            return None
        dungeon = getattr(message, "dungeon", None)
        if dungeon is None:
            return None
        dungeon_id = str(getattr(dungeon, "dungeon_id", "") or "").strip()
        if not dungeon_id:
            return None
        scene_id = str(getattr(message, "scene_id", "") or "")
        return {
            "dungeon_id": dungeon_id,
            "source": "SC_SELF_SCENE_INFO",
            "scene_num_id": _optional_int(getattr(message, "scene_num_id", None)),
            "scene_id": scene_id or None,
            "challenge_expire_ts": _optional_int(getattr(dungeon, "challenge_expire_ts", None)),
            "leave_dungeon_ts": _optional_int(getattr(dungeon, "leave_dungeon_ts", None)),
            "is_reward": bool(getattr(dungeon, "is_reward", False)),
            "is_calc": bool(getattr(dungeon, "is_calc", False)),
            "is_pass": bool(getattr(dungeon, "is_pass", False)),
        }

    def _emit_dungeon_context(
        self,
        timestamp_ms: int,
        *,
        source: str,
        dungeon_id: str,
        **extra: object | None,
    ) -> None:
        payload: dict[str, object | None] = {
            "source": source,
            "dungeon_id": dungeon_id,
            **extra,
        }
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="DUNGEON_CONTEXT",
                payload=payload,
            )
        )

    def _handle_leave_dungeon(self, timestamp_ms: int) -> None:
        self.scene_team_char_ids = []
        self.dungeon_team_char_ids = None
        if self.merge_multi_phase_enemy_battles and self.merged_battle_active:
            self._emit_event(
                BattleLogEvent(
                    session_id=self.session_id,
                    timestamp_ms=timestamp_ms,
                    event_type="BattleOpModifyBattleState",
                    payload={
                        "seq_id": None,
                        "client_tick_tms": None,
                        "is_in_battle": False,
                    },
                )
            )
        self.tracked_dungeon_id = None
        self.tracked_enemy_templateid = None
        self.tracked_enemy_inst_ids.clear()
        self.merged_battle_active = False

    def _update_squad_index(self, message: Any, timestamp_ms: int) -> None:
        dungeon_context = self._scene_dungeon_context_payload(message)
        if dungeon_context is not None:
            self._emit_dungeon_context(timestamp_ms, **dungeon_context)
        detail = getattr(message, "detail", None)
        team_info = getattr(message, "team_info", None)
        if detail is None:
            return
        char_list = list(getattr(detail, "char_list", []))
        if not char_list:
            LOGGER.info(
                "ignoring SC_SELF_SCENE_INFO without char_list self_info_reason=%s",
                getattr(message, "self_info_reason", None),
            )
            return
        current_leader_id = int(getattr(team_info, "cur_leader_id", 0)) if team_info is not None else 0
        previous_squad_ids = set(self.squad_index)
        self.squad_index.clear()
        self.skill_levels_by_battle_inst.clear()
        self.global_skill_levels.clear()
        scene_team_char_ids: list[int] = []
        for squad_index, char_info in enumerate(char_list):
            common_info = getattr(char_info, "common_info", None)
            battle_info = getattr(char_info, "battle_info", None)
            if common_info is None or battle_info is None:
                continue
            battle_inst_id = int(getattr(battle_info, "battle_inst_id", 0))
            if not battle_inst_id:
                continue
            obj_id = int(getattr(common_info, "id", 0)) or None
            templateid = self._resolve_scene_templateid(common_info, battle_info)
            display_name = self.name_index.get(templateid or "", templateid)
            member = SquadMember(
                battle_inst_id=battle_inst_id,
                obj_id=obj_id,
                templateid=templateid,
                display_name=display_name,
                is_leader=obj_id == current_leader_id,
                squad_index=squad_index,
                level=int(getattr(char_info, "level", 0) or 0) or None,
                hp=float(getattr(common_info, "hp", 0.0) or 0.0) or None,
                attrs=_attrs_payload(char_info),
            )
            self.squad_index[battle_inst_id] = member
            self.entity_index[battle_inst_id] = EntityInfo(
                battle_inst_id=battle_inst_id,
                obj_id=obj_id,
                templateid=templateid,
                entity_type=int(getattr(common_info, "type", 0)) or None,
            )
            if obj_id is not None:
                self.obj_to_battle[obj_id] = battle_inst_id
                scene_team_char_ids.append(obj_id)
            self._cache_scene_skill_levels(battle_inst_id, battle_info)
            self._replace_server_skill_rows(
                battle_inst_id,
                [self._server_skill_row(battle_inst_id, skill) for skill in getattr(battle_info, "skill_list", [])],
            )
        for owner_inst_id in previous_squad_ids - set(self.squad_index):
            detached = self.server_skill_state_by_owner_inst.pop(owner_inst_id, {})
            for skill_inst_id in detached:
                self.server_skill_owner_by_skill_inst.pop(skill_inst_id, None)
        self.scene_team_char_ids = scene_team_char_ids
        self._emit_scene_info_event(timestamp_ms, dungeon_context=dungeon_context, message=message)
        for member in self.squad_index.values():
            owner_skills = list(self.server_skill_state_by_owner_inst.get(member.battle_inst_id, {}).values())
            if not owner_skills:
                continue
            self._emit_server_skill_rows_event(
                event_type="SC_SELF_SCENE_INFO_SKILLS",
                owner_inst_id=member.battle_inst_id,
                generation=None,
                skill_rows=owner_skills,
                timestamp_ms=timestamp_ms,
            )
        self._emit_loadout_event("SC_SELF_SCENE_INFO", timestamp_ms)

    def _update_char_bag_info(self, message: Any, timestamp_ms: int | None = None) -> None:
        for char_info in getattr(message, "char_info", []):
            templateid = str(getattr(char_info, "templateid", "")) or None
            objid = int(getattr(char_info, "objid", 0) or 0)
            if not templateid:
                continue
            level = int(getattr(char_info, "potential_level", 0) or 0)
            self.char_potential_levels[templateid] = level
            equip_col = {int(key): int(value) for key, value in dict(getattr(char_info, "equip_col", {})).items()}
            equip_suit = {str(key): int(value) for key, value in dict(getattr(char_info, "equip_suit", {})).items()}
            self.char_bag_by_objid[objid] = {
                "objid": objid,
                "templateid": templateid,
                "level": int(getattr(char_info, "level", 0) or 0),
                "potential": level,
                "weapon_id": int(getattr(char_info, "weapon_id", 0) or 0),
                "equip_col": equip_col,
                "equipment_snapshot_complete": hasattr(char_info, 'equip_col'),
                "equip_suit": equip_suit,
                "skill_int_ids": self._battle_skill_int_ids(getattr(char_info, "battle_mgr_info", None)),
                "weapon_source_skills": self._weapon_source_skills(getattr(char_info, "battle_mgr_info", None)),
            }
        LOGGER.info('检测到潜能：%s',self.char_potential_levels)
        team_infos = list(getattr(message, "team_info", []))
        curr_team_index = int(getattr(message, "curr_team_index", 0) or 0)
        if team_infos:
            if 0 <= curr_team_index < len(team_infos):
                team_info = team_infos[curr_team_index]
            else:
                self.current_team_char_ids = []
                if timestamp_ms is not None:
                    self._emit_loadout_event("SC_SYNC_CHAR_BAG_INFO", timestamp_ms)
                return
            self.current_team_char_ids = [
                int(char_id)
                for char_id in getattr(team_info, "char_team", [])
                if int(char_id)
            ]
        if timestamp_ms is not None:
            self._emit_loadout_event("SC_SYNC_CHAR_BAG_INFO", timestamp_ms)

    def _update_char_team(self, message: Any, timestamp_ms: int) -> None:
        self.current_team_char_ids = [
            int(char_id)
            for char_id in getattr(message, "char_team", [])
            if int(char_id)
        ]
        self._emit_loadout_event("SC_CHAR_BAG_SET_TEAM", timestamp_ms)
