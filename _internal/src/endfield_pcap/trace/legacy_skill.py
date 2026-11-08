"""Independent legacy rendering of skill, ATB and poise evidence."""
from datetime import datetime, timezone, timedelta
from parser_core.ingestion.skill_wire import integer, number, label, identity_token
from endfield_pcap.trace.export_values import export_data


def skill_legacy_lines(event, *, timezone_offset_minutes):
    data = export_data(event)
    def general(key):
        value = number(data.get(key))
        return format(value, ".6g") if value is not None else "unknown"
    seq, tick = integer(data.get("operation_seq")) or 0, integer(data.get("client_tick_ms")) or 0
    if event.type == "skill_cast":
        start = data["phase"] == "start"
        owner_id = identity_token(data.get("owner_id")) if start else str(data["owner_id"]) if data.get("owner_id") is not None else "unknown"
        body = (f"SKILL_CAST_{'START' if start else 'END'} seq={seq} {'startMs' if start else 'endMs'}={tick} "
                f"inst={identity_token(data.get('skill_inst_id'))} owner={label(data, 'owner', '?')} ownerId={owner_id} "
                f"skill={label(data, 'skill', 'unknown_skill')} skillSource={label(data, 'skill_source')}"
                + (f" captureMs={event.captured_at_ms}" if start else ""))
    elif event.type == "atb":
        body = (f"ATB_UPDATE seq={seq} tick={tick} owner={label(data, 'owner', '?')} ownerId={identity_token(data.get('owner_id'))} "
                f"reason={label(data, 'reason')} atb={general('value')} recoverySpeed={general('recovery_speed')} "
                f"delta={general('delta')} source={label(data, 'source')} origSource={label(data, 'original_source')}")
    elif event.type == "poise":
        body = (f"POISE_V1 seq={seq} tick={tick} type={label(data, 'modify_type')} value={general('value')} cur={general('current_value')} "
                f"attacker={label(data, 'attacker', '?')} attackerId={identity_token(data.get('attacker_id'))} "
                f"ownerType={label(data, 'owner_type')} sourceType={label(data, 'source_type')} source={label(data, 'source')} "
                f"sourceInt={identity_token(data.get('source_int'))} origSourceType={label(data, 'original_source_type')} "
                f"origSource={label(data, 'original_source')} origSourceInt={identity_token(data.get('original_source_int'))} "
                f"actionId={identity_token(data.get('action_id'))}")
    else:
        raise ValueError("Expected skill/resource event")
    stamp = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{stamp:%H:%M:%S}.{event.captured_at_ms % 1000:03d}] {body}\n"]
