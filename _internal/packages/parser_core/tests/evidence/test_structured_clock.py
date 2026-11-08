"""Clock events keep BUFF ordering and do not manufacture combat time."""
from datetime import date

import pytest

from endfield_pcap.trace.bridge import TraceBridge
from endfield_pcap.trace.legacy_clock import clock_legacy_lines
from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.structured import consume_trace_event
from parser_core.ingestion.structured_clock import clock_observation
from parser_core.trace_jsonl import TraceEvent, parse, serialize


def test_clock_bypass_preserves_pending_buff_time_and_exact_export():
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Clock emitted legacy text'))
    bridge.handle_event({'type': 'BattleOpAddBuff', 'timestamp_ms': 1000, 'buff_inst_id': 8,
                         'int_id': 55, 'target_inst_id': 11, 'src_inst_id': 22})
    bridge.handle_event({'type': 'CS_PING', 'timestamp_ms': 9000, 'client_ts': 9007199254740993,
                         'server_ts': -1, 'logical_ts': 0, 'msg_id': 0, 'raw_body_hex': ''})
    bridge.handle_event({'type': 'GAME_CLOCK_TICK', 'timestamp_ms': 9100, 'source': 'CS_BATTLE_OP',
                         'tick_ms': '00042', 'seq_id': 0})
    bridge.handle_event({'type': 'SC_GAME_TIME_FREEZE_END_RSP', 'timestamp_ms': 9200,
                         'in_time_freeze': False, 'reason': 0, 'msg_id': None})
    bridge.handle_event({'type': 'CS_GAME_TIME_FREEZE_START_REQ', 'timestamp_ms': 9300, 'raw_body_hex': ''})
    assert [event.type for event in events] == ['clock_sync', 'clock_tick', 'time_freeze_state', 'time_freeze_request']
    for tick, source in ((0, 'CS_BATTLE_OP'), (-1, 'CS_BATTLE_OP'), (42, 'OTHER')):
        bridge.handle_event({'type': 'GAME_CLOCK_TICK', 'timestamp_ms': 9400, 'source': source, 'tick_ms': tick})
    bridge.handle_event({'type': 'CS_PING', 'client_ts': 0})
    assert len(events) == 4
    bridge.end_capture_session()
    assert events[4].type == 'buff_start' and events[4].captured_at_ms == 1000
    clocks = [parse(serialize(event), header=False) for event in events[:4]]
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert clocks[0].data['client_ts'] == 9007199254740993 and clocks[0].data['server_ts'] == -1
    assert clocks[1].data['tick_ms'] == 42 and clocks[1].source['operation_seq'] == 0
    assert 'operation_seq' not in clocks[1].data
    assert 'message_id' not in clocks[3].data and clocks[2].data['message_id'] is None
    assert [line for event in clocks for line in clock_legacy_lines(event, timezone_offset_minutes=330)] == [
        '[05:30:09.000] GAME_CLOCK_SYNC source=CS_PING msgId=0 captureMs=9000 clientTs=9007199254740993 logicalTs=0 rawBodyHex=empty\n',
        '[05:30:09.100] GAME_CLOCK_TICK source=CS_BATTLE_OP tickMs=42 seq=0\n',
        '[05:30:09.200] GAME_TIME_FREEZE_STATE source=SC_GAME_TIME_FREEZE_END_RSP inTimeFreeze=0 reason=0 msgId=None rawBodyHex=unknown\n',
        '[05:30:09.300] GAME_TIME_FREEZE_REQUEST source=CS_GAME_TIME_FREEZE_START_REQ reason=unknown msgId=unknown rawBodyHex=empty\n']
    assert clock_observation(clocks[0]).server_ts is None
    assert clock_observation(clocks[2]).frozen is False


def test_clock_ingestion_keeps_unknown_freeze_distinct_from_false():
    stream = IngestionState(reference_date=date(2026, 10, 31), first_hit_hint_ms=None,
        last_hit_hint_ms=None, context_enemy_hint=None, trace_identity_inference_seen=False,
        loadout_override_by_char=None, critical_attributes_override_by_actor=None)
    for value in (0, None, 'false'):
        event = TraceEvent(1, -1, 'time_freeze_state', {'source': 'SC_GAME_TIME_FREEZE_END_RSP', 'in_time_freeze': value}, {})
        assert clock_observation(event).frozen is None
        consume_trace_event(stream, event, 1)
    assert stream.last_context_ms == -1 and stream.game_timer_elapsed_ms is None
    assert not stream.hits and not stream.timer_observed_times and not stream.party_actor_ids
    clean = IngestionState(reference_date=date(2026, 10, 31), first_hit_hint_ms=None,
        last_hit_hint_ms=None, context_enemy_hint=None, trace_identity_inference_seen=False,
        loadout_override_by_char=None, critical_attributes_override_by_actor=None)
    with pytest.raises(ValueError, match='source'):
        consume_trace_event(clean, TraceEvent(1, 0, 'clock_sync', {}, {}), 1)
    assert clean.first_context_ms is None
