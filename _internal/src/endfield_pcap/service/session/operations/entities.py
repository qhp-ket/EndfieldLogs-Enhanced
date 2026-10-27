"""Decode entities operation payloads without changing operation order."""
from endfield_pcap.service.session.operations.context import BattleOperation


def entity_die(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    die_data = getattr(op, "entity_die_op_data", None)
    if die_data is None:
        return
    entity_inst_id = int(getattr(die_data, "entity_inst_id", 0)) or None
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "entity_inst_id": entity_inst_id,
    })
    if (
        session.merge_multi_phase_enemy_battles
        and session.merged_battle_active
        and entity_inst_id is not None
        and entity_inst_id in session.tracked_enemy_inst_ids
    ):
        context.emit({
            "seq_id": seq_id,
            "client_tick_tms": client_tick_tms,
            "is_in_battle": False,
        }, event_type="BattleOpModifyBattleState")
        session.merged_battle_active = False
        session.tracked_enemy_inst_ids.clear()


def entity_value_modify(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    value_data = getattr(op, "entity_value_modify_data", None)
    if value_data is None:
        return
    template_type, template_int_id, template_str_id = session._template_id_payload(getattr(value_data, "template_id", None))
    orig_template_type, orig_template_int_id, orig_template_str_id = session._template_id_payload(
        getattr(value_data, "original_source_template_id", None)
    )
    battle_info = getattr(value_data, "value", None)
    payload: dict[str, object | None] = {
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "owner_id": int(getattr(op, "owner_id", 0)) or None,
        "entity_inst_id": int(getattr(value_data, "entity_inst_id", 0)) or None,
        "scene_num_id": int(getattr(value_data, "scene_num_id", 0)) or None,
        "source": int(getattr(value_data, "source", 0)) or None,
        "hp": float(getattr(battle_info, "hp", 0.0) or 0.0) if battle_info is not None else None,
        "ultimatesp": float(getattr(battle_info, "ultimatesp", 0.0) or 0.0) if battle_info is not None else None,
        "delta_value": session._read_float_presence(value_data, "delta_value"),
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


def modify_battle_state(context: BattleOperation) -> None:
    session = context.session
    op = context.operation
    timestamp_ms = context.timestamp_ms
    seq_id = context.sequence_id
    client_tick_tms = context.client_tick_ms
    battle_state_data = getattr(op, "modify_battle_state_op_data", None)
    if battle_state_data is None:
        return
    is_in_battle = bool(getattr(battle_state_data, "is_in_battle", False))
    if session.merge_multi_phase_enemy_battles and session.tracked_enemy_templateid is not None:
        if is_in_battle and not session.merged_battle_active:
            session.merged_battle_active = True
        else:
            return
    context.emit({
        "seq_id": seq_id,
        "client_tick_tms": client_tick_tms,
        "is_in_battle": is_in_battle,
    })
    if is_in_battle:
        if session.squad_index:
            session._emit_scene_info_event(timestamp_ms)
        session._emit_loadout_event("BATTLE_START", timestamp_ms, force=True)
