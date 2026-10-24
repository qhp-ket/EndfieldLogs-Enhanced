from __future__ import annotations
from typing import Any
from endfield_pcap.models import BattleLogEvent


class ActionEvents:
    def _emit_trigger_action_event(
        self,
        op: Any,
        seq_id: int | None,
        client_tick_tms: int | None,
        timestamp_ms: int,
    ) -> None:
        trigger_data = getattr(op, "trigger_action_op_data", None)
        if trigger_data is None:
            return
        action = getattr(trigger_data, "action", None)
        if action is None:
            return
        template_type, template_int_id, template_str_id = self._template_id_payload(getattr(trigger_data, "template_id", None))
        payload: dict[str, object | None] = {
            "seq_id": seq_id,
            "client_tick_tms": client_tick_tms,
            "owner_id": int(getattr(trigger_data, "owner_id", 0) or getattr(op, "owner_id", 0)) or None,
            # Preserve the distinct protocol identities before the legacy
            # display owner fallback. uint64 values must survive JSON readers.
            "operation_owner_id": str(op.owner_id) if hasattr(op, "owner_id") else None,
            "trigger_owner_id": str(trigger_data.owner_id) if hasattr(trigger_data, "owner_id") else None,
            "trigger_inst_id": str(trigger_data.inst_id) if hasattr(trigger_data, "inst_id") else None,
            "generation": int(op.generation) if hasattr(op, "generation") else None,
            "owner_type": str(getattr(trigger_data, "owner_type", "")) or None,
            "inst_id": int(getattr(trigger_data, "inst_id", 0)) or None,
            # This is outside BATTLE_ACTION_INST. CreateBuff also emits an
            # End-phase payload containing the instances it finishes.
            "trigger_type": int(trigger_data.trigger_type) if hasattr(trigger_data, "trigger_type") else None,
            "template_type": template_type,
            "template_int_id": template_int_id,
            # Proto3 action/unit index zero is a defined value. The default
            # JSON serializer omits it, which is indistinguishable from an
            # incomplete hand-written event once the message is discarded.
            # Emit non-presence scalar defaults here, at the typed boundary.
            # Absent message/oneof fields remain absent.
            "action": self._message_to_payload(action, include_implicit_defaults=True),
            "action_serialization": "protobuf_json_implicit_defaults_v1",
        }
        template_id = getattr(trigger_data, "template_id", None)
        if template_id is not None and hasattr(template_id, "WhichOneof"):
            payload["template_id"] = self._message_to_payload(template_id, include_implicit_defaults=True)
            payload["template_id_case"] = template_id.WhichOneof("id_impl")
        if hasattr(action, "WhichOneof"):
            payload["action_runtime_case"] = action.WhichOneof("inst_impl")
        if hasattr(op, "WhichOneof"):
            payload["operation_payload_case"] = op.WhichOneof("op_data_impl")
        damage_detail_presence = self._damage_detail_presence_payload(action)
        if damage_detail_presence:
            payload["damage_detail_presence"] = damage_detail_presence
        if template_str_id:
            payload["template_str_id"] = template_str_id
        if (template_type or "").lower() == "skill":
            payload["level"] = self._skill_level_for_trigger(
                op,
                trigger_data,
                template_type,
                template_int_id,
                template_str_id,
                action,
            )
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="BattleOpTriggerAction",
                payload=payload,
            )
        )

    @classmethod
    def _damage_detail_presence_payload(cls, action: Any) -> list[dict[str, object]] | None:
        damage_action = getattr(action, "damage_action", None)
        if damage_action is None:
            return None
        details = getattr(damage_action, "details", None)
        if details is None:
            return None
        rows: list[dict[str, object]] = []
        for index, detail in enumerate(details):
            processor_debug_args = getattr(detail, "processor_debug_args", None)
            modifier_args = getattr(detail, "modifier_args", None)
            attacker_modifiers = list(getattr(modifier_args, "attacker_modifiers", [])) if modifier_args is not None else []
            defender_modifiers = list(getattr(modifier_args, "defender_modifiers", [])) if modifier_args is not None else []
            row = {
                "detail_index": index,
                "has_battle_report_info": cls._has_message_field(detail, "battle_report_info"),
                "has_calculation_check_args": cls._has_message_field(detail, "calculation_check_args"),
                "has_calculate_damage_check_args": cls._has_message_field(detail, "calculate_damage_check_args"),
                "processor_debug_args_count": len(processor_debug_args) if processor_debug_args is not None else 0,
                "has_attacker_attr_modifier_debug_data": cls._has_message_field(detail, "attacker_attr_modifier_debug_data"),
                "has_defender_attr_modifier_debug_data": cls._has_message_field(detail, "defender_attr_modifier_debug_data"),
                "attacker_modifier_count": len(attacker_modifiers),
                "defender_modifier_count": len(defender_modifiers),
                "attacker_modifier_debug_handle_count": cls._modifier_debug_handle_count(attacker_modifiers),
                "defender_modifier_debug_handle_count": cls._modifier_debug_handle_count(defender_modifiers),
                "attacker_modifier_debug_arg_entry_count": cls._modifier_debug_arg_entry_count(attacker_modifiers),
                "defender_modifier_debug_arg_entry_count": cls._modifier_debug_arg_entry_count(defender_modifiers),
            }
            rows.append(row)
        return rows

    @staticmethod
    def _has_message_field(message: Any, field_name: str) -> bool:
        try:
            return bool(message.HasField(field_name))
        except Exception:
            return False

    @staticmethod
    def _modifier_debug_handle_count(handles: list[Any]) -> int:
        count = 0
        for handle in handles:
            try:
                processor_debug_args = getattr(handle, "processor_debug_args", None)
                if processor_debug_args is not None and len(processor_debug_args) > 0:
                    count += 1
            except Exception:
                continue
        return count

    @staticmethod
    def _modifier_debug_arg_entry_count(handles: list[Any]) -> int:
        total = 0
        for handle in handles:
            try:
                processor_debug_args = getattr(handle, "processor_debug_args", None)
                if processor_debug_args is not None:
                    total += len(processor_debug_args)
            except Exception:
                continue
        return total

    def _emit_proto_passthrough_event(
        self,
        event_type: str,
        message: Any,
        timestamp_ms: int,
        extra_payload: dict[str, object] | None = None,
    ) -> None:
        payload = self._message_to_payload(message)
        if extra_payload:
            payload.update(extra_payload)
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type=event_type,
                payload=payload,
            )
        )
