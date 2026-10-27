"""Resource, poise and battle-state observations emitted by the trace owner."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any
from endfield_pcap.trace.formatting import _intish, _floatish
if TYPE_CHECKING:
    from endfield_pcap.trace.bridge import TraceBridge


def handle_update_atb_info(bridge: TraceBridge, event: dict[str, Any], ts_ms: int) -> None:
    # 技力(atb)更新：主控角色重击(连招末段)回技力 = reason=AddValue 的正 delta。
    # 排轴据此区分主控重击 vs 非主控 AI 重击。owner 归到角色，source 归到触发技能。
    owner_id = _intish(event.get("owner_id"))
    owner = bridge._name_for_id(owner_id)
    owner_hint = bridge._character_from_template(owner) or ""
    source_skill = bridge._resolve_skill_template(
        event.get("template_str_id"),
        event.get("template_int_id"),
        owner_hint=owner_hint,
    )
    orig_source_skill = bridge._resolve_skill_template(
        event.get("orig_template_str_id"),
        event.get("orig_template_int_id"),
        owner_hint=owner_hint,
    )
    seq = _intish(event.get("seq_id")) or 0
    client_tick = _intish(event.get("client_tick_tms")) or 0
    atb_value = _floatish(event.get("atb_value"))
    recovery_speed = _floatish(event.get("atb_recovery_speed"))
    delta = _floatish(event.get("delta_value"))
    parts = [
        "ATB_UPDATE",
        f"seq={seq}",
        f"tick={client_tick}",
        f"owner={owner}",
        f"ownerId={owner_id if owner_id is not None else 'unknown'}",
        f"reason={event.get('reason') or 'unknown'}",
        f"atb={atb_value:.6g}" if atb_value is not None else "atb=unknown",
        f"recoverySpeed={recovery_speed:.6g}" if recovery_speed is not None else "recoverySpeed=unknown",
        f"delta={delta:.6g}" if delta is not None else "delta=unknown",
        f"source={source_skill or event.get('template_str_id') or 'unknown'}",
        f"origSource={orig_source_skill or event.get('orig_template_str_id') or 'unknown'}",
    ]
    bridge._line(ts_ms, " ".join(parts))


def handle_modify_poise_value(bridge: TraceBridge, event: dict[str, Any], ts_ms: int) -> None:
    attacker_id = _intish(event.get("attacker_inst_id"))
    attacker = bridge._name_for_id(attacker_id)
    owner_hint = bridge._character_from_template(attacker) or ""
    source_skill = bridge._resolve_skill_template(
        event.get("template_str_id"),
        event.get("template_int_id"),
        owner_hint=owner_hint,
    )
    original_source_skill = bridge._resolve_skill_template(
        event.get("orig_template_str_id"),
        event.get("orig_template_int_id"),
        owner_hint=owner_hint,
    )
    seq = _intish(event.get("seq_id")) or 0
    client_tick = _intish(event.get("client_tick_tms")) or 0
    template_int_id = _intish(event.get("template_int_id"))
    orig_template_int_id = _intish(event.get("orig_template_int_id"))
    action_id = _intish(event.get("action_id"))
    value = _floatish(event.get("value"))
    cur_poise_value = _floatish(event.get("cur_poise_value"))
    parts = [
        "POISE_V1",
        f"seq={seq}",
        f"tick={client_tick}",
        f"type={event.get('modify_type') or 'unknown'}",
        f"value={value:.6g}" if value is not None else "value=unknown",
        f"cur={cur_poise_value:.6g}" if cur_poise_value is not None else "cur=unknown",
        f"attacker={attacker}",
        f"attackerId={attacker_id if attacker_id is not None else 'unknown'}",
        f"ownerType={event.get('owner_type') or 'unknown'}",
        f"sourceType={event.get('template_type') or 'unknown'}",
        f"source={source_skill or event.get('template_str_id') or 'unknown'}",
        f"sourceInt={template_int_id if template_int_id is not None else 'unknown'}",
        f"origSourceType={event.get('orig_template_type') or 'unknown'}",
        f"origSource={original_source_skill or event.get('orig_template_str_id') or 'unknown'}",
        f"origSourceInt={orig_template_int_id if orig_template_int_id is not None else 'unknown'}",
        f"actionId={action_id if action_id is not None else 'unknown'}",
    ]
    bridge._line(ts_ms, " ".join(parts))


def handle_battle_state(bridge: TraceBridge, event: dict[str, Any], ts_ms: int) -> None:
    is_in_battle = bool(event.get("is_in_battle"))
    if is_in_battle and not bridge._battle_active:
        is_war_echo_continuation = (
            bridge._official_timer_required() and bridge._official_timer_expected
        )
        bridge._challenge_pass_confirmed = False
        bridge._battle_active = True
        if bridge._official_timer_required():
            bridge._official_timer_expected = True
            bridge._official_timer_game_id = bridge._activity_id()
            if bridge._official_timer_observed_start_ts_ms is None:
                bridge._official_timer_observed_start_ts_ms = ts_ms
        bridge._battle_start_ts_ms = ts_ms
        seq = _intish(event.get("seq_id")) or 0
        raw_client_tick = _intish(event.get("client_tick_tms"))
        client_tick = raw_client_tick or 0
        bridge._battle_start_client_tick_ms = raw_client_tick
        if bridge._current_dungeon_context is not None and not bridge._battle_dungeon_context_emitted:
            bridge._write_dungeon_context(ts_ms, bridge._current_dungeon_context)
            bridge._battle_dungeon_context_emitted = True
        if is_war_echo_continuation:
            bridge._line(
                ts_ms,
                (
                    "BATTLE_PHASE_START "
                    f"seq={seq} source=BattleOpModifyBattleState "
                    f"gameId={bridge._activity_id()}"
                ),
            )
            return
        timer_source = "PacketBattleState" if raw_client_tick is not None else "BattleOpModifyBattleState"
        official = 1 if raw_client_tick is not None else 0
        bridge._line(
            ts_ms,
            f"GAME_TIMER_START seq={seq} source={timer_source} startMs={client_tick} expireMs=0 official={official}",
        )
    elif not is_in_battle and bridge._battle_active and bridge._official_timer_required():
        bridge._line(
            ts_ms,
            (
                "OFFICIAL_TIMER_AWAIT source=BattleOpModifyBattleState "
                f"gameId={bridge._activity_id()} "
                f"officialStartSeen={1 if bridge._official_timer_active else 0}"
            ),
        )
        bridge._clear_packet_battle_window()
    elif not is_in_battle and bridge._battle_active:
        bridge._battle_active = False
        seq = _intish(event.get("seq_id")) or 0
        raw_client_tick = _intish(event.get("client_tick_tms"))
        client_tick = raw_client_tick or 0
        start_tick = bridge._battle_start_client_tick_ms if bridge._battle_start_client_tick_ms is not None else client_tick
        packet_elapsed_ms = (
            client_tick - start_tick
            if raw_client_tick is not None and bridge._battle_start_client_tick_ms is not None
            else None
        )
        wall_elapsed_ms = max(ts_ms - bridge._battle_start_ts_ms, 0) if bridge._battle_start_ts_ms is not None else 0
        if packet_elapsed_ms is not None and packet_elapsed_ms >= 0:
            timer_source = "PacketBattleState"
            official = 1
            elapsed_ms = wall_elapsed_ms
        else:
            timer_source = "BattleOpModifyBattleState"
            official = 0
            elapsed_ms = wall_elapsed_ms
        packet_elapsed_token = (
            f" packetElapsedMs={packet_elapsed_ms}"
            if packet_elapsed_ms is not None and packet_elapsed_ms >= 0
            else ""
        )
        wall_elapsed_token = (
            f" wallElapsedMs={wall_elapsed_ms}"
            if wall_elapsed_ms > 0 and wall_elapsed_ms != elapsed_ms
            else ""
        )
        bridge._line(
            ts_ms,
            (
                f"GAME_TIMER_END seq={seq} source={timer_source} "
                f"elapsedMs={elapsed_ms} startMs={start_tick} endMs={client_tick} "
                f"expireMs=0 sane={1 if elapsed_ms > 0 else 0} official={official}"
                f"{packet_elapsed_token}{wall_elapsed_token}"
            ),
        )
        bridge._battle_start_ts_ms = None
        bridge._battle_start_client_tick_ms = None
        bridge._battle_dungeon_context_emitted = False
