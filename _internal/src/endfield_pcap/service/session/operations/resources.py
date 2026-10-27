"""Decode resources operation payloads without changing operation order."""
from endfield_pcap.service.session.operations.context import BattleOperation


def modify_poise_value(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    poise_data = getattr(op, "modify_poise_value_op_data", None)
    if poise_data is None:
        return
    template_type, template_int_id, template_str_id = session._template_id_payload(
        getattr(poise_data, "template_id", None)
    )
    orig_template_type, orig_template_int_id, orig_template_str_id = session._template_id_payload(
        getattr(poise_data, "original_source_template_id", None)
    )
    payload = {
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "owner_id": int(getattr(op, "owner_id", 0)) or None,
        "modify_type": session._field_enum_name(poise_data, "modify_type"),
        "owner_type": session._field_enum_name(poise_data, "owner_type"),
        "value": float(getattr(poise_data, "value", 0.0) or 0.0),
        "cur_poise_value": float(getattr(poise_data, "cur_poise_value", 0.0) or 0.0),
        "attacker_inst_id": int(getattr(poise_data, "attacker_inst_id", 0)) or None,
        "action_id": int(getattr(poise_data, "action_id", 0)) or None,
        "template_type": template_type,
        "template_int_id": template_int_id,
        "orig_template_type": orig_template_type,
        "orig_template_int_id": orig_template_int_id,
        "battle_report_info": session._message_to_payload(getattr(poise_data, "battle_report_info", None)),
    }
    if template_str_id:
        payload["template_str_id"] = template_str_id
    if orig_template_str_id:
        payload["orig_template_str_id"] = orig_template_str_id
    context.emit(payload)


def update_atb_info(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    atb_op = getattr(op, "update_atb_info_op_data", None)
    if atb_op is None:
        return
    atb_data = getattr(atb_op, "atb_data", None)
    template_type, template_int_id, template_str_id = session._template_id_payload(
        getattr(atb_op, "template_id", None)
    )
    orig_template_type, orig_template_int_id, orig_template_str_id = session._template_id_payload(
        getattr(atb_op, "original_source_template_id", None)
    )
    payload = {
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "owner_id": int(getattr(op, "owner_id", 0)) or None,
        "atb_value": float(getattr(atb_data, "atb_value", 0.0) or 0.0) if atb_data is not None else None,
        "atb_recovery_speed": session._atb_recovery_speed(atb_data),
        "reason": session._field_enum_name(atb_data, "reason") if atb_data is not None else None,
        "delta_value": session._read_float_presence(atb_op, "delta_value"),
        "template_type": template_type,
        "template_int_id": template_int_id,
        "orig_template_type": orig_template_type,
        "orig_template_int_id": orig_template_int_id,
    }
    if template_str_id:
        payload["template_str_id"] = template_str_id
    if orig_template_str_id:
        payload["orig_template_str_id"] = orig_template_str_id
    context.emit(payload)
