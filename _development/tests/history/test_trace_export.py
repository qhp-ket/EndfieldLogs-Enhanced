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
