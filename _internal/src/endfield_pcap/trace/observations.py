"""Write explicit clock, keyword and entity observations using original trace evidence."""
from __future__ import annotations
import json
import math
import re
from typing import TYPE_CHECKING, Any
from endfield_pcap.trace.formatting import _intish, _floatish
if TYPE_CHECKING:
    from endfield_pcap.trace.bridge import TraceBridge

CLOCK_EVENTS = {'GAME_CLOCK_TICK', 'CS_PING', 'SC_PING', 'CS_GAME_TIME_FREEZE_START_REQ', 'CS_GAME_TIME_FREEZE_END_REQ', 'SC_GAME_TIME_FREEZE_START_RSP', 'SC_GAME_TIME_FREEZE_END_RSP'}


def write_clock_observation(bridge: TraceBridge, event: dict[str, Any], event_type: str, ts_ms: int | None) -> None:
    if ts_ms is None:
        return
    if event_type == "GAME_CLOCK_TICK":
        tick = _intish(event.get("tick_ms"))
        seq = _intish(event.get("seq_id"))
        if event.get("source") == "CS_BATTLE_OP" and tick is not None and tick > 0:
            bridge._append_line(ts_ms, f"GAME_CLOCK_TICK source=CS_BATTLE_OP tickMs={tick} seq={seq if seq is not None else 'unknown'}")
    elif event_type in {"CS_PING", "SC_PING"}:
        parts = [f"GAME_CLOCK_SYNC source={event_type}", f"msgId={event.get('msg_id', 'unknown')}", f"captureMs={ts_ms}"]
        for key, output_key in (("client_ts", "clientTs"), ("server_ts", "serverTs"), ("logical_ts", "logicalTs")):
            value = _intish(event.get(key))
            if value is not None and value >= 0:
                parts.append(f"{output_key}={value}")
        if isinstance(event.get("raw_body_hex"), str):
            parts.append(f"rawBodyHex={event['raw_body_hex'] or 'empty'}")
        bridge._append_line(ts_ms, " ".join(parts))
    elif event_type in {"CS_GAME_TIME_FREEZE_START_REQ", "CS_GAME_TIME_FREEZE_END_REQ"}:
        reason = _intish(event.get("reason"))
        raw_body = event.get("raw_body_hex")
        raw_token = (raw_body or "empty") if isinstance(raw_body, str) else "unknown"
        bridge._append_line(ts_ms, f"GAME_TIME_FREEZE_REQUEST source={event_type} reason={reason if reason is not None else 'unknown'} msgId={event.get('msg_id', 'unknown')} rawBodyHex={raw_token}")
    else:
        reason = _intish(event.get("reason"))
        frozen = event.get("in_time_freeze")
        raw_body = event.get("raw_body_hex")
        raw_token = (raw_body or "empty") if isinstance(raw_body, str) else "unknown"
        bridge._append_line(ts_ms, f"GAME_TIME_FREEZE_STATE source={event_type} inTimeFreeze={int(frozen) if type(frozen) is bool else 'unknown'} reason={reason if reason is not None else 'unknown'} msgId={event.get('msg_id', 'unknown')} rawBodyHex={raw_token}")
    return


def write_keyword_update(bridge: TraceBridge, event: dict[str, Any], ts_ms: int) -> None:
    updates = []
    errors = []
    raw_updates = event.get('modify')
    if not isinstance(raw_updates, list):
        errors.append('missing_keyword_modify_list')
    for row in raw_updates if isinstance(raw_updates, list) else []:
        value = None
        if isinstance(row, dict) and type(row.get('modify_value')) in (int, float):
            try:
                value = float(row['modify_value'])
            except (OverflowError, ValueError):
                pass
        if (not isinstance(row, dict) or type(row.get('config_index')) is not int
                or row['config_index'] < 0 or value is None or not math.isfinite(value)):
            errors.append('invalid_keyword_modify_row')
            continue
        updates.append({'configIndex': row['config_index'], 'rateAfter': value})
    observation = {
        'schemaVersion': 1, 'sessionId': event.get('session_id'),
        'ownerId': str(event['owner_id']) if type(event.get('owner_id')) in (int, str) else None,
        'generation': event.get('generation'), 'operationSeq': event.get('seq_id'),
        'clientTickMs': str(event['client_tick_tms']) if type(event.get('client_tick_tms')) in (int, str) else None,
        'buffUid': str(event['buff_inst_id']) if type(event.get('buff_inst_id')) in (int, str) else None,
        'addedBuffNumId': event.get('add_buff_num_id'), 'modify': updates,
        'operationPayloadCase': event.get('operation_payload_case'),
    }
    if observation['operationPayloadCase'] != 'trigger_keyword_op_data':
        errors.append('keyword_operation_presence_unverified')
    for field in ('ownerId', 'buffUid'):
        value = observation[field]
        if (not isinstance(value, str) or not re.fullmatch(r'[1-9][0-9]*', value)
                or int(value) >= 2**64):
            errors.append('invalid_' + field)
    for field in ('generation', 'operationSeq', 'addedBuffNumId'):
        if type(observation[field]) is not int or observation[field] < 0:
            errors.append('invalid_' + field)
    if not isinstance(observation['sessionId'], str) or not observation['sessionId']:
        errors.append('missing_sessionId')
    if errors:
        observation['validationErrors'] = errors
    elif updates:
        # The native list contains consecutive absolute rate results.
        # Keep the ordinary create-row de-duplication cache current,
        # without emitting a fabricated new Buff or lifetime.
        uid = int(observation['buffUid'])
        owner = int(observation['ownerId'])
        indices = [row['configIndex'] for row in updates]
        cache_key = (observation['sessionId'], observation['ownerId'], observation['buffUid'])
        previous = bridge._keyword_value_serials.get(cache_key)
        seq = observation['operationSeq']
        if (uid in bridge.buff_values_by_uid and bridge.buff_actor_ids_by_uid.get(uid, (None, None))[0] == owner
                and indices == sorted(set(indices))):
            final_rate = updates[-1]['rateAfter']
            if previous is None or seq > previous[0]:
                bridge._keyword_value_serials[cache_key] = (seq, final_rate)
                bridge.buff_values_by_uid[uid]['rate'] = final_rate
                bridge.buff_keys_by_uid.setdefault(uid, set()).add('rate')
            elif seq == previous[0] and previous[1] != final_rate:
                bridge._keyword_value_serials[cache_key] = (seq, None)
                bridge.buff_values_by_uid[uid].pop('rate', None)
    bridge._line(ts_ms, ('BUFF_KEYWORD_UPDATE_UNRESOLVED ' if errors else 'BUFF_KEYWORD_UPDATE ')
               + json.dumps(observation, ensure_ascii=False, separators=(',', ':'), allow_nan=False))


def write_buff_enable(bridge: TraceBridge, event: dict[str, Any], ts_ms: int) -> None:
    states = event.get('states')
    if isinstance(states, dict):
        for uid, enabled in states.items():
            bridge._line(ts_ms, 'BUFF_ENABLE ' + json.dumps({
                'schemaVersion': 1, 'buffUid': str(uid), 'enabled': enabled,
                'ownerId': str(event.get('owner_id')) if event.get('owner_id') is not None else None,
                'operationSeq': event.get('seq_id'), 'clientTickMs': event.get('client_tick_tms'),
                'generation': event.get('generation'),
            }, separators=(',', ':')))


def write_entity_value(bridge: TraceBridge, event: dict[str, Any], ts_ms: int) -> None:
    entity_inst_id = _intish(event.get("entity_inst_id"))
    hp = _floatish(event.get("hp"))
    ultimatesp = _floatish(event.get("ultimatesp"))
    delta_value = _floatish(event.get("delta_value"))
    template_int_id = _intish(event.get("template_int_id"))
    orig_template_int_id = _intish(event.get("orig_template_int_id"))
    bridge._line(
        ts_ms,
        (
            f"ENTITY_VALUE seq={event.get('seq_id')} "
            f"id={entity_inst_id if entity_inst_id is not None else 'unknown'} "
            f"scene={event.get('scene_num_id') if event.get('scene_num_id') is not None else 'unknown'} "
            f"hp={hp if hp is not None else 'unknown'} "
            f"ult={ultimatesp if ultimatesp is not None else 'unknown'} "
            f"delta={delta_value if delta_value is not None else 'unknown'} "
            f"srcType={event.get('template_type') or 'unknown'} "
            f"srcInt={template_int_id if template_int_id is not None else 'unknown'} "
            f"origSrcType={event.get('orig_template_type') or 'unknown'} "
            f"origSrcInt={orig_template_int_id if orig_template_int_id is not None else 'unknown'}"
        ),
    )
