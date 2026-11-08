"""The wire fixture is handwritten and shared with the C# roundtrip verifier."""
from dataclasses import replace
from io import BytesIO
import json
import math
from pathlib import Path

import pytest

from parser_core.trace_jsonl import (
    TraceEvent, TraceJsonlReader, TraceJsonlWriter, from_object, parse, serialize, to_object,
)


def records():
    fixture = Path(__file__).parents[1] / "fixtures/trace_jsonl_contract.json"
    return [from_object(row, header=i == 0) for i, row in enumerate(json.loads(fixture.read_text(encoding="utf-8"))["records"])]


def test_chunked_jsonl_roundtrip_preserves_presence_identity_and_late_time():
    expected = records()
    output = BytesIO()
    writer = TraceJsonlWriter(output, expected[0])
    for event in expected[1:]:
        writer.write(event)
    writer.flush()
    wire = output.getvalue()
    assert not wire.startswith(b"\xef\xbb\xbf") and b"\r" not in wire
    reader = TraceJsonlReader()
    actual = []
    for byte in wire[:-1]:
        actual.extend(reader.feed(bytes([byte])))
    assert len(actual) == 2 and reader.pending_bytes
    actual.extend(reader.feed(wire[-1:]))
    assert [to_object(row) for row in actual] == [to_object(row) for row in expected]
    assert reader.pending_bytes == 0
    assert actual[1].source["owner_id"] == "18446744073709551615"
    assert actual[2].captured_at_ms < actual[1].captured_at_ms
    assert actual[2].data["unparsed"]["counter"] == 123456789012345678901234567890
    assert b'"rate":-0.0' in serialize(actual[2])
    evidence = actual[1].data["evidence"]
    assert evidence == {"report_present": False, "modifiers": [], "attributes": {}, "debug": None}
    assert "client_tick_ms" not in to_object(actual[2]) and actual[1].client_tick_ms == 0


def test_volume_does_not_require_sequence_or_time_reset():
    header, first, second = records()
    volume = replace(header, volume=2, previous_volume={"volume": 1, "file": "trace_part1.jsonl"})
    event = replace(first, sequence=8)
    output = BytesIO()
    writer = TraceJsonlWriter(output, volume)
    writer.write(event)
    reader = TraceJsonlReader()
    actual = reader.feed(output.getvalue())
    assert actual == [volume, event]
    with pytest.raises(ValueError, match="continuous"):
        writer.write(replace(second, sequence=10))
    with pytest.raises(ValueError, match="continuous"):
        reader.feed(serialize(replace(second, sequence=8)))


@pytest.mark.parametrize("patch", [{"seq": True}, {"seq": 0}, {"seq": 2**63}, {"source": {"owner_id": 11}},
                                  {"source": {"owner_id": ""}}, {"source": {"owner_id": "unknown"}}])
def test_invalid_envelopes_are_not_accepted_as_valid_events(patch):
    value = to_object(records()[1]) | patch
    with pytest.raises(ValueError):
        from_object(value, header=False)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "1e999"])
def test_non_finite_numeric_evidence_requires_explicit_status(number):
    line = ('{"seq":1,"captured_at_ms":0,"source":{},"type":"damage","data":{"value":' + number + '}}').encode()
    with pytest.raises(ValueError):
        parse(line, header=False)


def test_unknown_event_types_keep_evidence_and_invalid_versions_fail():
    future = TraceEvent(1, 0, "future_observation", {"evidence": []}, {})
    assert parse(serialize(future), header=False) == future
    value = to_object(records()[0]) | {"version": 3}
    with pytest.raises(ValueError, match="Unsupported"):
        from_object(value, header=True)


def test_instance_projection_restores_original_scalar_types_and_key_order_after_disk():
    from parser_core.trace_values import project_value, restore_value
    original = {'modifier_args': {'attacker_modifiers': [
        {'index': 0, 'buff_inst_id': 18446744073709551615, 'debug_args': {'z': -0.0, 'a': [1, None]}},
        {'buff_inst_id': '00099'}, {'buff_inst_id': -3}, {'buff_inst_id': 'unknown'},
        {'buff_inst_id': 1.5}, {'buff_inst_id': True}, {'buff_inst_id': None}], 'defender_modifiers': []}}
    projected, layout = project_value(original)
    handles = projected['modifier_args']['attacker_modifiers']
    assert [row['buff_inst_id'] for row in handles] == ['18446744073709551615', '99', None, None, '1', '1', None]
    event = TraceEvent(1, 0, 'damage', {'value': projected, 'layout': layout}, {})
    saved = parse(serialize(event), header=False).data
    restored = restore_value(saved['value'], saved['layout'])
    assert restored == original
    restored_handle = restored['modifier_args']['attacker_modifiers'][0]
    assert list(restored_handle) == ['index', 'buff_inst_id', 'debug_args']
    assert list(restored_handle['debug_args']) == ['z', 'a']
    assert math.copysign(1, restored_handle['debug_args']['z']) == -1
    assert type(restored['modifier_args']['attacker_modifiers'][4]['buff_inst_id']) is float
    assert type(restored['modifier_args']['attacker_modifiers'][5]['buff_inst_id']) is bool
    assert original['modifier_args']['attacker_modifiers'][0]['buff_inst_id'] == 18446744073709551615


@pytest.mark.parametrize('value,status', [(float('nan'), 'nan'), (float('inf'), 'positive_infinity'),
                                         (-float('inf'), 'negative_infinity')])
def test_projected_nonfinite_numbers_have_explicit_serializable_status(value, status):
    from parser_core.trace_values import project_value, restore_value
    projected, layout = project_value({'debug': [value]})
    assert projected == {'debug': [{'number_status': status}]}
    saved = parse(serialize(TraceEvent(1, 0, 'future_observation', {'value': projected, 'layout': layout}, {})), header=False).data
    restored = restore_value(saved['value'], saved['layout'])['debug'][0]
    assert math.isnan(restored) if math.isnan(value) else restored == value


def test_legacy_order_cannot_silently_omit_or_duplicate_evidence_fields():
    from parser_core.trace_values import restore_value
    for keys in (['a'], ['a', 'a'], ['a', 'other']):
        with pytest.raises(ValueError, match='key order'):
            restore_value({'a': 1, 'b': 2}, {'keys': keys})
