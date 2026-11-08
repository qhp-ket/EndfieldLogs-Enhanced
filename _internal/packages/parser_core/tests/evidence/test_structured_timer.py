"""Timer events preserve authority, optional raw fields and independent export."""
from datetime import date

import pytest

from endfield_pcap.trace.bridge import TraceBridge
from endfield_pcap.trace.legacy_timer import timer_legacy_lines
from endfield_pcap.trace.legacy_stage import stage_legacy_lines
from endfield_pcap.trace.legacy_context import context_legacy_lines
from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.structured import consume_trace_event
from parser_core.trace_jsonl import TraceEvent, parse, serialize


def state():
    return IngestionState(reference_date=date(2026, 10, 31), first_hit_hint_ms=None,
        last_hit_hint_ms=None, context_enemy_hint=None, trace_identity_inference_seen=False,
        loadout_override_by_char=None, critical_attributes_override_by_actor=None)


def test_packet_timer_keeps_wall_and_packet_time_without_legacy_parsing(monkeypatch):
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Timer emitted legacy text'))
    bridge.begin_capture_session(timestamp_ms=1000)
    bridge.handle_event({'type': 'BattleOpModifyBattleState', 'timestamp_ms': 1100,
                         'is_in_battle': True, 'client_tick_tms': 2000, 'seq_id': 0})
    bridge.handle_event({'type': 'BattleOpModifyBattleState', 'timestamp_ms': 2100,
                         'is_in_battle': False, 'client_tick_tms': 2600, 'seq_id': 1})
    bridge.end_capture_session()
    events = [parse(serialize(event), header=False) for event in events]
    assert [event.type for event in events] == ['battle_timer'] * 3
    assert [event.data['phase'] for event in events] == ['reset', 'start', 'end']
    assert [line for event in events for line in timer_legacy_lines(event, timezone_offset_minutes=330)] == [
        '[05:30:01.000] GAME_TIMER_RESET source=CAPTURE_SESSION_START\n',
        '[05:30:01.100] GAME_TIMER_START seq=0 source=PacketBattleState startMs=2000 expireMs=0 official=1\n',
        '[05:30:02.100] GAME_TIMER_END seq=1 source=PacketBattleState elapsedMs=1000 startMs=2000 endMs=2600 expireMs=0 sane=1 official=1 packetElapsedMs=600\n']
    import parser_core.ingestion.timers as timers
    monkeypatch.setattr(timers, '_extract_fields', lambda *_: pytest.fail('Typed timer parsed old fields'))
    stream = state()
    for index, event in enumerate(events, 1):
        consume_trace_event(stream, event, index)
    assert stream.game_timer_elapsed_ms == 1000 and stream.packet_timer_elapsed_ms == 600
    assert stream.timer_start_seen and stream.timer_end_seen
    assert stream.timer_observed_times == {1: 1000, 2: 1100, 3: 2100}
    assert not stream.official_pass_confirmed and not stream.hits


@pytest.mark.parametrize('pass_time', [None, 0, -1, True, 'unknown'])
def test_raw_invalid_official_duration_does_not_become_elapsed(pass_time):
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append)
    bridge.handle_event({'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE',
                         'timestamp_ms': 2000, 'pass_time': pass_time})
    event = events[0]
    assert 'pass_time' in event.data and event.data['pass_time'] == pass_time
    stream = state()
    consume_trace_event(stream, event, 1)
    assert stream.official_timer_elapsed_ms is None and not stream.timer_end_seen
    assert not stream.challenge_pass_confirmed
    token = '' if pass_time is None else f' passTime={pass_time}'
    assert timer_legacy_lines(event, timezone_offset_minutes=0) == [
        '[00:00:02.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE' + token + '\n']


def test_new_official_start_clears_prior_completion_and_keeps_missing_fields():
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append)
    bridge.handle_event({'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', 'timestamp_ms': 1000,
                         'game_id': 'synthetic', 'is_pass': True, 'pass_time': 750})
    bridge.handle_event({'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_START', 'timestamp_ms': 2000,
                         'game_id': 'synthetic', 'challenge_start_ts': None, 'prepare_challenge_seconds': 0})
    stream = state()
    consume_trace_event(stream, events[0], 1)
    assert stream.official_timer_elapsed_ms == 750 and stream.official_pass_confirmed
    consume_trace_event(stream, events[1], 2)
    assert stream.official_timer_elapsed_ms is None and stream.game_timer_elapsed_ms is None
    assert not stream.official_pass_confirmed and not stream.timer_end_seen and stream.completion_source == ''
    assert events[1].data['challenge_start_ts'] is None and events[1].data['prepare_seconds'] == 0
    assert 'challenge_expire_ts' not in events[1].data


def test_nonauthoritative_timer_and_capture_reset_keep_existing_semantics():
    stream = state()
    consume_trace_event(stream, TraceEvent(1, 1000, 'battle_timer', {
        'phase': 'end', 'source': 'BattleOpModifyBattleState', 'elapsed_ms': 500, 'sane': True, 'official': False}, {}), 1)
    assert stream.game_timer_elapsed_ms is None and not stream.timer_end_seen
    consume_trace_event(stream, TraceEvent(2, 2000, 'official_timer', {
        'phase': 'end', 'source': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', 'pass_time': 900, 'is_pass': True}, {}), 2)
    stream.critical_stats_by_actor['11'] = {'crit_rate': 0.2}
    consume_trace_event(stream, TraceEvent(3, 3000, 'battle_timer', {
        'phase': 'reset', 'source': 'CAPTURE_SESSION_START'}, {}), 3)
    assert not stream.critical_stats_by_actor
    assert stream.official_timer_elapsed_ms == 900 and stream.official_pass_confirmed
    assert stream.timer_observed_times[3] == 3000


@pytest.mark.parametrize('data', [{'phase': 'end'}, {'phase': 'invalid', 'source': 'PacketBattleState'}])
def test_invalid_timer_is_rejected_before_state_mutation(data):
    stream = state()
    with pytest.raises(ValueError):
        consume_trace_event(stream, TraceEvent(1, 1000, 'battle_timer', data, {}), 1)
    assert stream.first_context_ms is None and not stream.timer_observed_times


def test_stage_objects_preserve_optional_fields_and_legacy_contract_projection(monkeypatch):
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Stage emitted legacy text'))
    bridge.handle_event({'type': 'DUNGEON_CONTEXT', 'timestamp_ms': 1000, 'dungeon_id': ' synthetic ',
                         'is_calc': True, 'is_pass': True, 'scene_num_id': 0, 'scene_id': None, 'is_reward': False})
    bridge.handle_event({'type': 'CONTRACT_TAGS', 'timestamp_ms': 2000, 'dungeon_id': 'synthetic',
                         'tag_ids': [], 'tagIds': [0, -2, '0003', 3, 4.8, 'bad'],
                         'score': 0, 'direction': 'sc', 'msg_id': 0})
    events = [parse(serialize(event), header=False) for event in events]
    assert [event.type for event in events] == ['battle_result', 'dungeon', 'contracts']
    assert events[1].data['scene_id'] is None and events[1].data['is_reward'] is False
    assert events[2].data['tag_ids'] == [] and events[2].data['message_id'] == 0
    assert [line for event in events for line in stage_legacy_lines(event, timezone_offset_minutes=0)] == [
        '[00:00:01.000] BATTLE_RESULT source=DUNGEON_CONTEXT dungeonId=synthetic isCalc=1 isPass=1\n',
        '[00:00:01.000] DUNGEON_CONTEXT dungeonId=synthetic source=packet scene=0 isReward=0 isCalc=1 isPass=1\n',
        '[00:00:02.000] CONTRACT_TAGS dungeonId=synthetic source=packet tagIds=[-2,3,3,4] score=0 direction=sc\n']
    import parser_core.ingestion.timers as timers
    monkeypatch.setattr(timers, '_extract_fields', lambda *_: pytest.fail('Typed stage parsed old fields'))
    monkeypatch.setattr(timers, '_parse_contract_tag_ids', lambda *_: pytest.fail('Typed stage parsed old tag text'))
    stream = state()
    for index, event in enumerate(events, 1):
        consume_trace_event(stream, event, index)
    assert stream.dungeon_context_id == 'synthetic' and stream.challenge_pass_confirmed
    assert stream.completion_source == 'DUNGEON_CONTEXT'
    assert stream.contract_tag_ids == [2, 3, 3, 4] and stream.contract_tag_score == 0
    assert stream.game_timer_elapsed_ms is None and not stream.timer_observed_times


def test_contracts_keep_missing_dungeon_unknown_without_inventing_identity():
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append)
    bridge.handle_event({'type': 'CONTRACT_TAGS', 'timestamp_ms': 1000, 'tag_ids': [7]})
    assert events[0].data['dungeon_id'] is None
    stream = state()
    consume_trace_event(stream, events[0], 1)
    assert stream.dungeon_context_id == 'unknown' and stream.dungeon_context is None
    assert stream.contract_tag_ids == [7] and not stream.party_actor_ids
    assert not stream.challenge_pass_confirmed


@pytest.mark.parametrize('kind,data', [('dungeon', {'source': 'packet'}),
                                      ('contracts', {'tag_ids': [7]}),
                                      ('battle_result', {'source': 'packet', 'dungeon_id': 7})])
def test_invalid_stage_is_rejected_before_state_mutation(kind, data):
    stream = state()
    with pytest.raises(ValueError):
        consume_trace_event(stream, TraceEvent(1, 1000, kind, data, {}), 1)
    assert stream.first_context_ms is None and stream.dungeon_context_id is None


def test_official_phase_await_and_leave_preserve_evidence_without_completion():
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Connected context emitted legacy text'))
    for payload in [
        {'type': 'DUNGEON_CONTEXT', 'timestamp_ms': 1000, 'dungeon_id': 'indie_battletower_synthetic'},
        {'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_START', 'timestamp_ms': 1100, 'game_id': 'indie_battletower_synthetic'},
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': 1200, 'is_in_battle': True, 'seq_id': 0},
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': 1300, 'is_in_battle': False},
        {'type': 'SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST', 'timestamp_ms': 1400,
         'game_id': 'indie_battletower_synthetic', 'game_inst_id': '0009007199254740993'},
    ]:
        bridge.handle_event(payload)
    bridge.end_capture_session()
    events = [parse(serialize(event), header=False) for event in events]
    assert [event.type for event in events] == [
        'dungeon', 'official_timer', 'dungeon', 'battle_phase', 'official_timer', 'game_instance', 'official_timer', 'battle_timer']
    rows = [line for event in events if event.type != 'dungeon'
            for line in (context_legacy_lines if event.type == 'game_instance' else timer_legacy_lines)(event, timezone_offset_minutes=0)]
    assert rows == [
        '[00:00:01.100] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower_synthetic\n',
        '[00:00:01.200] BATTLE_PHASE_START seq=0 source=BattleOpModifyBattleState gameId=indie_battletower_synthetic\n',
        '[00:00:01.300] OFFICIAL_TIMER_AWAIT source=BattleOpModifyBattleState gameId=indie_battletower_synthetic officialStartSeen=1\n',
        '[00:00:01.400] GAME_INST_LEAVE source=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST gameId=indie_battletower_synthetic gameInstId=9007199254740993\n',
        '[00:00:01.400] OFFICIAL_TIMER_MISSING boundary=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST packetBattleActive=0 officialExpected=1 officialStartSeen=1 gameId=indie_battletower_synthetic\n',
        '[00:00:01.400] GAME_TIMER_RESET source=SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST\n']
    assert events[5].data['game_inst_id'] == '9007199254740993'
    stream = state()
    for index, event in enumerate(events, 1):
        consume_trace_event(stream, event, index)
    assert stream.timer_observed_times == {2: 1100, 5: 1300, 6: 1400, 7: 1400, 8: 1400}
    assert stream.game_timer_elapsed_ms is None and stream.official_timer_elapsed_ms is None
    assert not stream.timer_end_seen and not stream.challenge_pass_confirmed and not stream.hits


def test_context_roundtrip_keeps_raw_freeze_rows_zero_null_and_bare_reset():
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Connected context emitted legacy text'))
    for payload in [
        {'type': 'SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE', 'timestamp_ms': 1000,
         'game_inst_id': 18446744073709551615, 'is_hunter_mode': False,
         'time_freeze_infos': [None, {'time_key': 0, 'total_freeze_time_in_ms': -7},
                               {'time_key': '02', 'total_freeze_time_in_ms': 3.9}, {}]},
        {'type': 'SC_RESET_BATTLE_STATUS', 'timestamp_ms': 2000},
        {'type': 'SC_RESET_BATTLE_STATUS', 'timestamp_ms': 3000, 'reason': 0, 'inst_id': None, 'battle_inst_id': '00012'},
        {'type': 'SESSION_WARNING', 'timestamp_ms': 4000, 'kind': '', 'direction': None,
         'missing_bytes': 0, 'startup_tcp_gap_count': None},
        {'type': 'SC_SCENE_SET_BATTLE', 'timestamp_ms': 5000, 'in_battle': False},
        {'type': 'SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD', 'timestamp_ms': 6000},
    ]:
        bridge.handle_event(payload)
    events = [parse(serialize(event), header=False) for event in events]
    assert [line for event in events for line in context_legacy_lines(event, timezone_offset_minutes=330)] == [
        '[05:30:01.000] GAME_MECHANICS_TIME_FREEZE source=SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE gameInstId=18446744073709551615 isHunterMode=0 count=4 freezeInfos=[0:-7,2:3,0:0] totalFreezeMs=3\n',
        '[05:30:02.000] BATTLE_RESET_STATUS\n',
        '[05:30:03.000] BATTLE_RESET_STATUS reason=0 battleInst=12\n',
        '[05:30:04.000] SESSION_WARNING kind=unknown direction=unknown missingBytes=0 gapCount=unknown\n',
        '[05:30:05.000] SCENE_BATTLE_STATE source=SC_SCENE_SET_BATTLE inBattle=0\n',
        '[05:30:06.000] SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD source=SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD\n']
    assert events[0].data['game_inst_id'] == '18446744073709551615'
    assert events[2].data['event_inst_id'] is None and events[2].data['battle_inst_id'] == '12'
    assert 'reason' not in events[1].data and events[3].data['missing_bytes'] == 0
    stream = state()
    for index, event in enumerate(events, 1):
        consume_trace_event(stream, event, index)
    assert stream.first_context_ms == 1000 and stream.last_context_ms == 6000
    assert stream.timer_observed_times == {1: 1000} and not stream.party_actor_ids
    assert not stream.challenge_pass_confirmed and stream.game_timer_elapsed_ms is None


def test_capture_lost_has_missing_packet_timer_without_fabricating_an_end():
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Connected timer emitted legacy text'))
    bridge.handle_event({'type': 'BattleOpModifyBattleState', 'timestamp_ms': 1000, 'is_in_battle': True})
    bridge.end_capture_session()
    assert [event.type for event in events] == ['battle_timer', 'battle_timer_missing']
    assert timer_legacy_lines(events[1], timezone_offset_minutes=0) == [
        '[00:00:01.000] BATTLE_TIMER_MISSING boundary=CAPTURE_SESSION_LOST packetBattleActive=1 officialExpected=0 officialStartSeen=0\n']
    stream = state()
    for index, event in enumerate(events, 1):
        consume_trace_event(stream, event, index)
    assert not stream.timer_end_seen and stream.game_timer_elapsed_ms is None


def test_direct_official_evidence_reaches_report_without_scanning_legacy_text(monkeypatch):
    from copy import deepcopy
    from parser_core.ingestion.fields import _extract_fields, _parse_prefixed_timestamp_ms
    from parser_core.reporting.state import ReportState
    import parser_core.reporting.timing as timing
    from parser_core.timing.timer_evidence import collect_timer_evidence, validate_timer_evidence
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append,
                         line_sink=lambda *_: pytest.fail('Lifecycle emitted legacy text'))
    game = 'indie_battletower_synthetic'
    for payload in [
        {'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_START', 'timestamp_ms': 1000,
         'game_id': game, 'challenge_start_ts': 1234},
        {'type': 'SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE', 'timestamp_ms': 1500, 'game_id': game,
         'time_freeze_infos': [{'time_key': 0, 'total_freeze_time_in_ms': 100}]},
        {'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', 'timestamp_ms': 2000,
         'game_id': game, 'is_pass': True, 'pass_time': 800},
    ]:
        bridge.handle_event(payload)
    stream = state()
    for index, event in enumerate(events, 1):
        consume_trace_event(stream, event, index)
    rows = [(context_legacy_lines if event.type == 'game_mechanics' else timer_legacy_lines)(event, timezone_offset_minutes=0)[0]
            for event in events]
    expected = collect_timer_evidence(''.join(rows), _extract_fields, _parse_prefixed_timestamp_ms)
    assert stream.official_timer_collector.evidence == expected
    assert validate_timer_evidence(expected, duration_ms=800, game_id=game) == []
    report = ReportState.from_snapshot(deepcopy(stream.snapshot()))
    monkeypatch.setattr(timing, 'collect_timer_evidence', lambda *_args, **_kwargs: pytest.fail('Report rescanned trace text'))
    evidence, observed, scope = timing.apply_official_timing(report, '', None)
    assert evidence == expected and observed == 1000 and scope['line'] == 1
    assert report.game_timer_elapsed_ms == 800 and report.official_pass_confirmed
    # A captured report owns this evidence while ingestion continues to a new capture.
    bridge.begin_capture_session(timestamp_ms=3000)
    consume_trace_event(stream, events[-1], 4)
    assert report.official_timer_evidence == expected
    assert stream.official_timer_collector.evidence['start'] is None
