"""JSONL 业务组录制、连续分卷及 uploader 导出的固定旧样本回归。"""
from dataclasses import replace
from datetime import datetime, timezone
import asyncio
import hashlib
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from parser_core.trace_jsonl import TraceEvent, TraceHeader, TraceJsonlWriter, serialize
from parser_core.trace_volumes import read_events, resolve_volumes
from endfield_pcap.history.export import export_trace_log
from endfield_pcap.trace.legacy import legacy_text
from endfield_pcap.trace.recording import TraceRecording
from endfield_pcap.analysis.live.publisher import SnapshotPublisher
from app_test_support.runtime.service import service_factory
from uploader_core.log_integrity import load_raw_log_integrity


FIXTURE = Path(__file__).resolve().parents[3] / '_internal/packages/parser_core/tests/fixtures/trace_recording_contract.json'
BODY_HASH = '67c66dbbe838934cda9512236bb8d17c03684391967c359e96d8dd11de2f89e7'


def assert_compatible(actual, expected):
    # V2 exports canonical formatting; the complete parsed business report must
    # still agree with the fixed old log, including equipment and BUFF evidence.
    from parser_core.parser import parse_raw_battle_log_text
    assert parse_raw_battle_log_text(actual.decode('utf8')) == parse_raw_battle_log_text(expected.decode('utf8'))


def sample(monkeypatch, root):
    row = json.loads(FIXTURE.read_text(encoding='utf8'))
    assert row['reference_sha256'] == 'e23935c6e40f3ae3ec0ddd2653fe82ee7b447bed9653315096438c3b22e8632e'
    config = json.loads(row['config_json'])
    table = root / 'data/local_tables/NumIdStrTable.json'
    table.parent.mkdir(parents=True)
    table.write_text(json.dumps(config['table']), encoding='utf8')
    monkeypatch.setattr('endfield_pcap.capture.resolver.bundle_root', lambda: root)
    monkeypatch.setattr('endfield_pcap.trace.formatting.bundle_root', lambda: root)
    expected = ''.join(row['expected'][-1]).encode('utf8')
    assert len(expected) == 6292 and hashlib.sha256(expected).hexdigest() == BODY_HASH
    return config['steps'], expected


def header():
    return TraceHeader('synthetic-recording-contract', 1, None, 'python', 'contract', 'Asia/Shanghai', 480, {})


def apply(recording, step):
    if 'begin' in step:
        recording.begin_capture_session(timestamp_ms=step['begin'])
    elif 'end' in step:
        recording.end_capture_session()
    else:
        recording.handle_event(json.loads(step['event_json']))


def test_jsonl_recording_rotates_without_reset_and_exports_fixed_legacy(monkeypatch, tmp_path):
    steps, expected = sample(monkeypatch, tmp_path / 'resources')
    batches = []
    original_header = header()
    with TraceRecording(batches.append, original_header, log_directory=tmp_path / 'logs',
                        archive_time=datetime(2026, 10, 31, 23, 59)) as recording:
        first = recording.trace_file
        original_header.resources['late-mutation'] = 'not-recorded'
        for step in steps[:len(steps) // 2]:
            apply(recording, step)
        visible = list(read_events(resolve_volumes(first)))
        assert visible == [event for batch in batches for event in batch]
        first_bytes = first.read_bytes()
        last = recording.rotate_volume(archive_time=datetime(2026, 11, 1))
        assert first.parent == last.parent
        assert recording.header.volume == 2 and recording.header.resources == {}
        for step in steps[len(steps) // 2:]:
            apply(recording, step)
        assert first.read_bytes() == first_bytes
    chain = resolve_volumes(last)
    assert chain.complete and len(chain.volumes) == 2
    events = list(read_events(chain))
    assert events == [event for batch in batches for event in batch]
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert recording.events_written == len(events)
    exported = legacy_text(chain).encode('utf8')
    assert_compatible(exported, expected)
    destination = tmp_path / 'uploader.log'
    proof = export_trace_log(last, destination)
    integrity = load_raw_log_integrity(str(destination))
    assert integrity['verified'] and integrity['raw_content'].encode('utf8') == exported
    assert proof['meta']['source_recording_id'] == original_header.recording_id
    assert proof['meta']['source_volumes'] == [first.name, last.name]
    assert abs(destination.stat().st_mtime_ns - last.stat().st_mtime_ns) <= 1000
    renamed = first.with_name('renamed.jsonl')
    first.rename(renamed)
    assert legacy_text(resolve_volumes(last)).encode('utf8') == exported
    with pytest.raises(ValueError, match='覆盖'):
        export_trace_log(last, renamed)
    outside = tmp_path / 'missing.jsonl'
    renamed.rename(outside)
    assert not resolve_volumes(last).complete
    refused = tmp_path / 'refused.log'
    with pytest.raises(ValueError, match='不完整'):
        export_trace_log(last, refused)
    assert not refused.exists()


def test_jsonl_recording_disk_failure_never_publishes_unrecorded_group(tmp_path, monkeypatch):
    batches = []
    recording = TraceRecording(batches.append, header(), log_directory=tmp_path)
    def fail():
        raise OSError('synthetic disk failure')
    monkeypatch.setattr(recording._writer, 'flush', fail)
    with pytest.raises(OSError, match='synthetic disk failure'):
        recording.begin_capture_session(timestamp_ms=0)
    assert batches == [] and recording.events_written == 0
    with pytest.raises(RuntimeError, match='failed'):
        recording.begin_capture_session(timestamp_ms=1)
    recording.close()


def test_jsonl_recording_pending_buff_survives_volume_rotation(monkeypatch, tmp_path):
    steps, _ = sample(monkeypatch, tmp_path / 'resources')
    batches = []
    with TraceRecording(batches.append, header(), log_directory=tmp_path / 'logs') as recording:
        apply(recording, steps[0])
        apply(recording, steps[1])
        before = recording.events_written
        recording.handle_event({'type': 'BattleOpAddBuff', 'session_id': 'synthetic', 'timestamp_ms': 1100,
                                'buff_inst_id': 71, 'str_id': 'buff_test', 'src_inst_id': 11, 'target_inst_id': 333})
        assert recording.events_written == before
        last = recording.rotate_volume()
        recording.handle_event({'type': 'BattleOpFinishBuff', 'session_id': 'synthetic', 'timestamp_ms': 1200,
                                'buff_inst_id': 71})
        continued = [event for event in read_events(resolve_volumes(last)) if event.sequence > before]
        assert [event.type for event in continued] == ['buff_start', 'buff_creation', 'buff_end']
        assert continued[0].captured_at_ms == 1100
        assert continued[-1].data['template'] == 'buff_test'


def test_jsonl_volumes_reject_gaps_and_incomplete_tail(tmp_path):
    first, second = tmp_path / 'part1.jsonl', tmp_path / 'part2.jsonl'
    event = TraceEvent(1, 0, 'battle_timer', {'phase': 'reset', 'source': 'CAPTURE_SESSION_START'}, {})
    with first.open('wb') as stream:
        TraceJsonlWriter(stream, header()).write(event)
    next_header = replace(header(), volume=2, previous_volume={'volume': 1, 'file': first.name})
    with second.open('wb') as stream:
        TraceJsonlWriter(stream, next_header).write(replace(event, sequence=3))
    destination = tmp_path / 'refused.log'
    with pytest.raises(ValueError, match='不连续'):
        export_trace_log(second, destination)
    assert not destination.exists()
    second.write_bytes(serialize(next_header) + serialize(replace(event, sequence=2))[:-1])
    with pytest.raises(ValueError, match='尚未完成'):
        export_trace_log(second, destination)
    assert not destination.exists()


@pytest.mark.parametrize('summary', [False, True])
@pytest.mark.parametrize('use_process', [False, True])
def test_event_publisher_suffix_reset_and_worker_recovery(monkeypatch, tmp_path, summary, use_process):
    steps, _ = sample(monkeypatch, tmp_path / 'resources')
    batches = []
    with TraceRecording(batches.append, header()) as recording:
        for step in steps:
            apply(recording, step)
    from parser_core.realtime.live_events import LiveEventOverlayBattleParser
    events = tuple(event for batch in batches for event in batch)
    expected = LiveEventOverlayBattleParser(timezone_offset_minutes=480,
        align_to_data_watermark=True, summary=summary)
    expected.feed_events(events)

    async def scenario():
        publisher = SnapshotPublisher(structured=True, use_process=use_process,
                                      summary=summary, timezone_offset_minutes=480)
        processes = []
        try:
            initial = await publisher.publish_pending()
            split = len(batches) // 2
            for batch in batches[:split]:
                publisher.feed_events(batch)
            await asyncio.wait_for(publisher.publish_pending(), 30)
            for batch in batches[split:]:
                publisher.feed_events(batch)
            final = await asyncio.wait_for(publisher.publish_pending(), 30)
            assert final['snapshot'] == expected.snapshot()
            assert final['type'] == ('analysis_summary' if summary else 'analysis_snapshot')
            assert await publisher.publish_pending() is None
            if use_process:
                worker = publisher._worker
                processes.append(worker.process)
                # Restart must replay retained events, including the last batch,
                # rather than require a fresh battle or silently lose its prefix.
                worker.process.terminate()
                await asyncio.to_thread(worker.process.join, 5)
                publisher.request_current()
                failed = await asyncio.wait_for(publisher.publish_pending(), 15)
                assert failed['snapshot'] is None and failed['error']
                recovered = await asyncio.wait_for(publisher.publish_pending(), 30)
                assert recovered['snapshot'] == final['snapshot']
                assert publisher._worker is not worker and worker.closed
                processes.append(publisher._worker.process)
            reset = TraceEvent(0, events[0].captured_at_ms, 'battle_timer',
                               dict(phase='reset', source='CAPTURE_SESSION_START'), {})
            publisher.feed_events((reset, *events))
            clear = await publisher.publish_pending()
            assert clear['snapshot'] is None and clear['sequence'] > final['sequence']
            next_battle = await asyncio.wait_for(publisher.publish_pending(), 30)
            assert next_battle['snapshot'] == expected.snapshot()
            assert next_battle['stream_id'] == initial['stream_id']
        finally:
            await publisher.close()
        assert all(not process.is_alive() for process in processes)
    asyncio.run(scenario())


@pytest.mark.parametrize('trace_enabled', [False, True])
@pytest.mark.parametrize('trace_format', [None, 'jsonl'])
def test_service_jsonl_records_and_publishes_same_business_events(service_factory, monkeypatch, tmp_path, trace_enabled, trace_format):
    from endfield_pcap.trace.legacy import legacy_lines
    steps, expected_body = sample(monkeypatch, tmp_path / 'resources')
    monkeypatch.setattr('endfield_pcap.trace.recording.make_recording_header', header)
    def forbidden(*args, **kwargs):
        raise AssertionError('Structured service must not emit or ingest legacy text')
    monkeypatch.setattr('parser_core.ingestion.stream._raw_battle_ingestion', forbidden)
    monkeypatch.setattr('endfield_pcap.trace.legacy.legacy_lines', forbidden)
    service = service_factory(trace_enabled=trace_enabled, trace_format=trace_format)
    assert service.config.trace_format == 'jsonl'
    recording = service._trace_recording
    async def scenario():
        await service.snapshot_publisher.publish_pending()
        await service.summary_publisher.publish_pending()
        for step in steps:
            apply(service.trace_bridge, step)
        full = (await service.snapshot_publisher.publish_pending())['snapshot']
        brief = (await service.summary_publisher.publish_pending())['snapshot']
        assert full['battle']['total_damage'] == brief['battle']['total_damage'] == 197967
        assert full['participants'] == brief['participants']
        service._close_trace_recording()
        await service.snapshot_publisher.close()
        await service.summary_publisher.close()
        return full
    try:
        full = asyncio.run(scenario())
        assert recording._closed
        if trace_enabled:
            path = service.config.trace_file
            assert path.suffix == '.jsonl' and path.name == 'trace_20261022-100000.jsonl'
            assert service.config.status_file == path.with_suffix('.jsonl.status.json')
            assert recording.events_written == len(tuple(read_events(resolve_volumes(path))))
            from endfield_pcap.history.importer import load_trace_records
            from endfield_pcap.history.analysis import load_record_snapshot
            history = load_record_snapshot(load_trace_records(path)[0])
            assert history['participants'] == full['participants']
            assert history['battle']['total_damage'] == full['battle']['total_damage']
            monkeypatch.setattr('endfield_pcap.trace.legacy.legacy_lines', legacy_lines)
            destination = tmp_path / 'uploader.log'
            export_trace_log(path, destination)
            assert_compatible(load_raw_log_integrity(str(destination))['raw_content'].encode('utf8'), expected_body)
        else:
            assert service.config.trace_file is None and service.status_file is None
            assert not list(tmp_path.rglob('*.jsonl'))
        assert not (tmp_path / 'trace/trace_20261022-100000.log').exists()
    finally:
        service._close_trace_recording()


@pytest.mark.parametrize('startup_fails', [False, True])
def test_service_jsonl_lifecycle_closes_recording(service_factory, monkeypatch, startup_fails):
    service = service_factory(trace_enabled=True, trace_format='jsonl')
    recording = service._trace_recording
    disk = service._disk_trace
    async def failed(*args, **kwargs):
        raise OSError('synthetic busy port')
    if startup_fails:
        monkeypatch.setattr('endfield_pcap.service.runtime.server.websockets.serve', failed)
        with pytest.raises(OSError, match='synthetic busy port'):
            asyncio.run(service.run())
    else:
        async def idle():
            await asyncio.Future()
        monkeypatch.setattr(service, '_game_running', lambda: False)
        for name in ('_process_monitor_loop', '_packet_loop', '_stats_loop'):
            monkeypatch.setattr(service, name, idle)
        async def scenario():
            task = asyncio.create_task(service.run())
            try:
                assert await asyncio.to_thread(service.wait_started, 5)
            finally:
                service.request_stop()
                await asyncio.wait_for(task, 5)
        asyncio.run(scenario())
    assert recording._closed and disk._closed and disk._stream.closed
    assert not service.recording and service.log_file is None
    assert service.capture_manager.stopped


def test_event_publisher_busy_reset_and_input_ownership():
    entered, release = threading.Event(), threading.Event()
    class Parser:
        def __init__(self):
            self.events = []
        def feed_events(self, events):
            self.events.extend(events)
        def snapshot(self):
            if self.events[0].data['value'] == 'old':
                entered.set()
                assert release.wait(5)
            return {'values': [event.data['value'] for event in self.events]}
    async def scenario():
        publisher = SnapshotPublisher(structured=True, parser_factory=Parser)
        await publisher.publish_pending()
        old = TraceEvent(1, 1000, 'diagnostic', {'value': 'old'}, {})
        publisher.feed_events((old,))
        old.data['value'] = 'mutated after feeding'
        task = asyncio.create_task(publisher.publish_pending())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            publisher.feed_events((TraceEvent(2, 2000, 'diagnostic', {'value': 'discarded'}, {}),
                TraceEvent(3, 2000, 'battle_timer', {'phase': 'reset'}, {}),
                TraceEvent(4, 2000, 'diagnostic', {'value': 'new'}, {})))
        finally:
            release.set()
            result = await task
        assert result is None
        assert (await publisher.publish_pending())['snapshot'] is None
        assert (await publisher.publish_pending())['snapshot'] == {'values': ['new']}
    asyncio.run(scenario())


def test_paired_service_rotation_history_export_and_input(service_factory, monkeypatch, tmp_path):
    from endfield_pcap.application.input_evidence import InputEvidenceController
    from endfield_pcap.application.settings import SettingsStore
    from endfield_pcap.history.analysis import load_record_snapshot
    from endfield_pcap.history.files import rename_log, relocate_record
    from endfield_pcap.history.index import HistoryIndex, record_key
    from endfield_pcap.history.records import load_combat_records
    from endfield_pcap.history.session_volumes import resolve_sessions, read_lines
    from endfield_pcap.inputlog.bindings import relocate_bindings
    from endfield_pcap.inputlog.history import discover, load_evidence, battle_start_wall_ms
    from endfield_pcap.inputlog.storage import InputWriter, companion
    from endfield_pcap.settings import load_app_config

    steps, expected_body = sample(monkeypatch, tmp_path / 'resources')
    monkeypatch.setattr('endfield_pcap.trace.recording.make_recording_header', header)
    service = service_factory(trace_enabled=True, trace_format='jsonl')
    session = SimpleNamespace(session_id='synthetic-continuous', status_snapshot=lambda: {})
    service.active_session = session
    service._open_log_file(session.session_id)
    first_session, first_trace = service.current_log_path, service.config.trace_file
    day = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
    split = len(steps) // 2
    async def scenario():
        await service.snapshot_publisher.publish_pending()
        await service.summary_publisher.publish_pending()
        before = None
        for index, step in enumerate(steps):
            if index == split:
                before = (await service.snapshot_publisher.publish_pending())['snapshot']
                previous_bytes = first_session.read_bytes(), first_trace.read_bytes()
                service.rotate_recording()
                assert service.active_session is session
                assert (first_session.read_bytes(), first_trace.read_bytes()) == previous_bytes
            if 'event_json' in step:
                event = json.loads(step['event_json'])
                event['timestamp_ms'] += day
                service._handle_outbound_event(SimpleNamespace(as_dict=lambda: event))
            elif 'end' in step:
                service.trace_bridge.end_capture_session()
        full = (await service.snapshot_publisher.publish_pending())['snapshot']
        summary = (await service.summary_publisher.publish_pending())['snapshot']
        assert before['battle']['total_damage'] == full['battle']['total_damage'] == 197967
        assert full['battle']['total_damage'] == summary['battle']['total_damage']
        await service.snapshot_publisher.close()
        await service.summary_publisher.close()
        return full
    try:
        full = asyncio.run(scenario())
    finally:
        service._close_trace_recording()
    last_session, last_trace = service.current_log_path, service.config.trace_file
    assert last_trace.parent == last_session.parent == first_session.parent
    chain = resolve_sessions(last_session)
    assert chain.complete and len(chain.volumes) == 2
    assert chain.volumes[1].header['event_offset'] == split
    assert chain.volumes[1].header['trace_volume'] == 2
    assert chain.volumes[1].header['trace_recording_id'] == header().recording_id
    assert len(list(read_lines(chain))) == len(steps) - 1

    index = HistoryIndex(tmp_path / 'index')
    rows = index.records(last_session)
    assert len(rows) == 1 and rows[0].file_path == first_session
    assert index.records(last_session) == rows
    assert len(load_combat_records(first_session.parent)) == 1
    record = rows[0]
    history = load_record_snapshot(record)
    assert history['participants'] == full['participants']
    assert history['battle']['total_damage'] == full['battle']['total_damage']
    destination = tmp_path / 'uploader.log'
    proof = export_trace_log(last_session, destination)
    # Moving this fixture by whole UTC days preserves time-only lines, while
    # the explicit captured Unix milliseconds must move with the observation.
    dated_body = expected_body.replace(b'captureMs=1300', f'captureMs={day + 1300}'.encode('ascii'))
    assert_compatible(load_raw_log_integrity(str(destination))['raw_content'].encode('utf8'), dated_body)
    assert proof['meta']['source_session_volumes'] == [first_session.name, last_session.name]
    with pytest.raises(ValueError, match='覆盖'):
        export_trace_log(last_session, first_trace)

    # Each part has its own source digest; neither is checked against volume one.
    start = battle_start_wall_ms(full['battle'])
    for number, trace in enumerate((first_trace, last_trace)):
        writer = InputWriter(companion(trace), trace=trace)
        try:
            for delta, phase in ((0, 'down'), (10, 'up')):
                at = start + 20 + number * 40 + delta
                writer.put('input', kind='key', device='keyboard', code='K:49', phase=phase,
                           wall_ns=round(at * 1e6), mono_ns=round(at * 1e6))
        finally:
            writer.close()
    paths = discover(last_session)
    assert paths == [companion(first_trace), companion(last_trace)]
    input_battle = dict(full['battle'], duration_ms=200)
    evidence = load_evidence(paths, last_session, input_battle)
    assert len(evidence['actions']) == 2
    assert evidence['warnings'].count('已校验 trace 关联') == 1

    store = SettingsStore(load_app_config(tmp_path / 'settings.json'), tmp_path / 'settings.json')
    controller = InputEvidenceController(full['battle'], store, loader=lambda *a, **k: evidence)
    controller.set_record(record)
    controller.set_alignment(offset_ms=5., start_override=None, manual_slots={0: 'test'})
    controller.close()
    reopened = InputEvidenceController(full['battle'], store, loader=lambda *a, **k: evidence)
    reopened.set_record(record)
    assert reopened.state.paths == tuple(paths) and reopened.state.offset_ms == 5.
    reopened.close()
    assert len(store.current.input_log_bindings[record_key(record)]['paths']) == 2

    original_bytes = first_session.read_bytes()
    renamed = rename_log(first_session, '连续记录')
    relocate_record(record, first_session, renamed)
    assert renamed.read_bytes() == original_bytes
    assert load_record_snapshot(record)['participants'] == history['participants']
    moved_trace = rename_log(first_trace, '对应输入')
    bindings = relocate_bindings(store.current.input_log_bindings, first_trace, moved_trace)
    assert next(iter(bindings.values()))['paths'][0].endswith('对应输入.input.jsonl')
    assert discover(last_session) == [companion(moved_trace), companion(last_trace)]

    missing = tmp_path / 'outside.ndjson'
    renamed.rename(missing)
    with pytest.raises(ValueError, match='不完整'):
        load_record_snapshot(record)
    with pytest.raises(ValueError, match='不完整'):
        export_trace_log(last_session, tmp_path / 'refused.log')


def test_paired_rotation_keeps_live_damage_and_analysis_generation(service_factory, monkeypatch, tmp_path):
    from copy import deepcopy
    from endfield_pcap.history.analysis import load_record_snapshot
    from endfield_pcap.history.index import HistoryIndex
    steps, _ = sample(monkeypatch, tmp_path / 'resources')
    monkeypatch.setattr('endfield_pcap.trace.recording.make_recording_header', header)
    service = service_factory(trace_enabled=True, trace_format='jsonl')
    service.active_session = SimpleNamespace(session_id='two-hits', status_snapshot=lambda: {})
    # The fixture uses an in-thread publisher without the real service's 1 s
    # scheduler. Disable its parser's independent throttle for explicit steps.
    service.snapshot_publisher._parser.min_reparse_interval_ms = 0
    service._open_log_file('two-hits')
    day = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp() * 1000)
    def emit(event):
        event = deepcopy(event)
        event['timestamp_ms'] += day
        service._handle_outbound_event(SimpleNamespace(as_dict=lambda: event))
    async def scenario():
        await service.snapshot_publisher.publish_pending()
        for step in steps[:2]:
            emit(json.loads(step['event_json']))
        hit = json.loads(steps[6]['event_json'])
        hit['action']['damage_action']['details'][0]['value'] = -123.5
        hit['action']['damage_action']['details'][0]['cur_hp'] = 1000
        hit['timestamp_ms'] = 1000
        emit(hit)
        first = await service.snapshot_publisher.publish_pending()
        assert first['snapshot']['battle']['total_damage'] == 124
        service.rotate_recording()
        hit['timestamp_ms'] = 2000
        hit['seq_id'] += 1
        hit['client_tick_tms'] += 1000
        hit['action']['damage_action']['details'][0]['cur_hp'] = 800
        emit(hit)
        last = await service.snapshot_publisher.publish_pending()
        assert last['stream_id'] == first['stream_id'] and last['sequence'] > first['sequence']
        assert last['snapshot']['battle']['total_damage'] == 248, (
            service.snapshot_publisher._parser.incremental_diagnostics, last['snapshot']['battle'])
        await service.snapshot_publisher.close()
        await service.summary_publisher.close()
    try:
        asyncio.run(scenario())
    finally:
        service._close_trace_recording()
    rows = HistoryIndex(tmp_path / 'index').records(service.current_log_path)
    assert len(rows) == 1 and rows[0].total_damage == 247
    assert load_record_snapshot(rows[0])['battle']['total_damage'] == 248


def test_input_loadout_ownership_reads_jsonl_across_volumes(tmp_path):
    from endfield_pcap.inputlog.history import loadout_history
    first, last = tmp_path / 'first.jsonl', tmp_path / 'last.jsonl'
    with first.open('wb') as stream:
        writer = TraceJsonlWriter(stream, header())
        writer.write(TraceEvent(1, 1000, 'loadout_group', {}, {}))
        writer.write(TraceEvent(2, 1000, 'loadout_slot', {'slot': 0, 'template': 'chr_old'}, {}))
    with last.open('wb') as stream:
        writer = TraceJsonlWriter(stream, replace(header(), volume=2,
            previous_volume={'volume': 1, 'file': first.name}))
        writer.write(TraceEvent(3, 2000, 'loadout_group', {}, {}))
        writer.write(TraceEvent(4, 2000, 'loadout_slot', {'slot': 0, 'template': 'chr_new'}, {}))
    assert loadout_history(last, 1500) == [(1000, None, None), (1000, 0, 'chr_old'),
                                          (2000, None, None), (2000, 0, 'chr_new')]
