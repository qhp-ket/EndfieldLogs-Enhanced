from app_test_support.runtime.service import FIXTURE, service_factory
from app_test_support.paths import ROOT
import asyncio
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import threading
from types import SimpleNamespace
import pytest
import websockets
import endfield_pcap.service.runtime.server as service_module
from endfield_pcap.models import BattleLogEvent
from endfield_pcap.models import ServiceObserver
from endfield_pcap.analysis.live.publisher import SnapshotPublisher
from endfield_pcap.trace.bridge import TraceBridge
from parser_core.live import LiveOverlayBattleParser
from parser_core.unified import parse_overlay_battle_snapshot_text, rdps_totals_from_raw_report

def test_fixture_transport_matches_canonical_offline_and_live_without_wall_clock(monkeypatch):
    def forbidden_wall_clock():
        raise AssertionError("publisher must follow the processed data watermark")
    monkeypatch.setattr("parser_core.live._current_clock_ms", forbidden_wall_clock)
    async def scenario():
        publisher = SnapshotPublisher()
        initial = await publisher.publish_pending()
        assert initial["snapshot"] is None and initial["sequence"] == 0
        for line in FIXTURE.splitlines(keepends=True):
            publisher.feed_line(line)
        envelope = await publisher.publish_pending()
        snapshot = envelope["snapshot"]
        offline = parse_overlay_battle_snapshot_text(FIXTURE, file_name="live-overlay.log")
        live = LiveOverlayBattleParser(align_to_data_watermark=True)
        live.feed_lines(FIXTURE.splitlines(keepends=True))
        assert snapshot == offline == live.snapshot()
        assert envelope["type"] == "analysis_snapshot" and envelope["schema_version"] == 1
        assert envelope["stream_id"] == initial["stream_id"] and envelope["sequence"] == 1
        assert snapshot["battle"]["duration_ms"] == 2000
        assert rdps_totals_from_raw_report(snapshot) == {"chr_0004_pelica": 640, "chr_0035_liino": 120}
        assert snapshot["snapshot_quality"] == offline["snapshot_quality"]
        assert await publisher.publish_pending() is None
        assert publisher.current_message() == envelope
        json.dumps(envelope, allow_nan=False)
    asyncio.run(scenario())

def test_exact_trace_line_sink_produces_the_same_fixture_snapshot(tmp_path):
    async def scenario():
        publisher = SnapshotPublisher()
        await publisher.publish_pending()
        path = tmp_path / "trace.log"
        received = []
        def sink(line):
            received.append(line)
            publisher.feed_line(line)
        bridge = TraceBridge(path, line_sink=sink)
        # Use bridge's single formatter; this is the exact local timestamp it writes.
        for line in FIXTURE.splitlines():
            if not line.startswith("["):
                continue
            timestamp, body = line.split("] ", 1)
            local = datetime.strptime("2026-10-21 " + timestamp[1:], "%Y-%m-%d %H:%M:%S.%f")
            bridge._append_line(int(local.timestamp() * 1000), body)
        assert path.read_bytes() == "".join(received).encode("utf-8")
        actual = (await publisher.publish_pending())["snapshot"]
        expected = parse_overlay_battle_snapshot_text("".join(received), file_name="live-overlay.log")
        assert actual == expected
        assert rdps_totals_from_raw_report(actual) == {"chr_0004_pelica": 640, "chr_0035_liino": 120}
    asyncio.run(scenario())

def test_worker_coalesces_ordered_lines_and_transport_copy_preserves_core_cache():
    original = {"value": (1 << 64) - 1, "zero": 0, "unknown": None, "nested": [{"uid": "9007199254740993"}]}
    calls = []
    class Parser:
        def feed_lines(self, lines):
            calls.append(("feed", list(lines), threading.get_ident()))
        def snapshot(self):
            calls.append(("snapshot", threading.get_ident()))
            return original
    async def scenario():
        publisher = SnapshotPublisher(parser_factory=Parser)
        await publisher.publish_pending()
        event_thread = threading.get_ident()
        for index in range(1000):
            publisher.feed_line(f"line {index}\n")
        assert calls == []
        envelope = await publisher.publish_pending()
        assert len(calls) == 2
        assert calls[0][1] == [f"line {index}\n" for index in range(1000)]
        assert calls[0][-1] != event_thread and calls[1][-1] != event_thread
        assert envelope["snapshot"]["value"] == str((1 << 64) - 1)
        assert envelope["snapshot"]["zero"] == 0 and envelope["snapshot"]["unknown"] is None
        before = deepcopy(original)
        envelope["snapshot"]["nested"][0]["uid"] = "edited"
        assert original == before
        current = publisher.current_message()
        current["snapshot"]["nested"].clear()
        assert publisher.current_message()["snapshot"]["nested"] == before["nested"]
        assert len(calls) == 2
    asyncio.run(scenario())

def test_reset_frame_survives_a_busy_worker_and_new_hits_in_the_same_tick():
    entered, release = threading.Event(), threading.Event()
    class Parser:
        def feed_lines(self, lines):
            self.lines = list(lines)
        def snapshot(self):
            if self.lines == ["old\n"]:
                entered.set()
                assert release.wait(3)
            return {"lines": self.lines}
    async def scenario():
        publisher = SnapshotPublisher(parser_factory=Parser)
        initial = await publisher.publish_pending()
        publisher.feed_line("old\n")
        task = asyncio.create_task(publisher.publish_pending())
        assert await asyncio.to_thread(entered.wait, 2)
        # The event loop remains responsive while snapshot() is blocked.
        publisher.feed_line("[10:00:01.000] GAME_TIMER_RESET source=test\n")
        publisher.feed_line("new\n")
        assert publisher.current_message()["snapshot"] is None
        release.set()
        assert await task is None
        clear = await publisher.publish_pending()
        assert clear["snapshot"] is None and clear["sequence"] > initial["sequence"]
        fresh = await publisher.publish_pending()
        assert fresh["snapshot"] == {"lines": ["new\n"]}
        assert fresh["sequence"] > clear["sequence"]
    try:
        asyncio.run(scenario())
    finally:
        release.set()

def test_parser_failure_clears_the_previous_state_and_is_visible(caplog):
    class Parser:
        def feed_lines(self, lines):
            self.bad = "bad\n" in lines
        def snapshot(self):
            if self.bad:
                raise RuntimeError("synthetic analysis failure")
            return {"battle": "current"}
    async def scenario():
        publisher = SnapshotPublisher(parser_factory=Parser)
        await publisher.publish_pending()
        publisher.feed_line("good\n")
        good = await publisher.publish_pending()
        publisher.feed_line("bad\n")
        failed = await publisher.publish_pending()
        assert failed["snapshot"] is None
        assert failed["sequence"] > good["sequence"]
        assert failed["error"] == {"type": "RuntimeError", "message": "synthetic analysis failure"}
        assert publisher.current_message() == failed
        assert "synthetic analysis failure" in caplog.text
        publisher.feed_line("new\n")
        recovered = await publisher.publish_pending()
        assert recovered["snapshot"] == {"battle": "current"} and "error" not in recovered
    asyncio.run(scenario())

def test_real_reset_new_battle_and_new_stream_never_retain_old_rows():
    async def scenario():
        publisher = SnapshotPublisher()
        await publisher.publish_pending()
        for line in FIXTURE.splitlines(keepends=True):
            publisher.feed_line(line)
        first = await publisher.publish_pending()
        publisher.feed_line("[10:01:00.000] GAME_TIMER_RESET source=test\n")
        for line in FIXTURE.replace("10:00:", "10:01:").splitlines(keepends=True):
            publisher.feed_line(line)
        clear = await publisher.publish_pending()
        assert clear["snapshot"] is None
        second = await publisher.publish_pending()
        assert second["snapshot"]["battle"]["total_damage"] == 760
        assert rdps_totals_from_raw_report(second["snapshot"]) == {"chr_0004_pelica": 640, "chr_0035_liino": 120}
        assert first["sequence"] < clear["sequence"] < second["sequence"]
        publisher.reset(new_stream=True)
        new = await publisher.publish_pending()
        assert new["stream_id"] != first["stream_id"]
        assert new["sequence"] == 0 and new["snapshot"] is None
    asyncio.run(scenario())

def test_consecutive_official_battles_follow_existing_live_boundaries():
    async def scenario():
        publisher = SnapshotPublisher()
        await publisher.publish_pending()
        game = "dung01_bossrush01_04"
        start = f"[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId={game} challengeStartTs=1\n"
        end = f"[10:00:03.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId={game} isPass=1 passTime=3000\n"
        for line in (start + FIXTURE + "\n" + end).splitlines(keepends=True):
            publisher.feed_line(line)
        first = await publisher.publish_pending()
        assert first["snapshot"]["snapshot_quality"]["timing"]["status"] == "verified"
        second_input = start.replace("10:00:", "10:01:").replace("challengeStartTs=1", "challengeStartTs=60001") + FIXTURE.replace("10:00:", "10:01:")
        for line in second_input.splitlines(keepends=True):
            publisher.feed_line(line)
        second = await publisher.publish_pending()
        expected = parse_overlay_battle_snapshot_text(second_input, file_name="live-overlay.log")
        assert second["snapshot"] == expected
        assert second["snapshot"]["battle"]["total_damage"] == 760
        assert second["snapshot"]["snapshot_quality"]["timing"]["status"] == "provisional"
    asyncio.run(scenario())

def test_direct_gui_service_creates_official_archive_status_and_keeps_explicit_path(service_factory, tmp_path):
    service = service_factory(trace_enabled=True)
    expected = service.config.trace_file.with_suffix(".log.status.json")
    assert service.status_file == expected and service.config.status_file == expected
    status = json.loads(expected.read_text(encoding="utf-8"))
    assert status["type"] == "status" and status["schema_version"] == 1
    assert status["state"] == "waiting_game" and status["fatal_error"] is None
    explicit = tmp_path / "custom-status.json"
    service = service_factory(trace_enabled=True, status_file=explicit)
    assert service.status_file == explicit and explicit.is_file()
    assert service_factory(trace_enabled=False).status_file is None

def test_service_trace_is_directly_accepted_by_official_archive_import_gate(service_factory):
    import ast
    from uploader_core.log_integrity import load_raw_log_integrity
    # Execute the actual upstream GUI gate without importing its whole GUI,
    # updater, account or network stack. Generic upload_document intentionally
    # still reports missing proof; managed archive acceptance is a GUI policy.
    upstream = ROOT / '_development/audits/audit-20261021/upstream/endfield-suite-open/endfield-logs/apps/uploader/app/ui/main_window.py'
    if not upstream.is_file():
        pytest.skip('official source audit checkout is unavailable')
    tree = ast.parse(upstream.read_text(encoding='utf8'))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'MainWindow')
    cls.bases, cls.keywords, cls.decorator_list = [], [], []
    cls.body = [node for node in cls.body if isinstance(node, ast.FunctionDef)
        and node.name in {'_is_managed_archive_path', '_is_managed_archive_trace'}]
    scope = {'Path': Path}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(upstream), 'exec'), scope)
    service = service_factory(trace_enabled=True)
    service.trace_bridge.begin_capture_session(timestamp_ms=1000)
    service.trace_bridge._append_line(2000, 'HP_V2 #1 hit=120 raw=120 packetFinalValue=120 '
        'skill="chr_0004_pelica_combo_skill_projhit" actionId=11 damageUnitIndex=0 '
        'src=chr_0004_pelica tgt=eny_0051_rodin atk=chr_0004_pelica atkId=1001 tgtId=3001 hits=1')
    path = service.config.trace_file
    original = path.read_bytes()
    integrity = load_raw_log_integrity(str(path))
    assert scope['MainWindow']._is_managed_archive_trace(str(path), integrity)
    assert 'HP_V2' in integrity['raw_content'] and path.read_bytes() == original
    service.status_file.unlink()
    assert not scope['MainWindow']._is_managed_archive_trace(str(path), integrity)

def test_ink_packet_trace_preserves_double_precision_session_and_release_identity(tmp_path):
    path = tmp_path / 'trace.log'
    received = []
    bridge = TraceBridge(path, line_sink=received.append)
    bridge.id_to_name.update({4001: 'chr_0036_jsspsi', 3001: 'eny_0051_rodin'})
    event = dict(type='BattleOpTriggerAction', timestamp_ms=2000, owner_id=3001,
        owner_type=1, inst_id=7001, template_str_id='buff_chr_0036_jsspsi_xianjing_inkhurteffect',
        template_type='Buff', session_id='ink-session', seq_id=102, client_tick_tms=1000)
    bridge.handle_event({**event, 'action': dict(action_type='BattleActionSimpleCalcBb', action_id=47,
        simple_calc_bb_action=dict(client_target_key='EntityBB_ink_damage',
            client_value_a=123.456789012345, client_value_b=1.23456789012345,
            client_final_value=124.69135690246845))})
    bridge.handle_event({**event, 'seq_id': 130, 'action': dict(action_type='BattleActionLaunchProjectile',
        action_id=14, launch_projectile_action=dict(source_id=4001, details=[dict(client_projectile_id=8001)]))})
    disk = path.read_text(encoding='utf8')
    assert path.read_bytes() == ''.join(received).encode('utf8')
    assert 'valueA=123.456789012345' in disk and 'valueB=1.23456789012345' in disk
    assert 'packetSessionId=ink-session' in disk
    release = json.loads(next(line.split(' INK_RELEASE ', 1)[1] for line in received if ' INK_RELEASE ' in line))
    assert release['buff_uid'] == '7001' and release['projectile_id'] == '8001'
    assert release['source_actor_id'] == '4001' and release['session_id'] == 'ink-session'
    assert release['operation_seq'] == 130 and release['action_id'] == 14

def test_capture_start_failure_releases_port_for_restart(service_factory, monkeypatch):
    service = service_factory()
    stopped = []
    def failed_start():
        raise RuntimeError('capture startup failed')
    monkeypatch.setattr(service.capture_manager, 'start', failed_start)
    monkeypatch.setattr(service.capture_manager, 'stop', lambda: stopped.append(True))
    async def scenario():
        with pytest.raises(RuntimeError, match='capture startup failed'):
            await service.run()
        assert stopped and service.server is None and service.loop is None
        assert service._stop_event is None and service.log_file is None
    asyncio.run(scenario())

def test_service_memory_trace_and_observer_publish_replacement_with_raw_events_preserved(service_factory):
    observed = []
    raw = []
    service = service_factory(observer=ServiceObserver(on_event=raw.append, on_analysis_snapshot=observed.append))
    assert service.trace_bridge.trace_file is None
    assert not service.config.trace_file.parent.exists()
    async def scenario():
        await service._publish_analysis_snapshot()
        assert observed[-1]["snapshot"] is None
        service._handle_outbound_event(BattleLogEvent("test", 1000, "DUNGEON_CONTEXT", {"dungeon_id": "fixture"}))
        assert len(raw) == len(service.batch) == 1
        assert raw[0]["type"] == "DUNGEON_CONTEXT"
        await service._publish_analysis_snapshot()
        assert observed[-1]["snapshot"]["battle"]["total_damage"] == 0
        assert observed[-1]["snapshot"]["snapshot_quality"]["status"] == "unavailable"
        original = service.snapshot_publisher.current_message()
        observed[-1]["snapshot"]["battle"]["total_damage"] = 999
        assert service.snapshot_publisher.current_message() == original
        service.active_session = SimpleNamespace(flush_debug_state=lambda: None)
        service._reset_session()
        await service._publish_analysis_snapshot()
        assert observed[-1]["snapshot"] is None
        assert observed[-1]["sequence"] > original["sequence"]
    asyncio.run(scenario())

def test_decoded_damage_events_reach_disk_canonical_observer_and_websocket(service_factory):
    observed = []
    service = service_factory(trace_enabled=True, observer=ServiceObserver(on_analysis_snapshot=observed.append))
    async def scenario():
        await service._publish_analysis_snapshot()
        bridge = service.trace_bridge
        bridge.begin_capture_session(timestamp_ms=1_000)
        bridge.id_to_name.update({100701: "chr_0027_tangtang", 100804: "eny_0051_rodin"})
        for timestamp in (2_000, 3_000):
            service._handle_outbound_event(BattleLogEvent("fixture", timestamp, "BattleOpTriggerAction", {
                "owner_id": 100701,
                "template_str_id": "chr_0027_tangtang_attack1",
                "action": {"action_type": "BattleActionDamage", "damage_action": {
                    "attacker_id": 100701,
                    "details": [{"target_id": 100804, "value": 1234, "cur_hp": 5678, "is_crit": False}],
                }},
            }))
        # Reset is always visible before the next complete battle state.
        await service._publish_analysis_snapshot()
        await service._publish_analysis_snapshot()
        message = service.snapshot_publisher.current_message()
        disk = bridge.trace_file.read_text(encoding="utf-8")
        expected = LiveOverlayBattleParser(align_to_data_watermark=True)
        expected.feed_lines(disk.splitlines(keepends=True))
        assert message["snapshot"] == expected.snapshot()
        assert message["snapshot"]["battle"]["total_damage"] == 2468
        assert observed[-1] == message
        assert len(service.batch) == 2  # Original diagnostic stream is retained.
        async with websockets.serve(service._ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}") as socket:
                assert json.loads(await asyncio.wait_for(socket.recv(), 2))["type"] == "hello"
                assert json.loads(await asyncio.wait_for(socket.recv(), 2)) == observed[-1]
    asyncio.run(scenario())

class FakeSocket:
    def __init__(self):
        self.sent = []
        self.hello_entered = asyncio.Event()
        self.release_hello = asyncio.Event()
        self.closed = asyncio.Event()
    async def send(self, text):
        payload = json.loads(text)
        if not self.sent and payload["type"] == "hello":
            self.hello_entered.set()
            await self.release_hello.wait()
        self.sent.append(payload)
    async def wait_closed(self):
        await self.closed.wait()

def test_ws_hello_current_full_snapshot_then_registration_never_out_of_order(service_factory):
    async def scenario():
        service = service_factory()
        await service._publish_analysis_snapshot()
        socket = FakeSocket()
        handler = asyncio.create_task(service._ws_handler(socket))
        await asyncio.wait_for(socket.hello_entered.wait(), 1)
        assert socket not in service.clients
        for line in FIXTURE.splitlines(keepends=True):
            service.snapshot_publisher.feed_line(line)
        update = asyncio.create_task(service._publish_analysis_snapshot())
        # Await worker completion through its current state without releasing
        # the blocked handshake. This cannot publish before the initial hello.
        for _ in range(100):
            if service.snapshot_publisher.current_message()["snapshot"] is not None:
                break
            await asyncio.sleep(0.005)
        assert socket.sent == []
        socket.release_hello.set()
        await asyncio.wait_for(update, 2)
        for _ in range(100):
            if socket in service.clients:
                break
            await asyncio.sleep(.005)
        assert socket.sent[0]["type"] == "hello"
        assert socket.sent[1]["type"] == "analysis_snapshot"
        assert socket.sent[1]["snapshot"]["battle"]["total_damage"] == 760
        assert socket in service.clients
        sequences = [message["sequence"] for message in socket.sent if message["type"] == "analysis_snapshot"]
        assert sequences == sorted(sequences)
        service.batch.append({"type": "raw_control"})
        await service._flush_batch()
        for _ in range(100):
            if socket.sent[-1]['type'] == 'event_batch':
                break
            await asyncio.sleep(.005)
        assert socket.sent[-1]["type"] == "event_batch"
        socket.closed.set()
        await handler
        assert socket not in service.clients
    asyncio.run(scenario())

def test_ws_new_connection_without_damage_receives_explicit_null(service_factory):
    async def scenario():
        service = service_factory()
        socket = FakeSocket()
        socket.release_hello.set()
        task = asyncio.create_task(service._ws_handler(socket))
        for _ in range(20):
            if len(socket.sent) == 4:
                break
            await asyncio.sleep(0)
        assert [message["type"] for message in socket.sent] == ["hello", "analysis_snapshot", "buff_snapshot"]
        assert socket.sent[1]["snapshot"] is None
        socket.closed.set()
        await task
    asyncio.run(scenario())

def test_failed_snapshot_client_is_closed_to_trigger_full_reconnect(service_factory):
    class BrokenSocket:
        closed = False
        async def send(self, message):
            raise ConnectionError("synthetic send failure")
        async def close(self):
            self.closed = True
    async def scenario():
        service = service_factory()
        bad = BrokenSocket()
        good = FakeSocket()
        good.release_hello.set()
        service.clients.update((bad, good))
        await service._publish_analysis_snapshot()
        assert bad.closed and bad not in service.clients
        assert good in service.clients and good.sent[-1]["type"] == "analysis_snapshot"
    asyncio.run(scenario())

def test_localhost_websocket_full_handshake_raw_next_snapshot_and_reconnect(service_factory):
    async def receive(socket):
        return json.loads(await asyncio.wait_for(socket.recv(), 2))
    async def scenario():
        service = service_factory()
        await service._publish_analysis_snapshot()
        for line in FIXTURE.splitlines(keepends=True):
            service.snapshot_publisher.feed_line(line)
        await service._publish_analysis_snapshot()
        initial = service.snapshot_publisher.current_message()
        async with websockets.serve(service._ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with websockets.connect(f"ws://127.0.0.1:{port}") as socket:
                assert (await receive(socket))["type"] == "hello"
                assert await receive(socket) == initial
                assert (await receive(socket))["type"] == "buff_snapshot"
                service.batch.append({"type": "raw_control", "value": 7})
                await service._flush_batch()
                raw = await receive(socket)
                assert raw["type"] == "event_batch" and raw["events"] == [{"type": "raw_control", "value": 7}]
                service.snapshot_publisher.feed_line("[10:01:00.000] GAME_TIMER_RESET source=test\n")
                for line in FIXTURE.replace("10:00:", "10:01:").splitlines(keepends=True):
                    service.snapshot_publisher.feed_line(line)
                await service._publish_analysis_snapshot()
                clear = await receive(socket)
                assert clear["snapshot"] is None and clear["sequence"] > initial["sequence"]
                await service._publish_analysis_snapshot()
                latest = await receive(socket)
                assert latest == service.snapshot_publisher.current_message()
                assert latest["sequence"] > clear["sequence"]
                assert latest["snapshot"]["battle"]["total_damage"] == 760
                assert rdps_totals_from_raw_report(latest["snapshot"]) == {"chr_0004_pelica": 640, "chr_0035_liino": 120}
            async with websockets.connect(f"ws://127.0.0.1:{port}") as socket:
                assert (await receive(socket))["type"] == "hello"
                assert await receive(socket) == latest
                assert (await receive(socket))["type"] == "buff_snapshot"
        assert not service.clients
    asyncio.run(scenario())

def test_service_start_stop_changes_stream_and_notifies_clear_without_real_capture(service_factory, monkeypatch):
    class Server:
        def close(self):
            pass
        async def wait_closed(self):
            pass
    async def serve(*args, **kwargs):
        return Server()
    monkeypatch.setattr(service_module.websockets, "serve", serve)
    async def idle():
        await asyncio.Future()
    async def scenario():
        observed = []
        service = service_factory(observer=ServiceObserver(on_analysis_snapshot=observed.append))
        old_stream = service.snapshot_publisher.current_message()["stream_id"]
        monkeypatch.setattr(service, "_game_running", lambda: False)
        for name in ("_process_monitor_loop", "_packet_loop", "_stats_loop"):
            monkeypatch.setattr(service, name, idle)
        task = asyncio.create_task(service.run())
        for _ in range(20):
            if service._started_event.is_set():
                break
            await asyncio.sleep(0)
        assert service._started_event.is_set()
        assert service.snapshot_publisher.current_message()["stream_id"] != old_stream
        service.request_stop()
        await asyncio.wait_for(task, 2)
        assert service.capture_manager.started and service.capture_manager.stopped
        assert observed[-1]["snapshot"] is None
        assert service.snapshot_publisher.current_message()["snapshot"] is None
        assert service.loop is None
    asyncio.run(scenario())
