from __future__ import annotations
from typing import Any
from endfield_pcap.capture.registry import DecodedMessage
from endfield_pcap.models import BattleLogEvent
from endfield_pcap.service.session.helpers import _CONTRACT_TAG_CLASS_NAMES


class MessageDispatch:
    def _handle_message(self, decoded: DecodedMessage, timestamp_ms: int) -> None:
        self.decoded_class_counts[decoded.class_name] += 1
        if self.on_debug_message is not None:
            self.on_debug_message(decoded, timestamp_ms)
        if decoded.class_name in {
            "CS_PING", "SC_PING", "CS_GAME_TIME_FREEZE_START_REQ", "CS_GAME_TIME_FREEZE_END_REQ",
            "SC_GAME_TIME_FREEZE_START_RSP", "SC_GAME_TIME_FREEZE_END_RSP",
        }:
            # Preserve proto3 false/zero defaults: an explicit response with
            # in_time_freeze=false must survive as a state transition.
            payload = self._message_to_payload(decoded.message, include_implicit_defaults=True)
            self._emit_event(BattleLogEvent(
                session_id=self.session_id, timestamp_ms=timestamp_ms,
                event_type=decoded.class_name,
                payload={**payload, "direction": decoded.direction, "msg_id": decoded.msg_id,
                         "raw_body_hex": decoded.raw_body.hex()},
            ))
            return
        if decoded.class_name == "CS_ENTER_DUNGEON":
            self._emit_proto_passthrough_event(
                decoded.class_name,
                decoded.message,
                timestamp_ms,
                extra_payload={
                    "raw_body_len": len(decoded.raw_body),
                    "raw_body_hex": decoded.raw_body.hex(),
                },
            )
            self._handle_enter_dungeon(decoded.message, timestamp_ms)
            return
        if decoded.class_name in _CONTRACT_TAG_CLASS_NAMES:
            self._emit_contract_tags_event(decoded, timestamp_ms)
            return
        if decoded.class_name == "CS_LEAVE_DUNGEON":
            self._handle_leave_dungeon(timestamp_ms)
            return
        if decoded.class_name == "SC_SYNC_CHAR_BAG_INFO":
            self._update_char_bag_info(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_CHAR_BAG_SET_TEAM":
            self._update_char_team(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_CHAR_BAG_SET_TEAM_LEADER":
            self._emit_loadout_event("SC_CHAR_BAG_SET_TEAM_LEADER", timestamp_ms)
            return
        if decoded.class_name == "SC_ITEM_BAG_SCOPE_SYNC":
            self._update_item_bag_scope_sync(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_ITEM_BAG_SCOPE_MODIFY":
            self._update_item_bag_scope_modify(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_EQUIP_PUTON":
            self._update_equip_puton(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_EQUIP_PUTOFF":
            self._update_equip_putoff(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_EQUIP_ENHANCE":
            self._update_equip_enhance(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_WEAPON_PUTON":
            self._update_weapon_puton(decoded.message, timestamp_ms)
            return
        if decoded.class_name in {
            "SC_WEAPON_ADD_EXP",
            "SC_WEAPON_BREAKTHROUGH",
            "SC_WEAPON_REFINE_UPGRADE",
            "SC_WEAPON_ATTACH_GEM",
            "SC_WEAPON_DETACH_GEM",
        }:
            self._update_weapon_delta(decoded.class_name, decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_SELF_SCENE_INFO":
            self._update_squad_index(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_OBJECT_ENTER_VIEW":
            self._update_entity_index(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_SYNC_ATTR":
            self._sync_entity_attrs(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_OBJECT_LEAVE_VIEW":
            self._remove_entities(decoded.message)
            return
        if decoded.class_name in {"SC_ATTACH_SERVER_SKILL", "SC_UPDATE_SERVER_SKILL"}:
            self._update_server_skill_state(decoded.class_name, decoded.message, timestamp_ms)
            return
        if decoded.class_name == "SC_DETACH_SERVER_SKILL":
            self._detach_server_skill_state(decoded.message, timestamp_ms)
            return
        if decoded.class_name == "CS_BATTLE_OP":
            self._emit_battle_events(decoded.message, timestamp_ms)
            return
        if decoded.class_name in {
            "CS_DEV_CLEAR_BATTLE_INFO",
            "CS_CONDITIONAL_MULTI_STAGE_ACTIVITY_GAIN_REWARD",
            "CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH",
            "CS_GAME_MECHANICS_REQ_START",
            "CS_GAME_MECHANICS_REQ_STOP",
            "CS_SCENE_LOAD_FINISH",
            "CS_SCENE_SET_BATTLE",
            "SC_ACTIVITY_CONDITIONAL_MULTI_STAGE_BASE_CHANGE",
            "SC_ACTIVITY_CONDITIONAL_STAGE_PROGRESS_CHANGE",
            "SC_ACTIVITY_PROGRESS_CHANGE",
            "SC_ADD_SERVER_BUFF",
            "SC_REMOVE_SERVER_BUFF",
            "SC_BATTLE_ADD_GLOBAL_BUFF",
            "SC_BATTLE_DEBUG_INFO",
            "SC_BATTLE_GENERATION_CHANGE",
            "SC_BATTLE_REMOVE_GLOBAL_BUFF",
            "SC_BATTLE_SYNC_GLOBAL_BUFF_INFO",
            "SC_BATTLE_SYNC_SEQ_ID",
            "SC_ENTER_DUNGEON",
            "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE",
            "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE",
            "SC_GAME_MECHANICS_SYNC_CHALLENGE_START",
            "SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD",
            "SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST",
            "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST",
            "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST",
            "SC_CONDITIONAL_MULTI_STAGE_ACTIVITY_GAIN_REWARD",
            "SC_RESET_BATTLE_STATUS",
            "SC_SCENE_SET_BATTLE",
            "SC_SYNC_FULL_DUNGEON_STATUS",
            "SC_SYNC_WEEK_RAID_SETTLEMENT",
        }:
            self._emit_proto_passthrough_event(decoded.class_name, decoded.message, timestamp_ms)

    def _iter_detail_objects(self, detail: Any):
        for field_desc, value in detail.ListFields():
            # protobuf 7 removed the deprecated ``label`` attribute from the
            # upb FieldDescriptor implementation. ``is_repeated`` is the
            # supported API in both protobuf 6 and 7.
            if not bool(field_desc.is_repeated):
                continue
            for item in value:
                common_info = getattr(item, "common_info", None)
                battle_info = getattr(item, "battle_info", None)
                if common_info is None:
                    continue
                yield field_desc.name, item, common_info, battle_info
