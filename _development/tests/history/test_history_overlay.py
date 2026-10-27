from app_test_support.scenarios.raw import raw_hit, raw_scene
import json
from datetime import datetime
import endfield_pcap.history.analysis as history_analysis
import endfield_pcap.overlays.manager as overlay_host
from endfield_pcap.history.records import load_combat_records
from endfield_pcap.models import OverlayEntry
from endfield_pcap.models import OverlaySourceType

def test_history_indexes_exact_source_range_and_replay_does_not_mix_next_battle(tmp_path):
    events = [raw_scene(),
        {"type": "SC_OBJECT_ENTER_VIEW", "timestamp_ms": 1_000_100,
         "objects": [{"battle_inst_id": 99, "templateid": "eny_0051_rodin"}]},
        {"type": "BattleOpModifyBattleState", "timestamp_ms": 1_001_000, "is_in_battle": True},
        raw_hit(1_002_000, 100), raw_hit(1_003_000, 200),
        {"type": "BattleOpModifyBattleState", "timestamp_ms": 1_004_000, "is_in_battle": False},
        {"type": "BattleOpModifyBattleState", "timestamp_ms": 1_010_000, "is_in_battle": True},
        raw_hit(1_011_000, 900), raw_hit(1_012_000, 1000),
        {"type": "GAME_CLOCK_TICK", "timestamp_ms": 1_100_000, "tick_ms": 100000}]
    path = tmp_path / "session_test.ndjson"
    for event in events:
        event["timestamp_ms"] += 1_792_000_000_000
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    records = sorted(load_combat_records(tmp_path), key=lambda r: r.record_index)
    assert [(r.source_start_line, r.source_end_line) for r in records] == [(2, 6), (6, 10)]
    assert [r.total_damage for r in records] == [300, 1900]
    # Appending to an active source after indexing cannot enter the selection.
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n" + json.dumps(raw_hit(1_792_001_101_000, 99999)))
    snapshots = [history_analysis.load_record_snapshot(r) for r in records]
    assert [s["battle"]["total_damage"] for s in snapshots] == [300, 1900]
    assert all("snapshot_quality" in s for s in snapshots)
    assert not list(tmp_path.glob("*.log")), "history replay must not write trace files"

def test_history_mode_keeps_latest_live_and_reopen_replays_current_presentation(monkeypatch):
    class Window:
        def __init__(self, config): self.messages = []
        def apply_analysis_snapshot(self, value): self.messages.append(value)
        def show(self): pass
    monkeypatch.setattr(overlay_host, "OverlayWindow", Window)
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    def message(n):
        return {"type": "analysis_snapshot", "schema_version": 1, "stream_id": "live", "sequence": n,
                "snapshot": {"battle": {"total_damage": n}}}
    manager.apply_analysis_snapshot(message(1))
    manager.show_history({"battle": {"total_damage": 99}}, "selected")
    history = manager._analysis_snapshot
    manager.apply_analysis_snapshot(message(2))
    entry = OverlayEntry("test", "damage", OverlaySourceType.BUILTIN, "damage", True, False, False)
    manager.apply_entry(entry)
    assert manager._windows[entry.id].messages[-1] == history
    manager.return_live()
    live = manager._windows[entry.id].messages[-1]
    assert live["snapshot"]["battle"]["total_damage"] == 2
    assert live["stream_id"] == history["stream_id"] and live["sequence"] > history["sequence"]
    assert live["source"] == {"mode": "live"}
    manager.show_history({"battle": {}}, "other")
    manager.apply_analysis_snapshot({**message(3), "snapshot": None})
    manager.return_live()
    assert manager._analysis_snapshot["snapshot"] is None

def test_official_start_before_indexed_range_and_leave_reset_do_not_erase_history(tmp_path):
    started = int(datetime(2026, 10, 21, 10).timestamp() * 1000)
    events = [raw_scene(started), {"type": "SC_OBJECT_ENTER_VIEW", "timestamp_ms": started,
        "objects": [{"battle_inst_id": 99, "templateid": "eny_0051_rodin"}]},
        {"type": "SC_GAME_MECHANICS_SYNC_CHALLENGE_START", "timestamp_ms": started,
         "game_id": "dung_ss06", "challenge_start_ts": str(started), "challenge_expire_ts": str(started + 420000)},
        {"type": "BattleOpModifyBattleState", "timestamp_ms": started + 100, "is_in_battle": True, "client_tick_tms": 100},
        raw_hit(started + 1000, 100), raw_hit(started + 2000, 200),
        {"type": "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE", "timestamp_ms": started + 3000,
         "game_id": "dung_ss06", "is_pass": True, "pass_time": 3000},
        {"type": "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST", "timestamp_ms": started + 5000, "game_id": "dung_ss06"}]
    path = tmp_path / "session_official.ndjson"
    path.write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    record = load_combat_records(tmp_path)[0]
    assert record.source_start_line == 3
    snapshot = history_analysis.load_record_snapshot(record)
    assert snapshot["battle"]["total_damage"] == 300
    assert snapshot["battle"]["duration_ms"] == 3000
    assert snapshot["battle"]["official_timer_start_seen"]
    assert snapshot["battle"]["official_timer_end_seen"]
