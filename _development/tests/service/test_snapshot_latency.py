import asyncio
import json
import threading
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
import endfield_pcap.gui.main as gui_main
import endfield_pcap.overlays.manager as overlay_host
from endfield_pcap.analysis.live.publisher import SnapshotPublisher
from parser_core.live import LiveOverlayBattleParser
from app_test_support.runtime.service import FIXTURE, service_factory
from app_test_support.ui.window import entry, main_window
from app_test_support.ui.qt import EVIDENCE, snapshot_message


def test_process_uses_canonical_results_and_reset_closes_its_own_worker():
    async def scenario():
        publisher = SnapshotPublisher(use_process=True)
        try:
            await publisher.publish_pending()
            assert publisher._worker is None  # no consumer work for an empty clear
            publisher.start()
            process = publisher._worker.process
            assert process.is_alive()
            for line in FIXTURE.splitlines(keepends=True):
                publisher.feed_line(line)
            frame = await asyncio.wait_for(publisher.publish_pending(), 30)
            expected = LiveOverlayBattleParser(align_to_data_watermark=True)
            expected.feed_lines(FIXTURE.splitlines(keepends=True))
            assert frame["snapshot"] == expected.snapshot()
            publisher.feed_line('[10:01:00.000] GAME_TIMER_RESET source=test\n')
            assert (await publisher.publish_pending())["snapshot"] is None
            for line in FIXTURE.replace('10:00:', '10:01:').splitlines(keepends=True):
                publisher.feed_line(line)
            second = await asyncio.wait_for(publisher.publish_pending(), 20)
            assert second["snapshot"]["battle"]["total_damage"] == 760
            assert second["sequence"] > frame["sequence"]
        finally:
            await publisher.close()
        assert not process.is_alive()
    asyncio.run(scenario())


def test_no_clients_does_not_serialize_a_full_snapshot(service_factory, monkeypatch):
    service = service_factory()
    frame = snapshot_message()
    def forbidden(*args, **kwargs):
        raise AssertionError('No network clients: JSON encoding is unnecessary')
    monkeypatch.setattr('endfield_pcap.service.runtime.server.json.dumps', forbidden)
    received = []
    service.observer = SimpleNamespace(on_analysis_snapshot=received.append)
    asyncio.run(service._deliver_snapshot(frame, 'on_analysis_snapshot'))
    assert received == [frame]


def test_qt_raw_queue_contains_only_squad_changes(monkeypatch):
    class Service:
        def __init__(self, config, observer): self.observer = observer
        def set_full_analysis_required(self, required): pass
        async def run(self):
            for _ in range(10000): self.observer.on_event({'type': 'BattleOpTriggerAction'})
            self.observer.on_event({'type': 'SC_SELF_SCENE_INFO', 'char_list': []})
    monkeypatch.setattr('endfield_pcap.gui.service.DamageLogService', Service)
    controller = gui_main.ServiceController(SimpleNamespace())
    controller.start(); controller.join()
    assert controller.queue.get_nowait() == ('event', {'type': 'SC_SELF_SCENE_INFO', 'char_list': []})
    assert controller.queue.get_nowait() == ('stopped', None)
    assert controller.queue.empty()


def test_bulk_buttons_and_enabled_count_fit_together(main_window, app):
    window = main_window
    card = window.overlay_page.status_card
    window.switchTo(window.overlay_page)
    QTest.qWait(150)
    for button in (card.enable_all_btn, card.disable_all_btn, card.visibility_button):
        assert card.rect().contains(button.mapTo(card, button.rect().topRight()))
    assert card.enabled_count.mapTo(card, QPoint()).y() > card.visibility_button.mapTo(card, card.visibility_button.rect().bottomLeft()).y()
    assert card.enabled_count.mapTo(card, card.enabled_count.rect().topRight()).x() < card.width()
    assert window.queue_timer.interval() == 33
    assert window.grab().save(str(EVIDENCE / 'gui-home-count.png'))


def test_native_table_gets_small_view_and_manager_retains_full_report(app, tmp_path):
    frame = snapshot_message()
    frame['snapshot']['buff_events'] = [{'evidence': 'x' * 10000} for _ in range(100)]
    frame['snapshot']['timeline_events'] = ['x' * 10000] * 100
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    current = entry(enabled=True)
    try:
        manager.apply_analysis_snapshot(frame)
        manager.apply_entry(current)
        window = manager._windows[current.id]
        app.processEvents()
        view = window.canvas.modules[0].snapshot
        for key in ('battle', 'participants', 'snapshot_quality', 'rdps_damage_basis', 'rdps_preflight'):
            assert view[key] == frame['snapshot'][key]
        assert 'buff_events' not in view and 'timeline_events' not in view
        assert manager._analysis_snapshot['snapshot'] == frame['snapshot']
        assert len(json.dumps(view)) < len(json.dumps(frame['snapshot'])) / 10
        assert window.canvas.modules[0].snapshot["battle"]["total_damage"] == 760
        # Unsubscribed windows do not copy/cache multi-MB damage evidence.
        combo = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(entry=entry(source_value='combo_skill'), ws_port=1))
        try:
            combo.apply_analysis_snapshot(frame)
            assert not hasattr(combo.canvas.modules[0], 'message')
        finally: combo.close()
    finally:
        manager.close_all(); app.processEvents()


def test_process_exit_clears_state_and_next_input_starts_a_fresh_worker():
    async def scenario():
        publisher = SnapshotPublisher(use_process=True)
        try:
            await publisher.publish_pending()
            publisher.start()
            broken = publisher._worker
            broken.process.terminate()
            await asyncio.to_thread(broken.process.join, 5)
            publisher.feed_line(FIXTURE.splitlines(keepends=True)[0])
            failed = await asyncio.wait_for(publisher.publish_pending(), 15)
            assert failed['snapshot'] is None and failed['error']
            assert broken.closed and not broken.process.is_alive()
            for line in FIXTURE.splitlines(keepends=True): publisher.feed_line(line)
            recovered = await asyncio.wait_for(publisher.publish_pending(), 30)
            assert recovered['snapshot']['battle']['total_damage'] == 760
            assert publisher._worker is not broken
        finally:
            await publisher.close()
    asyncio.run(scenario())


def test_process_generation_discards_busy_result_without_losing_next_battle(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    class Worker:
        def __init__(self): self.lines = []; self.closed = False; self.last_metrics = {}
        def feed_line(self, generation, line): self.lines.append((generation, line))
        def calculate(self, generation):
            if generation == 0:
                entered.set()
                assert release.wait(5)
            return {'lines': [line for gen, line in self.lines if gen == generation]}
        def close(self): self.closed = True
    monkeypatch.setattr('endfield_pcap.analysis.live.process.SnapshotProcess', Worker)
    async def scenario():
        publisher = SnapshotPublisher(use_process=True)
        try:
            await publisher.publish_pending()
            publisher.feed_line('old\n')
            task = asyncio.create_task(publisher.publish_pending())
            assert await asyncio.to_thread(entered.wait, 3)
            publisher.reset()
            publisher.feed_line('new\n')
            release.set()
            assert await task is None
            assert (await publisher.publish_pending())['snapshot'] is None
            assert (await publisher.publish_pending())['snapshot'] == {'lines': ['new\n']}
        finally:
            release.set()
            await publisher.close()
    asyncio.run(scenario())


def test_service_startup_failure_closes_analysis_worker(service_factory, monkeypatch):
    service = service_factory()
    closed = []
    async def close(): closed.append(True)
    async def failed(*args, **kwargs): raise OSError('test port already in use')
    monkeypatch.setattr(service.snapshot_publisher, 'close', close)
    monkeypatch.setattr('endfield_pcap.service.runtime.server.websockets.serve', failed)
    with pytest.raises(OSError, match='test port already in use'):
        asyncio.run(service.run())
    assert closed == [True]
