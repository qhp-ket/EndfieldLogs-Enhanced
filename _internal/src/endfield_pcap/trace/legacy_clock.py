"""Independent clock export, retaining the observed timestamp and scalar layout."""
from datetime import datetime, timedelta, timezone

from parser_core.ingestion.structured_clock import CLOCK_TYPES
from parser_core.ingestion.skill_wire import integer
from parser_core.trace_values import restore_value


def clock_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in CLOCK_TYPES:
        raise ValueError('Expected clock event')
    if 'legacy_layout' not in event.data:
        raise ValueError('Clock event lacks legacy export layout')
    data = restore_value(event.data, event.data['legacy_layout'])
    source = data['source']
    message = data.get('message_id', 'unknown')
    raw = data.get('raw_body_hex')
    raw_token = (raw or 'empty') if isinstance(raw, str) else 'unknown'
    if event.type == 'clock_tick':
        if source in ('GAME_TIMER_TICK', 'HEARTBEAT'):
            from endfield_pcap.trace.legacy_historical import historical_body
            body = historical_body(event.type, data)
        else:
            sequence = integer(data.get('operation_seq'))
            body = f"GAME_CLOCK_TICK source={source} tickMs={integer(data.get('tick_ms'))} seq={sequence if sequence is not None else 'unknown'}"
    elif event.type == 'clock_sync':
        parts = [f'GAME_CLOCK_SYNC source={source}', f'msgId={message}', f'captureMs={event.captured_at_ms}']
        for key, target in (('client_ts', 'clientTs'), ('server_ts', 'serverTs'), ('logical_ts', 'logicalTs')):
            value = integer(data.get(key))
            if value is not None and value >= 0:
                parts.append(f'{target}={value}')
        if isinstance(raw, str):
            parts.append(f'rawBodyHex={raw_token}')
        body = ' '.join(parts)
    else:
        reason = integer(data.get('reason'))
        token = reason if reason is not None else 'unknown'
        if event.type == 'time_freeze_request':
            body = f'GAME_TIME_FREEZE_REQUEST source={source} reason={token} msgId={message} rawBodyHex={raw_token}'
        else:
            frozen = data.get('in_time_freeze')
            body = f"GAME_TIME_FREEZE_STATE source={source} inTimeFreeze={int(frozen) if type(frozen) is bool else 'unknown'} reason={token} msgId={message} rawBodyHex={raw_token}"
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {body}\n"]
