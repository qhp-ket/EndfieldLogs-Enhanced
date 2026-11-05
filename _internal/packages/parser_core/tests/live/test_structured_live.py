"""Direct events retain legacy calculations without accumulated text input."""
from dataclasses import replace
from datetime import timedelta, timezone
import json
from pathlib import Path

import pytest

from endfield_pcap.trace.bridge import TraceBridge
from parser_core.realtime.events import EventBattleParser, LiveEventBatch
from parser_core.realtime.incremental import IncrementalBattleParser


FIXTURE = Path(__file__).resolve().parents[1] / 'fixtures/trace_recording_contract.json'


def observations(monkeypatch, tmp_path):
    case = json.loads(FIXTURE.read_text(encoding='utf8'))
    config = json.loads(case['config_json'])
    table = tmp_path / 'data/local_tables/NumIdStrTable.json'
    table.parent.mkdir(parents=True)
    table.write_text(json.dumps(config['table']), encoding='utf8')
    monkeypatch.setattr('endfield_pcap.capture.resolver.bundle_root', lambda: tmp_path)
    monkeypatch.setattr('endfield_pcap.trace.formatting.bundle_root', lambda: tmp_path)
    events = []
    bridge = TraceBridge(write_enabled=False, event_sink=events.append)
    for step in config['steps']:
        if 'begin' in step:
            bridge.begin_capture_session(timestamp_ms=step['begin'])
        elif 'end' in step:
            bridge.end_capture_session()
        else:
            bridge.handle_event(json.loads(step['event_json']))
    return events, case['expected'][-1]


@pytest.mark.parametrize('summary', [False, True])
def test_structured_live_matches_fixed_legacy_and_consumes_only_suffix(monkeypatch, tmp_path, summary):
    events, old_lines = observations(monkeypatch, tmp_path)
    legacy = IncrementalBattleParser(allow_empty=True).snapshot(old_lines, summary=summary)
    if legacy:
        # The old text has no zone; this fixture was recorded at UTC+8.
        # Reattach that source zone rather than the test runner's local zone.
        from datetime import datetime
        for key in ('battle_start_at', 'battle_end_at'):
            legacy['battle'][key] = datetime.fromisoformat(legacy['battle'][key]).replace(
                tzinfo=timezone(timedelta(minutes=480))).isoformat(timespec='milliseconds')
    def no_text(*args, **kwargs):
        raise AssertionError('Structured analysis must not render or parse legacy lines')
    monkeypatch.setattr('parser_core.ingestion.stream._raw_battle_ingestion', no_text)
    monkeypatch.setattr('endfield_pcap.trace.legacy.legacy_lines', no_text)
    parser = EventBattleParser(allow_empty=True, timezone_offset_minutes=480)
    split = len(events) // 2
    parser.snapshot_events(LiveEventBatch(1, 1, 0, tuple(events[:split])), summary=summary)
    result = parser.snapshot_events(LiveEventBatch(1, 2, split, tuple(events[split:])), summary=summary)
    assert result['battle']['total_damage'] == 197967
    assert result['battle'] == legacy['battle']
    assert result['participants'] == legacy['participants']
    quality_key = 'quality_summary' if summary else 'snapshot_quality'
    assert result[quality_key] == legacy[quality_key]
    if not summary:
        assert result['role_skill_stats'] == legacy['role_skill_stats']
        assert result['loadout'] == legacy['loadout']
    assert parser.diagnostics['ingested_lines'] == len(events)
    assert parser.text == '' and parser.lines == [] and parser.input_lines == []
    count = parser.report_builds
    result['participants'].clear()
    cached = parser.snapshot_events(LiveEventBatch(1, 2, len(events), ()), summary=summary)
    assert cached['participants'] == legacy['participants']
    assert parser.report_builds == count
    assert parser.diagnostics['trace_replays'] == 0


def test_structured_live_rejects_stale_watermarks_and_replays_only_explicit_generation(monkeypatch, tmp_path):
    events, _ = observations(monkeypatch, tmp_path)
    parser = EventBattleParser(allow_empty=True, timezone_offset_minutes=480)
    complete = parser.snapshot_events(LiveEventBatch(2, 1, 0, tuple(events)))
    with pytest.raises(ValueError, match='watermark'):
        parser.snapshot_events(LiveEventBatch(2, 2, 0, ()))
    with pytest.raises(ValueError, match='revision'):
        parser.snapshot_events(LiveEventBatch(2, 0, len(events), ()))
    with pytest.raises(ValueError, match='generation'):
        parser.snapshot_events(LiveEventBatch(1, 3, 0, ()))
    assert parser.snapshot_events(LiveEventBatch(3, 1, 0, tuple(events))) == complete
    assert parser.diagnostics['trace_replays'] == 0
    with pytest.raises(NotImplementedError):
        parser.snapshot_events(LiveEventBatch(3, 2, len(events), (replace(events[-1], type='unsupported'),)))
    with pytest.raises(ValueError, match='watermark'):
        parser.snapshot_events(LiveEventBatch(3, 3, len(events), ()))
    assert parser.snapshot_events(LiveEventBatch(3, 3, 0, tuple(events))) == complete


def test_structured_live_midnight_and_observer_keep_original_evidence(monkeypatch, tmp_path):
    events, _ = observations(monkeypatch, tmp_path)
    damage = next(event for event in events if event.type == 'damage')
    first = replace(damage, sequence=1, captured_at_ms=57_599_000)
    second = replace(damage, sequence=2, captured_at_ms=57_601_000)
    parser = EventBattleParser(allow_empty=True, timezone_offset_minutes=480)
    parser.snapshot_events(LiveEventBatch(1, 1, 0, (first, second)))
    assert [hit['ts_ms'] for hit in parser.state['hits']] == [86_399_000, 86_401_000]
    assert (first.captured_at_ms, second.captured_at_ms) == (57_599_000, 57_601_000)
    result = parser.snapshot_events(LiveEventBatch(1, 1, 2, ()), observer=(57_603_000, 4000))
    assert result['battle']['duration_ms'] == 4000
    assert parser.state['game_timer_elapsed_ms'] is None
    assert parser.state['official_timer_elapsed_ms'] is None
    assert parser.diagnostics['ingested_lines'] == 2


@pytest.mark.parametrize('summary', [False, True])
def test_event_live_session_uses_shared_boundaries_and_only_appended_input(monkeypatch, tmp_path, summary):
    from datetime import date
    from parser_core.realtime.live import LiveOverlayBattleParser
    from parser_core.realtime.live_events import LiveEventOverlayBattleParser
    events, old_lines = observations(monkeypatch, tmp_path)
    old = LiveOverlayBattleParser(align_to_data_watermark=True, summary=summary)
    old.feed_lines(old_lines)
    expected = old.snapshot()
    def forbidden(*args, **kwargs):
        raise AssertionError('Event live session must not use legacy text')
    monkeypatch.setattr('parser_core.ingestion.stream._raw_battle_ingestion', forbidden)
    monkeypatch.setattr('endfield_pcap.trace.legacy.legacy_lines', forbidden)
    parser = LiveEventOverlayBattleParser(timezone_offset_minutes=480, reference_date=date.today(),
                                         align_to_data_watermark=True, summary=summary)
    split = len(events) // 2
    parser.feed_events(events[:split])
    parser.snapshot()
    consumed = parser.incremental_diagnostics['ingested_lines']
    parser.feed_events(events[split:])
    result = parser.snapshot()
    assert result['participants'] == expected['participants']
    for key in ('total_damage', 'duration_ms', 'time_source', 'timer_integrity_ok'):
        assert result['battle'][key] == expected['battle'][key]
    assert parser.incremental_diagnostics['ingested_lines'] == consumed + len(events[split:])
    builds = parser.incremental_diagnostics['report_builds']
    assert parser.snapshot() is result
    assert parser.incremental_diagnostics['report_builds'] == builds
    assert parser._lines == [] and parser._engine.text == ''
    assert parser.incremental_diagnostics['event_recoveries'] == 0


def test_event_live_official_clock_phase_end_heartbeat_and_new_battle(monkeypatch, tmp_path):
    from parser_core.trace_jsonl import TraceEvent
    from parser_core.realtime.live_events import LiveEventOverlayBattleParser
    events, _ = observations(monkeypatch, tmp_path)
    damage = next(event for event in events if event.type == 'damage')
    def timer(kind, phase, stamp, **fields):
        return TraceEvent(1, stamp, kind, dict(phase=phase, source='synthetic', **fields), {})
    parser = LiveEventOverlayBattleParser(timezone_offset_minutes=480, align_to_data_watermark=True, summary=True)
    start = timer('official_timer', 'start', 1000, game_id='test', challenge_start_ts=1000)
    parser.feed_events((start, replace(damage, captured_at_ms=2000)))
    assert parser.snapshot()['battle']['duration_ms'] == 1000
    parser.feed_events((timer('battle_timer', 'end', 3000, elapsed_ms=2000, sane=1),
                        replace(damage, captured_at_ms=4000)))
    assert parser.snapshot()['battle']['duration_ms'] == 3000
    assert parser.snapshot(now_ms=5000)['battle']['duration_ms'] == 4000
    assert parser.snapshot()['battle']['duration_ms'] == 3000
    parser.feed_events((timer('official_timer', 'end', 5000, game_id='test', is_pass=True, pass_time=4000),))
    ended = parser.snapshot()
    revision = parser.source_revision
    parser.feed_events((TraceEvent(1, 6000, 'clock_tick', dict(source='CS_BATTLE_OP', tick_ms=6000), {}),))
    assert parser.snapshot() is ended and parser.source_revision == revision
    parser.feed_events((timer('official_timer', 'start', 7000, game_id='next', challenge_start_ts=7000),
                        replace(damage, captured_at_ms=8000)))
    assert parser.snapshot()['battle']['total_damage'] == 197967
    assert parser.incremental_diagnostics['event_recoveries'] == 0


def test_event_live_recovers_once_from_frozen_mutation_and_detaches_input(monkeypatch, tmp_path):
    from parser_core.realtime.live_events import LiveEventOverlayBattleParser
    from parser_core.realtime.live_frozen import FrozenMutation
    events, _ = observations(monkeypatch, tmp_path)
    parser = LiveEventOverlayBattleParser(timezone_offset_minutes=480, align_to_data_watermark=True, summary=True)
    parser.feed_events(events)
    expected = parser.snapshot()
    damage = next(event for event in events if event.type == 'damage')
    parser.feed_event(replace(damage, sequence=damage.sequence + 100, captured_at_ms=damage.captured_at_ms + 1))
    def fail(*args, **kwargs):
        raise FrozenMutation('synthetic frozen mutation')
    monkeypatch.setattr(parser._engine, 'snapshot_events', fail)
    damage.data.clear()
    recovered = parser.snapshot()
    assert recovered['battle']['total_damage'] == expected['battle']['total_damage']
    assert parser._engine.freeze_disabled
    assert parser.incremental_diagnostics['event_recoveries'] == 1
    assert parser.snapshot() is recovered
