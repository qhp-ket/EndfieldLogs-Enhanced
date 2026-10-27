"""Decode buffs operation payloads without changing operation order."""
from endfield_pcap.service.session.operations.context import BattleOperation


def trigger_keyword(context: BattleOperation) -> None:
    op = context.operation
    if op.WhichOneof('op_data_impl') != 'trigger_keyword_op_data':
        return
    keyword = op.trigger_keyword_op_data
    context.emit({'seq_id': int(op.seq_id), 'client_tick_tms': int(op.client_tick_tms),
    'owner_id': str(op.owner_id), 'generation': int(op.generation),
    'buff_inst_id': str(keyword.buff_inst_id),
    'add_buff_num_id': int(keyword.add_buff_num_id),
    'modify': [{'config_index': int(row.config_index),
                'modify_value': float(row.modify_value)} for row in keyword.modify],
    'operation_payload_case': op.WhichOneof('op_data_impl')})


def set_buff_enable_state(context: BattleOperation) -> None:
    op = context.operation
    state_data = getattr(op, 'set_buff_enable_state_op_data', None)
    if state_data is None:
        return
    context.emit({'seq_id': int(op.seq_id), 'client_tick_tms': int(op.client_tick_tms),
    'owner_id': int(op.owner_id), 'generation': int(op.generation),
    'states': {str(uid): enabled for uid, enabled in state_data.buff_inst_id_to_enable_state.items()}})


def finish_buff(context: BattleOperation) -> None:
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    finish_data = getattr(op, "finish_buff_op_data", None)
    if finish_data is None:
        return
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "buff_inst_id": int(getattr(finish_data, "buff_inst_id", 0)) or None,
    })


def add_buff(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    add_data = getattr(op, "add_buff_op_data", None)
    if add_data is None:
        return
    _, template_int_id, template_str_id = session._template_id_payload(getattr(add_data, "buff_id", None))
    payload: dict[str, object | None] = {
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "operation_owner_id": str(op.owner_id) if hasattr(op, "owner_id") else None,
        "generation": int(op.generation) if hasattr(op, "generation") else None,
        "int_id": template_int_id,
        "buff_inst_id": int(getattr(add_data, "buff_inst_id", 0)) or None,
        "src_inst_id": int(getattr(add_data, "src_inst_id", 0)) or None,
        "target_inst_id": int(getattr(add_data, "target_inst_id", 0)) or None,
        "assigned_items": session._message_to_payload(getattr(add_data, "assigned_items", None)),
    }
    buff_template = getattr(add_data, "buff_id", None)
    if buff_template is not None and hasattr(buff_template, "WhichOneof"):
        payload["buff_template_id"] = session._message_to_payload(buff_template, include_implicit_defaults=True)
        payload["buff_template_id_case"] = buff_template.WhichOneof("id_impl")
    if template_str_id:
        payload["str_id"] = template_str_id
    context.emit(payload)
