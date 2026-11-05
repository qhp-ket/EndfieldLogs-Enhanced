"""历史字段经结构化入口保留旧解析结果、数值表示与诊断权限。"""
import json
from pathlib import Path

from parser_core.ingestion.historical_wire import historical_data
from parser_core.ingestion.structured import consume_trace_event
from parser_core.ingestion.hits import consume_hit_and_buff_lifecycle
from parser_core.ingestion.packet_evidence import consume_packet_evidence
from parser_core.trace_jsonl import TraceEvent, parse, serialize
from parser_core.trace_values import project_value
from test_structured_entity import state


CONTRACT = Path(__file__).resolve().parents[1] / 'fixtures/trace_historical_contract.json'


def events():
    fixture = json.loads(CONTRACT.read_text(encoding='utf8'))
    for index, row in enumerate(fixture['observations'], 1):
        kind, raw = historical_data(row['line'])
        assert kind == row['type']
        data, layout = project_value(raw)
        data['legacy_layout'] = layout
        yield row['line'] + '\n', parse(serialize(TraceEvent(index, fixture['captured_at_ms'], kind, data, {})), header=False)


def test_historical_fields_match_legacy_state_and_pending_boundaries():
    fixture = json.loads(CONTRACT.read_text(encoding='utf8'))
    old, typed = state(), state()
    for stream in (old, typed):
        for index, line in enumerate(fixture['setup'], 1):
            consume_hit_and_buff_lifecycle(stream, line, index, fixture['captured_at_ms'])
    assert typed.pending_buff_record is not None
    for index, (line, event) in enumerate(events(), 3):
        consume_trace_event(typed, event, index)
        if not consume_packet_evidence(old, line, index, event.captured_at_ms):
            consume_hit_and_buff_lifecycle(old, line, index, event.captured_at_ms)
        assert typed.hits == old.hits
        assert typed.baseline_by_character == old.baseline_by_character
        assert typed.pending_attr_mods == old.pending_attr_mods
        assert typed.pending_buff_record == old.pending_buff_record
    assert typed.hits[0]['dpd_raw']['calc'] == float('1.2345678901234567e+02')
    assert typed.hits[0]['baseline'][1] == float('1.2345678901234567')
    assert len(typed.hits) == 1 and typed.pending_buff_record is None
    assert typed.trace_identity_inference_seen
    assert not typed.party_actor_ids and not typed.squad_actor_keys
    assert typed.timer_observed_times == {8: fixture['captured_at_ms']}
    assert typed.game_timer_elapsed_ms is None and typed.official_timer_elapsed_ms is None


def test_historical_export_retains_duplicate_tokens_quotes_and_precision():
    # The test supplies fixed old rows; neither exporter creates its own expected text.
    from endfield_pcap.trace.legacy_historical import historical_legacy_lines
    from endfield_pcap.trace.legacy_identity import identity_legacy_lines
    from endfield_pcap.trace.legacy_clock import clock_legacy_lines
    for expected, event in events():
        exporter = (identity_legacy_lines if event.type == 'identity_inference' else
                    clock_legacy_lines if event.type == 'clock_tick' else historical_legacy_lines)
        assert ''.join(exporter(event, timezone_offset_minutes=0)) == expected
    modifier = list(events())[3][1]
    values = [row['value'] for row in modifier.data['observation']['fields'] if row['name'] == 'val']
    assert values == ['0.1', '0.25']


def test_typed_historical_consumption_does_not_reparse_legacy_rows(monkeypatch):
    prepared = list(events())
    def no_text(*args, **kwargs):
        raise AssertionError('Typed historical consumption must not parse a legacy row')
    monkeypatch.setattr('parser_core.ingestion.historical_wire._extract_fields', no_text)
    monkeypatch.setattr('parser_core.ingestion.fields._parse_dpd_raw_line', no_text)
    monkeypatch.setattr('parser_core.ingestion.fields._parse_baseline_line', no_text)
    stream = state()
    for index, (_, event) in enumerate(prepared, 1):
        consume_trace_event(stream, event, index)
    assert not stream.hits and stream.trace_identity_inference_seen


def test_historical_diagnostics_end_pending_blackboard_window():
    fixture = json.loads(CONTRACT.read_text(encoding='utf8'))
    for line, event in events():
        if event.type not in ('identity_inference', 'clock_tick'):
            continue
        old, typed = state(), state()
        for stream in (old, typed):
            consume_hit_and_buff_lifecycle(stream, fixture['setup'][1], 1, event.captured_at_ms)
        consume_hit_and_buff_lifecycle(old, line, 2, event.captured_at_ms)
        consume_trace_event(typed, event, 2)
        assert old.pending_buff_record is None
        assert typed.pending_buff_record is None, event.type
