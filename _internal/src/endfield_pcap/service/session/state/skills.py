from __future__ import annotations
from typing import Any
from google.protobuf.json_format import MessageToDict
from endfield_pcap.capture.registry import DecodedMessage
from endfield_pcap.models import BattleLogEvent


class SkillStateEvents:
    @staticmethod
    def _read_float_presence(detail: Any, field_name: str) -> float | None:
        try:
            if detail.HasField(field_name):
                return float(getattr(detail, field_name))
        except ValueError:
            value = float(getattr(detail, field_name, 0.0))
            if value != 0.0:
                return value
        return None

    @staticmethod
    def _field_enum_name(message: Any, field_name: str, default: str | None = None) -> str | None:
        try:
            field = type(message).DESCRIPTOR.fields_by_name[field_name]
            return field.enum_type.values_by_number[int(getattr(message, field_name))].name
        except Exception:
            return default

    @classmethod
    def _atb_recovery_speed(cls, data: Any) -> float | None:
        if data is None:
            return None
        value = cls._read_float_presence(data, 'atb_recovery_speed')
        # Proto3 scalars have no presence for their default zero. A speed-change
        # operation makes zero meaningful; on unrelated operations it is absent.
        if value is None and cls._field_enum_name(data, 'reason') == 'ChangeRecoverySpeed':
            return 0.
        return value

    @classmethod
    def _template_id_payload(cls, template_id: Any) -> tuple[str | None, int | None, str | None]:
        if template_id is None:
            return None, None, None
        return (
            cls._field_enum_name(template_id, "type"),
            int(getattr(template_id, "int_id", 0)) or None,
            str(getattr(template_id, "str_id", "")) or None,
        )

    @classmethod
    def _battle_skill_int_ids(cls, battle_mgr_info: Any) -> list[int]:
        if battle_mgr_info is None:
            return []
        out: set[int] = set()
        for skill in getattr(battle_mgr_info, "skill_list", []):
            _, template_int_id, _ = cls._template_id_payload(getattr(skill, "skill_id", None))
            if template_int_id is not None:
                out.add(template_int_id)
        return sorted(out)

    @staticmethod
    def _blackboard_values(blackboard: Any) -> dict[str, object]:
        values = getattr(blackboard, "blackboard", None)
        if values is None:
            return {}
        out: dict[str, object] = {}
        for key, value in dict(values).items():
            str_value = str(getattr(value, "str_value", "") or "")
            is_dynamic = bool(getattr(value, "is_dynamic", False))
            if str_value or is_dynamic:
                out[str(key)] = str_value
                continue
            out[str(key)] = float(getattr(value, "float_value", 0.0) or 0.0)
        return out

    @staticmethod
    def _format_blackboard_values(values: dict[str, object]) -> str:
        parts: list[str] = []
        for key in sorted(values):
            value = values[key]
            if isinstance(value, float):
                parts.append(f"{key}={value:.12g}")
            else:
                parts.append(f"{key}={value}")
        return ",".join(parts)

    @classmethod
    def _weapon_source_skills(cls, battle_mgr_info: Any) -> list[dict[str, object]]:
        if battle_mgr_info is None:
            return []
        out: list[dict[str, object]] = []
        for skill in getattr(battle_mgr_info, "skill_list", []):
            if cls._field_enum_name(skill, "source") != "Weapon":
                continue
            _, template_int_id, template_str_id = cls._template_id_payload(getattr(skill, "skill_id", None))
            blackboard = cls._blackboard_values(getattr(skill, "blackboard", None))
            out.append(
                {
                    "skill_int_id": template_int_id or 0,
                    "skill_str_id": template_str_id or "",
                    "inst_id": int(getattr(skill, "inst_id", 0) or 0),
                    "potential_lv": int(getattr(skill, "potential_lv", 0) or 0),
                    "level": int(getattr(skill, "level", 0) or 0),
                    "blackboard": blackboard,
                }
            )
        return out

    def _owner_meta_payload(self, owner_inst_id: int | None) -> dict[str, object | None]:
        member = self.squad_index.get(owner_inst_id or 0) if owner_inst_id is not None else None
        entity = self.entity_index.get(owner_inst_id or 0) if owner_inst_id is not None else None
        templateid = None
        obj_id = None
        display_name = None
        squad_index = None
        if member is not None:
            templateid = member.templateid
            obj_id = member.obj_id
            display_name = member.display_name or self._resolve_display_name(member.templateid)
            squad_index = member.squad_index
        elif entity is not None:
            templateid = entity.templateid
            obj_id = entity.obj_id
            display_name = self._resolve_display_name(entity.templateid)
        return {
            "owner_inst_id": owner_inst_id,
            "owner_obj_id": obj_id,
            "owner_templateid": templateid,
            "owner_display_name": display_name,
            "owner_squad_index": squad_index,
        }

    def _server_skill_row(self, owner_inst_id: int, skill: Any) -> dict[str, object | None]:
        template_type, template_int_id, template_str_id = self._template_id_payload(getattr(skill, "skill_id", None))
        row: dict[str, object | None] = {
            "owner_inst_id": owner_inst_id,
            "skill_inst_id": int(getattr(skill, "inst_id", 0)) or None,
            "template_type": template_type,
            "template_int_id": template_int_id,
            "level": int(getattr(skill, "level", 0)) or None,
            "potential_lv": int(getattr(skill, "potential_lv", 0)) or None,
            "source": self._field_enum_name(skill, "source"),
            "is_server_init": bool(getattr(skill, "is_server_init", False)),
            "is_enable": bool(getattr(skill, "is_enable", False)),
            "is_passive": bool(getattr(skill, "is_passive", False)),
        }
        if template_str_id:
            row["template_str_id"] = template_str_id
        talent_node_ids = [str(node_id) for node_id in getattr(skill, "talent_node_ids", []) if str(node_id)]
        if talent_node_ids:
            row["talent_node_ids"] = talent_node_ids
        return row

    def _cache_server_skill_rows(self, owner_inst_id: int, skill_rows: list[dict[str, object | None]]) -> None:
        owner_state = self.server_skill_state_by_owner_inst.setdefault(owner_inst_id, {})
        for row in skill_rows:
            skill_inst_id = row.get("skill_inst_id")
            if skill_inst_id is None:
                continue
            skill_inst_id_int = int(skill_inst_id)
            owner_state[skill_inst_id_int] = dict(row)
            self.server_skill_owner_by_skill_inst[skill_inst_id_int] = owner_inst_id

    def _replace_server_skill_rows(self, owner_inst_id: int, skill_rows: list[dict[str, object | None]]) -> None:
        previous = self.server_skill_state_by_owner_inst.pop(owner_inst_id, {})
        for skill_inst_id in previous:
            self.server_skill_owner_by_skill_inst.pop(skill_inst_id, None)
        self._cache_server_skill_rows(owner_inst_id, skill_rows)

    def _emit_server_skill_rows_event(
        self,
        event_type: str,
        owner_inst_id: int | None,
        generation: int | None,
        skill_rows: list[dict[str, object | None]],
        timestamp_ms: int,
    ) -> None:
        payload: dict[str, object | None] = self._owner_meta_payload(owner_inst_id)
        payload["generation"] = generation
        payload["skills"] = sorted(
            skill_rows,
            key=lambda row: (
                int(row.get("template_int_id") or 0),
                int(row.get("skill_inst_id") or 0),
            ),
        )
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type=event_type,
                payload=payload,
            )
        )

    def _update_server_skill_state(self, event_type: str, message: Any, timestamp_ms: int) -> None:
        owner_inst_id = int(getattr(message, "inst_id", 0)) or None
        if owner_inst_id is None:
            return
        skill_rows = [self._server_skill_row(owner_inst_id, skill) for skill in getattr(message, "skills", [])]
        self._cache_server_skill_rows(owner_inst_id, skill_rows)
        self._emit_server_skill_rows_event(
            event_type=event_type,
            owner_inst_id=owner_inst_id,
            generation=int(getattr(message, "generation", 0)) or None,
            skill_rows=skill_rows,
            timestamp_ms=timestamp_ms,
        )

    def _detach_server_skill_state(self, message: Any, timestamp_ms: int) -> None:
        owner_inst_id = int(getattr(message, "inst_id", 0)) or None
        generation = int(getattr(message, "generation", 0)) or None
        deleted_skill_inst_ids = [int(inst_id) for inst_id in getattr(message, "del_inst_ids", []) if int(inst_id)]
        removed_rows: list[dict[str, object | None]] = []
        if owner_inst_id is not None:
            owner_state = self.server_skill_state_by_owner_inst.get(owner_inst_id, {})
            for skill_inst_id in deleted_skill_inst_ids:
                removed = owner_state.pop(skill_inst_id, None)
                self.server_skill_owner_by_skill_inst.pop(skill_inst_id, None)
                if removed is not None:
                    removed_rows.append(removed)
            if not owner_state:
                self.server_skill_state_by_owner_inst.pop(owner_inst_id, None)
        payload: dict[str, object | None] = self._owner_meta_payload(owner_inst_id)
        payload["generation"] = generation
        payload["del_skill_inst_ids"] = deleted_skill_inst_ids
        payload["removed_skills"] = removed_rows
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="SC_DETACH_SERVER_SKILL",
                payload=payload,
            )
        )

    @staticmethod
    def _message_to_payload(message: Any, *, include_implicit_defaults: bool = False) -> dict[str, object]:
        if message is None:
            return {}
        return MessageToDict(
            message,
            preserving_proto_field_name=True,
            use_integers_for_enums=False,
            always_print_fields_with_no_presence=include_implicit_defaults,
        )

    def _emit_contract_tags_event(self, decoded: DecodedMessage, timestamp_ms: int) -> None:
        message = decoded.message
        dungeon_id = str(getattr(message, "dungeon_id", "") or "").strip()
        tag_ids = [int(tag_id) for tag_id in getattr(message, "tag_ids", []) if int(tag_id) > 0]
        display_tag_ids = [
            int(tag_id)
            for tag_id in getattr(message, "display_tag_ids", [])
            if int(tag_id) > 0
        ]
        if not tag_ids and display_tag_ids:
            tag_ids = list(display_tag_ids)
        score = int(getattr(message, "score", 0) or 0) or None
        if not dungeon_id and not tag_ids:
            return
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="CONTRACT_TAGS",
                payload={
                    "dungeon_id": dungeon_id or None,
                    "tag_ids": tag_ids,
                    "display_tag_ids": display_tag_ids,
                    "score": score,
                    "source": decoded.class_name,
                    "direction": decoded.direction,
                    "msg_id": decoded.msg_id,
                },
            )
        )
