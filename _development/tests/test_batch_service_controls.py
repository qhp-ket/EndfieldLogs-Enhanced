"""Batch history actions and explicit, restartable capture service controls."""
from copy import deepcopy
from pathlib import Path
import threading

from PySide6.QtCore import QItemSelectionModel
from PySide6.QtTest import QTest

from endfield_pcap import gui_main, gui_service
from endfield_pcap.gui_config import load_app_config
from test_overlay_controls import main_window
from test_trace_import import two_battles, wait_for
from test_qt_snapshot_bridge import EVIDENCE


def test_batch_load_preserves_click_order_and_only_presents_last(main_window, app, tmp_path, monkeypatch):
    window = main_window
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    listing = window.records_page.record_list
    # Select the older row, then Ctrl-select the newer row: presentation follows
    # the final selection, not row order or the last worker to finish.
    listing.setCurrentRow(1)
    listing.setCurrentRow(0, QItemSelectionModel.SelectionFlag.Select)
    order = window._selected_history_records()
    assert [r.record_index for r in order] == [1, 2]
    calls = []
    from endfield_pcap.history_analysis import load_record_snapshot
    def analyze(record):
        calls.append(record.record_index)
        return load_record_snapshot(record)
    monkeypatch.setattr('endfield_pcap.gui_history.load_record_snapshot', analyze)
    window.records_page.load_overlay_btn.click()
    wait_for(lambda: window.overlay_manager._history_mode, app)
    assert calls == [1, 2]
    assert all(record.analysis_loaded for record in window.records)
    assert len(listing.selectedItems()) == 2
    assert listing.delegate.selectedRows == {0, 1}
    assert window.overlay_manager._analysis_snapshot['snapshot']['battle']['total_damage'] == 860
    assert window._selected_record.record_index == 2
    window.switchTo(window.records_page)
    QTest.qWait(350)
    assert window.grab().save(str(EVIDENCE / 'gui-history-batch.png'))
    before = source.read_bytes()
    window.records_page.remove_record_btn.click()
    assert not window.records
    assert not window.overlay_manager._history_mode
    assert len(load_app_config(window.config_path).hidden_history_records) == 2
    assert source.read_bytes() == before


def test_partial_batch_failure_keeps_last_selection_as_presentation_target(main_window, app, tmp_path, monkeypatch):
    window = main_window
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    window.records_page.select_all_btn.click()
    target = window._selected_history_records()[-1]
    from endfield_pcap.history_analysis import load_record_snapshot
    def analyze(record):
        if record is target:
            raise ValueError('selected target failed')
        return load_record_snapshot(record)
    monkeypatch.setattr('endfield_pcap.gui_history.load_record_snapshot', analyze)
    window._load_selected_history()
    wait_for(lambda: '加载失败' in window.records_page.overlay_source_status.text(), app)
    assert not window.overlay_manager._history_mode
    assert sum(record.analysis_loaded for record in window.records) == 1
    assert window.records_page.overlay_source_status.toolTip()


def test_single_capture_button_saved_port_and_nonblocking_stop(main_window, app, tmp_path, monkeypatch):
    window = main_window
    class Controller:
        def __init__(self):
            self.running = False
            self.queue = window.service_controller.queue
            self.lifecycle = gui_service.CaptureLifecycle.STOPPED
            self.running_config = None
            self.starts, self.stops = [], 0
        def is_running(self): return self.running
        def start(self):
            self.running_config = deepcopy(window.app_config.service)
            self.starts.append(self.running_config.ws_port)
            self.running = True
            self.lifecycle = gui_service.CaptureLifecycle.STARTING
        def stop(self):
            self.stops += 1
            self.lifecycle = gui_service.CaptureLifecycle.STOPPING
        def join(self, **kwargs): pass
    controller = Controller()
    monkeypatch.setattr(window, 'service_controller', controller)
    monkeypatch.setattr(gui_main, '_is_valid_game_dir', lambda path: True)
    monkeypatch.setattr(window, '_ensure_npcap_ready', lambda: True)
    window.app_config.service.rsa_key_txt = tmp_path / 'synthetic-key-presence.txt'
    window.app_config.service.rsa_key_txt.write_text('synthetic presence marker only', encoding='utf8')
    assert not controller.starts
    window.settings_page.port_edit.setValue(31234)
    assert load_app_config(window.config_path).service.ws_port == 31234
    window.home_page.start_service_btn.click()
    assert controller.starts == [31234]
    assert window.home_page.start_service_btn.text() == '正在启动…'
    assert not window.home_page.start_service_btn.isEnabled()
    controller.lifecycle = gui_service.CaptureLifecycle.RUNNING
    window._update_service_status()
    assert window.home_page.start_service_btn.text() == '停止抓包'
    assert window.home_page.start_service_btn.isEnabled()
    window.settings_page.port_edit.setValue(31235)
    assert controller.running_config.ws_port == 31234
    window.home_page.start_service_btn.click()
    assert controller.stops == 1 and window._stop_pending
    assert window.home_page.start_service_btn.text() == '正在停止…'
    assert not window.home_page.start_service_btn.isEnabled()
    assert controller.starts == [31234]  # Never overlap capture services.
    window.records_page.return_live_btn.click()  # UI remains interactive.
    controller.running = False
    controller.lifecycle = gui_service.CaptureLifecycle.STOPPED
    window._finish_service_stop()
    assert controller.starts == [31234]  # Stopping never restarts automatically.
    window._auto_start_service()
    assert controller.starts == [31234]
    window.home_page.start_service_btn.click()
    assert controller.starts == [31234, 31235]
    assert window.overlay_manager.ws_port == 31235
    QTest.qWait(150)  # An old stop poll must not disable the new start.
    assert not window._stop_pending
    window.switchTo(window.home_page)
    QTest.qWait(350)
    assert window.grab().save(str(EVIDENCE / 'gui-home-service-controls.png'))
    window.switchTo(window.settings_page)
    QTest.qWait(350)
    assert window.grab().save(str(EVIDENCE / 'gui-settings-port.png'))


def test_controller_constructs_off_thread_and_does_not_reuse_generated_paths(monkeypatch, tmp_path):
    from endfield_pcap.gui_config import default_service_config
    config = default_service_config()
    created = []
    class Service:
        def __init__(self, config, observer):
            assert threading.current_thread() is not threading.main_thread()
            self.observer = observer
            assert config.trace_file is None and config.status_file is None
            config.trace_file = tmp_path / f'trace-{len(created)}.log'
            created.append(config)
        def set_full_analysis_required(self, required): pass
        async def run(self): pass
    monkeypatch.setattr(gui_service, 'DamageLogService', Service)
    controller = gui_service.ServiceController(config)
    for _ in range(2):
        controller.start()
        controller.join()
    assert len(created) == 2 and created[0] is not created[1]
    assert config.trace_file is None and config.status_file is None
    assert controller.queue.get_nowait() == ('stopped', None)
    assert controller.queue.get_nowait() == ('stopped', None)
