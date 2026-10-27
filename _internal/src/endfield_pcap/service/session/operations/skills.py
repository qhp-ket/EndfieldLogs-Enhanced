"""Decode skills operation payloads without changing operation order."""
from endfield_pcap.service.session.operations.context import BattleOperation


def skill_attach(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    attach_data = getattr(op, "skill_attach_op_data", None)
    if attach_data is None:
        return
    template_type, template_int_id, template_str_id = session._template_id_payload(
        getattr(attach_data, "skill_id", None)
    )
    payload: dict[str, object | None] = {
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "src_inst_id": int(getattr(attach_data, "src_inst_id", 0)) or None,
        "skill_inst_id": int(getattr(attach_data, "skill_inst_id", 0)) or None,
        "skill_lv": int(getattr(attach_data, "skill_lv", 0)) or None,
        "skill_source": session._field_enum_name(attach_data, "skill_source"),
        "template_type": template_type,
        "template_int_id": template_int_id,
    }
    if template_str_id:
        payload["template_str_id"] = template_str_id
    context.emit(payload)


def skill_detach(context: BattleOperation) -> None:
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    detach_data = getattr(op, "skill_detach_op_data", None)
    if detach_data is None:
        return
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "skill_inst_id": int(getattr(detach_data, "skill_inst_id", 0)) or None,
    })


def skill_start_cast(context: BattleOperation) -> None:
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    cast_data = getattr(op, "skill_start_cast_op_data", None)
    if cast_data is None:
        return
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "owner_id": int(getattr(op, "owner_id", 0)) or None,
        "skill_inst_id": int(getattr(cast_data, "inst_id", 0)) or None,
    })


def skill_end_cast(context: BattleOperation) -> None:
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    cast_data = getattr(op, "skill_end_cast_op_data", None)
    if cast_data is None:
        return
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "owner_id": int(getattr(op, "owner_id", 0)) or None,
        "skill_inst_id": int(getattr(cast_data, "inst_id", 0)) or None,
    })


def trigger_action(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    timestamp_ms = context.timestamp_ms
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    session._emit_trigger_action_event(op, seq_id, client_tick_tms, timestamp_ms)


def enable_passive_skill(context: BattleOperation) -> None:
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    enable_data = getattr(op, "skill_enable_op_data", None)
    if enable_data is None:
        return
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "skill_inst_id": int(getattr(enable_data, "skill_inst_id", 0)) or None,
    })
