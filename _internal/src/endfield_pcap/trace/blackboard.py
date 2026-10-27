"""Blackboard and attribute observations; allocation remains in parser_core."""
from __future__ import annotations
import json
import math
import re
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING
from endfield_pcap.trace.formatting import _intish, _floatish, _trace_string
if TYPE_CHECKING:
    from endfield_pcap.trace.bridge import TraceBridge


@dataclass(slots=True)
class ActionEvidence:
    bridge: TraceBridge
    event: dict[str, Any]
    action: dict[str, Any]
    action_type: str
    ts_ms: int
    identity: dict[str, Any] | None = None
    template: dict[str, Any] | None = None
    template_case: str | None = None


def prepare_dynamic_identity(context: ActionEvidence) -> None:
    event, action, action_type = context.event, context.action, context.action_type
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
    context.identity, context.template, context.template_case = identity, template, template_case


def write_read_skill_setting(context: ActionEvidence) -> None:
    bridge = context.bridge
    event = context.event
    action = context.action
    ts_ms = context.ts_ms
    identity = context.identity
    template = context.template
    template_case = context.template_case
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
    bridge._line(ts_ms, ("BB_READ_SKILL_SETTING_UNRESOLVED " if errors else "BB_READ_SKILL_SETTING ")
               + json.dumps(identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return


def write_attribute_refresh(context: ActionEvidence) -> None:
    bridge = context.bridge
    event = context.event
    action = context.action
    ts_ms = context.ts_ms
    identity = context.identity
    template = context.template
    template_case = context.template_case
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
    bridge._line(ts_ms, ("BUFF_ATTR_REFRESH_UNRESOLVED " if errors else "BUFF_ATTR_REFRESH ")
               + json.dumps(identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return


def write_dynamic_value(context: ActionEvidence) -> bool:
    bridge = context.bridge
    event = context.event
    action = context.action
    ts_ms = context.ts_ms
    identity = context.identity
    runtime_field = "modify_dynamic_blackboard_action"
    if ({key for key in action if key.endswith("_action")} != {runtime_field}
            or event.get("action_runtime_case") not in (None, runtime_field)):
        return True
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
            rows = bridge.recent_dynamic_bb_by_inst.setdefault(inst_id, [])
            rows.append((action_id, value))
            del rows[:-8]
            bridge._write_blackboard_trace(
                ts_ms,
                "BB_MODIFY_DYNAMIC",
                event,
                action_id,
                f"value={value!r} identity=" + json.dumps(
                    identity, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
            )
    return False


def write_simple_calculation(context: ActionEvidence) -> None:
    bridge = context.bridge
    event = context.event
    action = context.action
    ts_ms = context.ts_ms
    inst_id = _intish(event.get("inst_id"))
    action_id = int(_intish(action.get("action_id")) or 0)
    calc_action = action.get("simple_calc_bb_action")
    if inst_id and isinstance(calc_action, dict):
        target_key = str(calc_action.get("client_target_key") or "")
        final_value = _floatish(calc_action.get("client_final_value"))
        if target_key and final_value is not None:
            rows = bridge.recent_calc_bb_by_inst.setdefault(inst_id, [])
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
            bridge._write_blackboard_trace(
                ts_ms,
                "BB_SIMPLE_CALC",
                event,
                action_id,
                " ".join(parts),
            )


def write_multi_modify(context: ActionEvidence) -> None:
    bridge = context.bridge
    event = context.event
    action = context.action
    ts_ms = context.ts_ms
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
            bridge._write_blackboard_trace(
                ts_ms,
                "BB_MULTI_MODIFY",
                event,
                action_id,
                " ".join(parts),
            )


def write_preset(context: ActionEvidence) -> None:
    bridge = context.bridge
    event = context.event
    action = context.action
    ts_ms = context.ts_ms
    action_id = int(_intish(action.get("action_id")) or 0)
    preset_action = action.get("set_blackboard_from_preset_action")
    if isinstance(preset_action, dict):
        modified_value = preset_action.get("modified_value")
        if modified_value:
            bridge._write_blackboard_trace(
                ts_ms,
                "BB_SET_PRESET",
                event,
                action_id,
                f"modifiedValue={_trace_string(modified_value)}",
            )


def consume_blackboard_action(bridge: TraceBridge, event: dict[str, Any], action: dict[str, Any],
                              action_type: str, ts_ms: int) -> bool:
    context = ActionEvidence(bridge, event, action, action_type, ts_ms)
    if action_type in {'BattleActionModifyDynamicBlackboard', 'BattleActionRefreshBuffAttrModifierValue', 'BattleActionReadSkillActionToBb'}:
        prepare_dynamic_identity(context)
        if action_type == "BattleActionReadSkillActionToBb":
            write_read_skill_setting(context)
            return True
        if action_type == "BattleActionRefreshBuffAttrModifierValue":
            write_attribute_refresh(context)
            return True
    if action_type == 'BattleActionModifyDynamicBlackboard':
        if write_dynamic_value(context):
            return True
    if action_type == 'BattleActionSimpleCalcBb':
        write_simple_calculation(context)
    if action_type == 'BattleActionMultiModifyBb' or 'multi_modify_bb_action' in action:
        write_multi_modify(context)
    if action_type == 'BattleActionSetBlackboardFromPreset' or 'set_blackboard_from_preset_action' in action:
        write_preset(context)
    return False
