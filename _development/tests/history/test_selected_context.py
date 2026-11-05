"""Selected history keeps pre-combat observations and the replay calendar day."""
from datetime import datetime, timedelta, timezone
import json

import pytest

from app_test_support.scenarios.raw import raw_hit, raw_scene
from endfield_pcap.history.analysis import load_record_snapshot
from endfield_pcap.history.export import default_battle_export_path, export_battle_log
from endfield_pcap.history.importer import load_trace_records
from endfield_pcap.history.records import load_combat_records
from endfield_pcap.trace.recording import TraceRecording
from parser_core.trace_jsonl import TraceHeader
from parser_core.unified import parse_overlay_battle_snapshot_text
from uploader_core.log_integrity import load_raw_log_integrity


def enemy(stamp):
    return dict(type='SC_OBJECT_ENTER_VIEW', timestamp_ms=stamp, objects=[dict(
        battle_inst_id=99, templateid='eny_0051_rodin',
        attrs=[dict(attr_type=3, value=200)])])


def record_jsonl(tmp_path, events, offset):
    header = TraceHeader('selected-context', 1, None, 'python', 'test', 'recorded', offset, {})
    archive_time = datetime.fromtimestamp(events[0]['timestamp_ms'] / 1000, timezone(timedelta(minutes=offset)))
    recording = TraceRecording(lambda _: None, header, log_directory=tmp_path / 'logs', archive_time=archive_time)
    path = recording.trace_file
    try:
        for index, event in enumerate(events):
            if index == len(events) // 2:
                recording.rotate_volume()
            recording.handle_event(event)
    finally:
        recording.close(finish_session=False)
    return path


def test_selected_jsonl_restores_precombat_stats_without_previous_hits(tmp_path):
    start = int(datetime(2026, 11, 5, 12, tzinfo=timezone.utc).timestamp() * 1000)
    events = []
    for shift, damage in ((0, 123), (60000, 456)):
        stamp = start + shift
        events.extend([raw_scene(stamp), enemy(stamp),
            dict(type='BattleOpModifyBattleState', timestamp_ms=stamp + 100, is_in_battle=True),
            raw_hit(stamp + 200, damage),
            dict(type='BattleOpModifyBattleState', timestamp_ms=stamp + 1000, is_in_battle=False)])
    source = record_jsonl(tmp_path, events, 480)
    rows = load_trace_records(source)
    assert len(rows) == 2
    for row, total in zip(rows, (123, 456)):
        snapshot = load_record_snapshot(row)
        assert snapshot['battle']['total_damage'] == total
        hits = [event for event in snapshot['timeline_events'] if event['event_type'] == 'damage']
        assert len(hits) == 1
        assert hits[0]['target_entity']['target_defense'] == 200
        assert hits[0]['target_entity']['target_defense_source'] == 'ENTITY_STATS.attr3'
        target = tmp_path / 'selected.log'
        export_battle_log(row, target)
        imported = parse_overlay_battle_snapshot_text(load_raw_log_integrity(str(target))['raw_content'])
        assert imported['battle']['total_damage'] == total
        imported_hit = next(event for event in imported['timeline_events'] if event['event_type'] == 'damage')
        assert imported_hit['target_entity']['target_defense'] == 200


@pytest.mark.parametrize('kind', ['jsonl', 'session'])
@pytest.mark.parametrize('offset', [480, -300])
@pytest.mark.parametrize('after_midnight', [False, True])
def test_selected_history_and_export_use_replay_day_across_midnight(tmp_path, kind, offset, after_midnight):
    zone = timezone(timedelta(minutes=offset))
    origin = (datetime(2026, 11, 6, 0, 0, 30, tzinfo=zone) if after_midnight
              else datetime(2026, 11, 5, 23, 59, 59, tzinfo=zone))
    stamp = int(origin.timestamp() * 1000)
    events = [raw_scene(stamp - 41000), enemy(stamp - 41000),
        dict(type='SC_GAME_MECHANICS_SYNC_CHALLENGE_START', timestamp_ms=stamp - 40000,
             game_id='old', challenge_start_ts='122'),
        raw_hit(stamp - 39000, 777),
        dict(type='SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', timestamp_ms=stamp - 38000,
             game_id='old', is_pass=True, pass_time=2000),
        dict(type='SC_GAME_MECHANICS_SYNC_CHALLENGE_START', timestamp_ms=stamp,
             game_id='test', challenge_start_ts='123'),
        raw_hit(stamp + 1100, 100),
        dict(type='SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', timestamp_ms=stamp + 2000,
             game_id='test', is_pass=True, pass_time=2000)]
    if kind == 'jsonl':
        source = record_jsonl(tmp_path, events, offset)
        rows = load_trace_records(source)
    else:
        source = tmp_path / 'session_20261105-midnight.ndjson'
        header = dict(type='session_volume', schema_version=1, recording_id='midnight', session_id='test',
            trace_recording_id='trace', volume=1, trace_volume=1, event_offset=0,
            timezone_offset_minutes=offset, previous_volume=None)
        source.write_text(''.join(json.dumps(event) + '\n' for event in [header, *events]), encoding='utf8')
        rows = sorted(load_combat_records(tmp_path), key=lambda row: row.record_index)
    assert '20261105' in source.name
    assert len(rows) == 2
    row = rows[-1]
    battle = load_record_snapshot(row)['battle']
    assert battle['total_damage'] == 100
    assert datetime.fromisoformat(battle['battle_start_at']) == origin
    assert datetime.fromisoformat(battle['battle_end_at']) == origin + timedelta(seconds=2)
    # Use the GUI's suggested path, including when the recording began yesterday.
    target = default_battle_export_path(row)
    export_battle_log(row, target)
    assert load_raw_log_integrity(str(target))['verified']
    imported, = load_trace_records(target)
    actual = load_record_snapshot(imported)['battle']
    assert actual['total_damage'] == battle['total_damage']
    assert actual['duration_ms'] == battle['duration_ms']
    for key in ('battle_start_at', 'battle_end_at'):
        assert datetime.fromisoformat(actual[key]).replace(tzinfo=None) == datetime.fromisoformat(battle[key]).replace(tzinfo=None)
