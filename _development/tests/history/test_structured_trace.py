"""Actual recording, event-only history, volume invalidation and file operations."""
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from endfield_pcap.history.analysis import load_record_snapshot
from endfield_pcap.history.files import rename_log, relocate_record
from endfield_pcap.history.importer import load_trace_records
from endfield_pcap.history.index import HistoryIndex
from endfield_pcap.history.structured import trace_source_signature
from endfield_pcap.trace.recording import TraceRecording
from parser_core.battle_splitter.events import split_event_battles
from parser_core.battle_splitter.trace import split_trace_battles
from parser_core.trace_jsonl import TraceHeader, TraceJsonlWriter, serialize
from parser_core.trace_volumes import read_events, resolve_volumes


@pytest.fixture
def recorded(tmp_path, monkeypatch):
    fixture = Path(__file__).resolve().parents[3] / '_internal/packages/parser_core/tests/fixtures/trace_recording_contract.json'
    sample = json.loads(fixture.read_text(encoding='utf8'))
    config = json.loads(sample['config_json'])
    root = tmp_path / 'resources'
    table = root / 'data/local_tables/NumIdStrTable.json'
    table.parent.mkdir(parents=True)
    table.write_text(json.dumps(config['table']), encoding='utf8')
    monkeypatch.setattr('endfield_pcap.capture.resolver.bundle_root', lambda: root)
    monkeypatch.setattr('endfield_pcap.trace.formatting.bundle_root', lambda: root)
    header = TraceHeader('synthetic-history', 1, None, 'python', 'contract', 'Asia/Shanghai', 480, {})
    day = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
    with TraceRecording(lambda batch: None, header, log_directory=tmp_path / 'logs') as recording:
        first = recording.trace_file
        for index, step in enumerate(config['steps']):
            if index == len(config['steps']) // 2:
                last = recording.rotate_volume()
            if 'begin' in step:
                recording.begin_capture_session(timestamp_ms=day + step['begin'])
            elif 'end' in step:
                recording.end_capture_session()
            else:
                event = json.loads(step['event_json'])
                if 'timestamp_ms' in event:
                    event['timestamp_ms'] += day
                recording.handle_event(event)
    return first, last, ''.join(sample['expected'][-1])


def test_jsonl_history_indexes_without_analysis_then_loads_direct_events(recorded, tmp_path, monkeypatch):
    first, last, legacy = recorded
    old_path = tmp_path / 'trace_20261101.log'
    old_path.write_text(legacy, encoding='utf8')
    old = load_record_snapshot(load_trace_records(old_path)[0])
    originals = [path.read_bytes() for path in (first, last)]
    index = HistoryIndex(tmp_path / 'index')
    def forbidden(*args, **kwargs):
        raise AssertionError('JSONL history must not use legacy export or ingestion')
    monkeypatch.setattr('endfield_pcap.trace.legacy.legacy_lines', forbidden)
    monkeypatch.setattr('parser_core.ingestion.stream._raw_battle_ingestion', forbidden)
    from parser_core.realtime.events import EventBattleParser
    calculate = EventBattleParser.snapshot_events
    monkeypatch.setattr(EventBattleParser, 'snapshot_events', forbidden)
    rows = index.records(last, trace=True)
    assert len(rows) == 1 and not rows[0].analysis_loaded and not rows[0].snapshot
    monkeypatch.setattr('endfield_pcap.history.index.load_trace_records', forbidden)
    cached = index.records(last, trace=True)
    assert cached == rows
    monkeypatch.setattr(EventBattleParser, 'snapshot_events', calculate)
    result = load_record_snapshot(cached[0])
    assert result['battle']['total_damage'] == old['battle']['total_damage'] == 197967
    assert result['participants'] == old['participants']
    assert result['role_skill_stats'] == old['role_skill_stats']
    assert result['loadout'] == old['loadout']
    assert result['snapshot_quality'] == old['snapshot_quality']
    assert result['battle']['source_file_name'] == first.name
    result['participants'].clear()
    assert load_record_snapshot(cached[0])['participants'] == old['participants']
    assert [path.read_bytes() for path in (first, last)] == originals


def test_jsonl_history_detects_changed_other_volume_and_missing_chain(recorded, tmp_path, monkeypatch):
    first, last, _ = recorded
    index = HistoryIndex(tmp_path / 'index')
    row = index.records(first, trace=True)[0]
    load_record_snapshot(row)
    before = trace_source_signature(first)
    event = list(read_events(resolve_volumes(first)))[-1]
    with last.open('ab') as stream:
        stream.write(serialize(replace(event, sequence=event.sequence + 1)))
    assert trace_source_signature(first) != before
    with pytest.raises(ValueError, match='已变化'):
        load_record_snapshot(row)
    # A changed sibling must invalidate the disposable index even though the selected file is unchanged.
    rebuilt = index.records(first, trace=True)
    assert rebuilt[0].source_volumes != row.source_volumes
    last.rename(tmp_path / 'missing.jsonl')
    with pytest.raises(ValueError, match='已变化|不完整'):
        load_record_snapshot(rebuilt[0])


def test_jsonl_history_renames_volume_without_changing_evidence(recorded):
    first, last, _ = recorded
    row = load_trace_records(last)[0]
    expected = load_record_snapshot(row)
    before = trace_source_signature(last)
    new = rename_log(first, '自定义名称')
    relocate_record(row, first, new)
    assert trace_source_signature(last) != before
    expected['battle']['source_file_name'] = new.name
    assert load_record_snapshot(row) == expected
    row.snapshot = {}
    assert load_record_snapshot(row) == expected


def test_jsonl_splitter_preserves_existing_battle_boundaries(recorded):
    first, _, legacy = recorded
    events = tuple(read_events(resolve_volumes(first)))
    old = split_trace_battles(legacy)
    bounds = split_event_battles(iter(events), timezone_offset_minutes=480)
    assert [(row['battle_index'], row['first_hit_hint'], row['last_hit_hint']) for row in bounds] == [
        (row['battle_index'], row['first_hit_hint'], row['last_hit_hint']) for row in old]
    doubled = events + tuple(replace(event, sequence=len(events) + event.sequence,
                                    captured_at_ms=event.captured_at_ms + 60_000) for event in events)
    bounds = split_event_battles(iter(doubled), timezone_offset_minutes=480)
    assert len(bounds) == 2
    assert bounds[0]['end_line_index'] <= bounds[1]['start_line_index']


def test_selected_jsonl_export_keeps_cross_volume_evidence_and_excludes_other_battle(recorded, tmp_path):
    from endfield_pcap.history.export import export_battle_log
    from uploader_core.log_integrity import load_raw_log_integrity
    from parser_core.unified import parse_overlay_battle_snapshot_text
    first, _, _ = recorded
    events = tuple(read_events(resolve_volumes(first)))
    target = tmp_path / 'cross-volume.log'
    row = load_trace_records(first)[0]
    export_battle_log(row, target)
    content = load_raw_log_integrity(str(target))
    assert content['verified']
    assert parse_overlay_battle_snapshot_text(content['raw_content'])['battle']['total_damage'] == 197967
    path = tmp_path / 'two-battles.jsonl'
    header = TraceHeader('two-battles', 1, None, 'python', 'test', 'Asia/Shanghai', 480, {})
    with path.open('wb') as stream:
        writer = TraceJsonlWriter(stream, header)
        for event in events:
            writer.write(event)
        for event in events:
            writer.write(replace(event, sequence=len(events) + event.sequence, captured_at_ms=event.captured_at_ms + 60000))
    rows = load_trace_records(path)
    assert len(rows) == 2
    for row in rows:
        export_battle_log(row, target)
        content = load_raw_log_integrity(str(target))
        assert len(split_trace_battles(content['raw_content'])) == 1
        actual = parse_overlay_battle_snapshot_text(content['raw_content'])
        expected = load_record_snapshot(row)
        assert actual['battle']['total_damage'] == expected['battle']['total_damage'] == 197967
        assert actual['loadout'] == expected['loadout']
        assert actual['role_skill_stats'] == expected['role_skill_stats']


@pytest.mark.parametrize('offset', [480, -300])
def test_jsonl_history_uses_recorded_timezone_and_midnight_date(recorded, tmp_path, offset):
    from datetime import timedelta
    first, _, _ = recorded
    damage = next(event for event in read_events(resolve_volumes(first)) if event.type == 'damage')
    zone = timezone(timedelta(minutes=offset))
    stamp = int(datetime(2026, 11, 1, 23, 59, 59, tzinfo=zone).timestamp() * 1000)
    path = tmp_path / f'midnight-{offset}.jsonl'
    header = TraceHeader(f'midnight-{offset}', 1, None, 'python', 'contract', 'recorded', offset, {})
    with path.open('wb') as stream:
        writer = TraceJsonlWriter(stream, header)
        writer.write(replace(damage, sequence=1, captured_at_ms=stamp))
        writer.write(replace(damage, sequence=2, captured_at_ms=stamp + 2000))
    row = load_trace_records(path)[0]
    result = load_record_snapshot(row)
    start = datetime.fromisoformat(result['battle']['battle_start_at'])
    end = datetime.fromisoformat(result['battle']['battle_end_at'])
    assert int(start.timestamp() * 1000) == row.started_at_ms == stamp
    assert int(end.timestamp() * 1000) == stamp + 2000
    assert start.utcoffset() == end.utcoffset() == timedelta(minutes=offset)
    assert (start.day, end.day) == (1, 2)


def test_jsonl_history_controller_imports_volumes_once_and_removes_only_listing(recorded, tmp_path):
    import time
    from endfield_pcap.application.capture_state import CaptureWritingState, WritingKind
    from endfield_pcap.application.history import HistoryController
    from endfield_pcap.application.settings import SettingsStore
    from endfield_pcap.history.index import record_key
    from endfield_pcap.settings import load_app_config
    first, last, _ = recorded
    originals = [path.read_bytes() for path in (first, last)]
    path = tmp_path / 'settings.json'
    controller = HistoryController(SettingsStore(load_app_config(path), path),
        lambda: CaptureWritingState(WritingKind.IDLE))
    try:
        controller.import_files([first, last])
        deadline = time.monotonic() + 5
        while controller.import_pending:
            controller.drain()
            assert time.monotonic() < deadline
            time.sleep(.002)
        assert len(controller.records) == 1
        key = record_key(controller.records[0])
        controller.remove([key])
        assert controller.records == []
        assert [source.read_bytes() for source in (first, last)] == originals
    finally:
        controller.close()
