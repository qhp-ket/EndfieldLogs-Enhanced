from app_test_support.paths import ROOT
import json
import os
import pytest
from endfield_pcap.history.export import export_trace_log
from uploader_core.log_integrity import load_raw_log_integrity
from uploader_core.upload_document import build_raw_log_upload_document
from parser_core.unified import parse_overlay_battle_snapshot_text


@pytest.mark.parametrize("ending", ["\n", "\r\n", ""])
def test_export_preserves_trace_and_capture_date_with_valid_official_proof(tmp_path, ending):
    fixture = ROOT / "_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log"
    text = fixture.read_text(encoding="utf-8")
    if ending == "\r\n":
        text = text.replace("\n", "\r\n")
    elif not ending:
        text = text.rstrip("\n")
    source, target = tmp_path / "trace_original.log", tmp_path / "trace_export_upload.log"
    source.write_bytes(text.encode("utf-8"))
    os.utime(source, (1_780_000_000, 1_780_000_000))
    assert load_raw_log_integrity(str(source))["issues"] == ["missing integrity proof"]
    proof = export_trace_log(source, target)
    integrity = load_raw_log_integrity(str(target))
    assert integrity["verified"] and integrity["proof_source"] == "embedded"
    assert integrity["raw_content"] == text
    assert source.read_bytes() == text.encode("utf-8")
    assert target.stat().st_mtime == source.stat().st_mtime
    assert parse_overlay_battle_snapshot_text(integrity["raw_content"]) == parse_overlay_battle_snapshot_text(text)
    document = build_raw_log_upload_document(str(target))
    assert document["content"] == text and document["proof"] == proof
    assert document["integrity_gate"] == {
        "tamper_suspected": False, "integrity_proof_present": True, "reasons": []}
    assert not list(tmp_path.glob("*.tmp"))


def test_export_cannot_overwrite_trace_or_reseal_corrupted_proof(tmp_path):
    fixture = ROOT / "_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log"
    target = tmp_path / "export.log"
    with pytest.raises(ValueError, match="另存"):
        export_trace_log(fixture, fixture)
    export_trace_log(fixture, target)
    target.write_bytes(target.read_bytes().replace(b"hit=", b"hit=9", 1))
    with pytest.raises(ValueError, match="完整性校验失败"):
        export_trace_log(target, tmp_path / "resealed.log")
    assert not (tmp_path / "resealed.log").exists()


def test_export_rejects_diagnostic_ndjson(tmp_path):
    source = tmp_path / "session.ndjson"
    source.write_text(json.dumps({"type": "BattleOpTriggerAction"}), encoding="utf-8")
    with pytest.raises(ValueError, match="session_"):
        export_trace_log(source, tmp_path / "wrong.log")


def test_selected_legacy_export_contains_one_complete_battle(tmp_path):
    from app_test_support.scenarios.trace import two_battles
    from endfield_pcap.history.importer import load_trace_records
    from endfield_pcap.history.analysis import load_record_snapshot
    from endfield_pcap.history.export import export_battle_log
    from parser_core.battle_splitter import split_trace_battles
    source = tmp_path / 'trace_20261105.log'
    source.write_text(two_battles(), encoding='utf8')
    original = source.read_bytes()
    rows = load_trace_records(source)
    assert len(rows) == 2
    for row in rows:
        target = tmp_path / f'battle-{row.record_index}.log'
        export_battle_log(row, target)
        integrity = load_raw_log_integrity(str(target))
        segments = split_trace_battles(integrity['raw_content'])
        assert integrity['verified'] and len(segments) == 1
        expected = load_record_snapshot(row)
        actual = parse_overlay_battle_snapshot_text(integrity['raw_content'])
        for field in ('participants', 'loadout', 'role_skill_stats', 'snapshot_quality'):
            assert actual[field] == expected[field]
        assert actual['battle']['total_damage'] == expected['battle']['total_damage']
        assert actual['battle']['duration_ms'] == expected['battle']['duration_ms']
        assert build_raw_log_upload_document(str(target))['content'] == integrity['raw_content']
    assert source.read_bytes() == original


def test_selected_session_export_and_analysis_allow_append_but_reject_changed_prefix(tmp_path):
    from app_test_support.scenarios.raw import raw_scene, raw_hit
    from endfield_pcap.history.records import load_combat_records
    from endfield_pcap.history.analysis import load_record_snapshot
    from endfield_pcap.history.export import export_battle_log
    from parser_core.battle_splitter import split_trace_battles
    start = 1793808000000
    events = [raw_scene(start),
        {'type': 'SC_OBJECT_ENTER_VIEW', 'timestamp_ms': start,
         'objects': [{'battle_inst_id': 99, 'templateid': 'eny_0051_rodin'}]},
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': start + 100, 'is_in_battle': True},
        raw_hit(start + 1000, 100), raw_hit(start + 2000, 200),
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': start + 60000, 'is_in_battle': True},
        raw_hit(start + 61000, 900), raw_hit(start + 62000, 1000)]
    def header(volume, offset, previous=None):
        return dict(type='session_volume', schema_version=1, recording_id='selected', session_id='test',
            trace_recording_id='trace-selected', volume=volume, trace_volume=volume,
            event_offset=offset, timezone_offset_minutes=480, previous_volume=previous)
    first, last = tmp_path / 'session_first.ndjson', tmp_path / 'session_last.ndjson'
    for path, metadata, rows in ((first, header(1, 0), events[:3]),
            (last, header(2, 3, {'volume': 1, 'file': first.name}), events[3:])):
        path.write_text(''.join(json.dumps(row) + '\n' for row in [metadata, *rows]), encoding='utf8')
    records = sorted(load_combat_records(tmp_path), key=lambda row: row.record_index)
    assert len(records) == 2
    with last.open('a', encoding='utf8') as stream:
        stream.write(json.dumps(raw_hit(start + 63000, 3000)) + '\n')
    for row, total in zip(records, (300, 1900)):
        target = tmp_path / f'session-selected-{row.record_index}.log'
        export_battle_log(row, target)
        content = load_raw_log_integrity(str(target))
        assert content['verified'] and len(split_trace_battles(content['raw_content'])) == 1
        expected_export = total if row.record_index == 1 else total + 3000
        assert parse_overlay_battle_snapshot_text(content['raw_content'])['battle']['total_damage'] == expected_export
        assert load_record_snapshot(row)['battle']['total_damage'] == total
    # Another battle appended later must never enter either selected export.
    with last.open('a', encoding='utf8') as stream:
        for event in ({'type': 'BattleOpModifyBattleState', 'timestamp_ms': start + 90000, 'is_in_battle': True},
                      raw_hit(start + 91000, 88888)):
            stream.write(json.dumps(event) + '\n')
    target = tmp_path / 'after-next-battle.log'
    export_battle_log(records[1], target)
    content = load_raw_log_integrity(str(target))['raw_content']
    assert len(split_trace_battles(content)) == 1
    assert parse_overlay_battle_snapshot_text(content)['battle']['total_damage'] == 4900
    saved = last.read_bytes()
    last.unlink()
    with pytest.raises(ValueError, match='分卷已变化或不完整'):
        export_battle_log(records[0], tmp_path / 'missing-volume.log')
    assert not (tmp_path / 'missing-volume.log').exists()
    last.write_bytes(saved)
    first.write_bytes(first.read_bytes().replace(b'"is_in_battle": true', b'"is_in_battle": false'))
    with pytest.raises(ValueError, match='已变化'):
        load_record_snapshot(records[0])
    with pytest.raises(ValueError, match='已变化'):
        export_battle_log(records[0], tmp_path / 'tampered.log')
    assert not (tmp_path / 'tampered.log').exists()


def test_selected_session_excludes_next_official_start_and_keeps_packet_phases(tmp_path):
    from app_test_support.scenarios.raw import raw_scene, raw_hit
    from endfield_pcap.history.records import load_combat_records
    from endfield_pcap.history.analysis import load_record_snapshot
    from endfield_pcap.history.export import export_battle_log
    from parser_core.battle_splitter import split_trace_battles
    start = 1793808000000
    official = {'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_START', 'timestamp_ms': start + 3000,
                'game_id': 'test', 'challenge_start_ts': '123'}
    events = [raw_scene(start), {'type': 'SC_OBJECT_ENTER_VIEW', 'timestamp_ms': start,
               'objects': [{'battle_inst_id': 99, 'templateid': 'eny_0051_rodin'}]},
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': start + 100, 'is_in_battle': True},
        raw_hit(start + 1000, 100), official,
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': start + 3100, 'is_in_battle': True},
        raw_hit(start + 3200, 200), dict(official, timestamp_ms=start + 3300),
        {'type': 'BattleOpModifyBattleState', 'timestamp_ms': start + 3400, 'is_in_battle': True},
        raw_hit(start + 3500, 300),
        {'type': 'SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE', 'timestamp_ms': start + 4000,
         'game_id': 'test', 'is_pass': True, 'pass_time': 1000}]
    source = tmp_path / 'session_official.ndjson'
    source.write_text(''.join(json.dumps(row) + '\n' for row in events), encoding='utf8')
    records = sorted(load_combat_records(tmp_path), key=lambda row: row.record_index)
    assert [row.total_damage for row in records] == [100, 500]
    for row in records:
        target = tmp_path / f'selected-{row.record_index}.log'
        export_battle_log(row, target)
        content = load_raw_log_integrity(str(target))['raw_content']
        assert len(split_trace_battles(content)) == 1
        actual = parse_overlay_battle_snapshot_text(content)
        expected = load_record_snapshot(row)
        assert actual['battle']['total_damage'] == expected['battle']['total_damage'] == row.total_damage
        assert actual['battle']['duration_ms'] == expected['battle']['duration_ms']
