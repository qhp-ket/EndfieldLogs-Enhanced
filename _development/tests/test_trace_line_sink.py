from datetime import datetime

import pytest

from endfield_pcap import trace_bridge as trace_module
from endfield_pcap.trace_bridge import TraceBridge


def test_sink_gets_exact_disk_lines_after_each_write_including_pending_order(tmp_path):
    path = tmp_path / "trace.log"
    received = []
    def sink(line):
        received.append(line)
        # The callback sees a closed/flushed write, with identical LF bytes.
        assert path.read_bytes() == "".join(received).encode("utf-8")
    bridge = TraceBridge(path, line_sink=sink)
    bridge._pending_buff_start_ts_ms = 1000
    bridge._pending_buff_start_order = [9007199254740993]
    bridge._pending_buff_start_rows[9007199254740993] = (
        "buff_fixture", "chr_0004_pelica", "chr_0035_liino",
        {"blackboard": {"atk_up": {"float_value": 0.2}}},
    )
    bridge._line(2000, 'HP_V2 #1 hit=120 skill="fixture"')
    bridge.handle_event({"type": "GAME_CLOCK_TICK", "source": "CS_BATTLE_OP",
                         "timestamp_ms": 2500, "tick_ms": 50, "seq_id": 3})
    assert len(received) == 4
    assert " BUFF_START " in received[0]
    assert " BB[9007199254740993]:" in received[1]
    assert " HP_V2 " in received[2]
    assert " GAME_CLOCK_TICK " in received[3]
    assert all(line.endswith("\n") and not line.endswith("\r\n") for line in received)


def test_memory_only_bridge_never_resolves_or_writes_default_or_supplied_path(tmp_path, monkeypatch):
    def forbidden_default():
        raise AssertionError("memory-only trace must not select a default file")
    monkeypatch.setattr(trace_module, "default_trace_file", forbidden_default)
    path = tmp_path / "uncreated" / "trace.log"
    received = []
    bridge = TraceBridge(path, write_enabled=False, line_sink=received.append)
    bridge.begin_capture_session(timestamp_ms=1000)
    bridge._append_line(2000, "DUNGEON_CONTEXT dungeonId=fixture")
    assert bridge.trace_file is None
    assert not path.parent.exists()
    assert len(received) == 2
    assert " GAME_TIMER_RESET " in received[0]
    assert " DUNGEON_CONTEXT " in received[1]


def test_default_trace_behavior_still_truncates_then_appends(tmp_path, monkeypatch):
    path = tmp_path / "trace.log"
    path.write_text("old battle", encoding="utf-8")
    monkeypatch.setattr(trace_module, "default_trace_file", lambda: path)
    bridge = TraceBridge()
    assert path.read_bytes() == b""
    bridge._append_line(1234, "fixture")
    stamp = datetime.fromtimestamp(1.234).strftime("%H:%M:%S.%f")[:-3]
    assert path.read_bytes() == f"[{stamp}] fixture\n".encode("utf-8")


def test_failed_disk_write_does_not_feed_a_line_that_was_not_saved(tmp_path, monkeypatch):
    path = tmp_path / "trace.log"
    received = []
    bridge = TraceBridge(path, line_sink=received.append)
    def broken_open(*args, **kwargs):
        raise OSError("disk failure")
    monkeypatch.setattr(type(path), "open", broken_open)
    with pytest.raises(OSError, match="disk failure"):
        bridge._append_line(1000, "fixture")
    assert received == []
