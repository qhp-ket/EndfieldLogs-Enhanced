"""Explicit recording boundaries preserve the live stream without retaining old hits."""
import asyncio
from datetime import datetime, timezone
from copy import deepcopy
import json
from types import SimpleNamespace

from app_test_support.runtime.service import service_factory
from test_trace_jsonl_recording import sample
from parser_core.trace_volumes import read_events, resolve_volumes
from endfield_pcap.history.index import HistoryIndex
from endfield_pcap.history.analysis import load_record_snapshot
from endfield_pcap.trace.recording_context import RecordingContext


def test_recording_context_retains_only_active_context_without_sibling_damage():
    context = RecordingContext()
    context.observe(dict(type='BattleOpTriggerAction', action=dict(
        damage_action=dict(details=[dict(value=-100)]),
        create_buff_action=dict(details=[dict(buff_inst_id=9, str_id='buff_test')]))))
    context.observe(dict(type='SC_SYNC_ATTR', battle_inst_id=1, attrs=[dict(attr_type='hp', value=100)]))
    context.observe(dict(type='SC_SYNC_ATTR', battle_inst_id=1, attrs=[dict(attr_type='attack', value=200)]))
    context.observe(dict(type='SC_SYNC_ATTR', battle_inst_id=1, attrs=[dict(attr_type='hp', value=90)]))
    rows = context.snapshot()
    assert len(rows) == 3
    assert rows[0]['action'] == dict(create_buff_action=dict(details=[dict(buff_inst_id=9, str_id='buff_test')]))
    assert {row['attrs'][0]['attr_type']: row['attrs'][0]['value'] for row in rows[1:]} == {'hp': 90, 'attack': 200}
    context.observe(dict(type='BattleOpFinishBuff', buff_inst_id=9))
    assert len(context.snapshot()) == 2
    context.clear()
    assert context.snapshot() == []


def test_recording_defaults_off_flushes_and_restarts_independent_files(service_factory, monkeypatch, tmp_path):
    steps, _ = sample(monkeypatch, tmp_path / 'resources')
    service = service_factory(trace_enabled=True, trace_format='jsonl', recording_on_start=False)
    service.snapshot_publisher._parser.min_reparse_interval_ms = 0
    service.summary_publisher._parser.min_reparse_interval_ms = 0
    day = int(datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp() * 1000)
    def emit(event):
        event = deepcopy(event)
        event['timestamp_ms'] += day
        service._handle_outbound_event(SimpleNamespace(as_dict=lambda: event))
    hit = json.loads(steps[6]['event_json'])
    hit['action']['damage_action']['details'][0].update(value=-123.5, cur_hp=10000)
    hit['timestamp_ms'] = 1000
    async def scenario():
        await service.snapshot_publisher.publish_pending()
        for step in steps[:2]:
            emit(json.loads(step['event_json']))
        emit(hit)
        first = await service.snapshot_publisher.publish_pending()
        assert first['snapshot']['battle']['total_damage'] == 124
        assert not service.recording and service.config.trace_file is None
        assert not list(service.config.log_dir.rglob('*'))
        raw, trace = service.set_recording(True)
        hit['timestamp_ms'] = 2000
        hit['seq_id'] += 1
        emit(hit)
        emit(dict(type='BattleOpAddBuff', timestamp_ms=2001, buff_inst_id=999,
                  str_id='buff_pending', src_inst_id=11, target_inst_id=333))
        service.set_recording(False)
        assert not service.recording and service.log_file is None
        assert service.set_recording(False) == (None, None)
        events = list(read_events(resolve_volumes(trace)))
        assert len([event for event in events if event.type == 'damage']) == 1
        assert any(event.type == 'buff_start' and event.data['buff_inst_id'] == '999' for event in events)
        saved = raw.read_bytes(), trace.read_bytes()
        hit['timestamp_ms'] = 3000
        hit['seq_id'] += 1
        emit(hit)
        assert (raw.read_bytes(), trace.read_bytes()) == saved
        next_raw, next_trace = service.set_recording(True)
        assert next_raw != raw and next_trace != trace
        chain = resolve_volumes(next_trace)
        assert chain.complete and len(chain.volumes) == 1 and chain.volumes[0].header.volume == 1
        assert chain.volumes[0].header.recording_id != resolve_volumes(trace).volumes[0].header.recording_id
        hit['timestamp_ms'] = 4000
        hit['seq_id'] += 1
        emit(hit)
        service.set_recording(False)
        final = await service.snapshot_publisher.publish_pending()
        assert final['stream_id'] == first['stream_id'] and final['source_generation'] == first['source_generation']
        assert final['snapshot']['battle']['total_damage'] == 496
        for path in (raw, next_raw):
            rows = HistoryIndex(tmp_path / ('index-' + path.stem)).records(path)
            assert len(rows) == 1 and load_record_snapshot(rows[0])['battle']['total_damage'] == 124
        for path in (trace, next_trace, raw, next_raw):
            moved = path.with_name('closed-' + path.name)
            path.rename(moved)
            moved.rename(path)
        await service.snapshot_publisher.close()
        await service.summary_publisher.close()
    try:
        asyncio.run(scenario())
    finally:
        service._close_trace_recording()
