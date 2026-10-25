from app_test_support.paths import ROOT
import endfield_pcap.gui.pages.home.actions as capture_actions
"""Capture lifecycle, offline GUI and detached-launch failure reporting."""
import asyncio
import importlib.util
import logging
from pathlib import Path
import threading
import json
import time
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
import endfield_pcap.gui.service as gui_service
from endfield_pcap.gui.config import default_service_config
from endfield_pcap.gui.service import CaptureLifecycle
from endfield_pcap.models import ServiceState
from app_test_support.ui.window import main_window
from app_test_support.ui.qt import EVIDENCE
from app_test_support.scenarios.trace import two_battles, wait_for


def test_controller_waits_for_ready_and_cleanup_before_stopped(monkeypatch, tmp_path):
    constructed = threading.Event()
    ready = threading.Event()
    cleanup = threading.Event()
    release_cleanup = threading.Event()
    class Service:
        def __init__(self, config, observer):
            self.observer = observer
            self.loop = None
            self.stop_requested = threading.Event()
            constructed.set()
        def set_full_analysis_required(self, required): pass
        def request_stop(self): self.stop_requested.set()
        async def run(self):
            while not ready.is_set():
                await asyncio.sleep(.001)
            self.observer.on_state_change(ServiceState.WAITING_GAME, None, None)
            while not self.stop_requested.is_set():
                await asyncio.sleep(.001)
            cleanup.set()
            while not release_cleanup.is_set():
                await asyncio.sleep(.001)
    monkeypatch.setattr(gui_service, 'DamageLogService', Service)
    controller = gui_service.ServiceController(default_service_config())
    try:
        controller.start()
        assert constructed.wait(2)
        assert controller.lifecycle == CaptureLifecycle.STARTING
        ready.set()
        assert controller.queue.get(timeout=2)[0] == 'state'
        assert controller.lifecycle == CaptureLifecycle.RUNNING
        controller.stop()
        assert cleanup.wait(2)
        assert controller.lifecycle == CaptureLifecycle.STOPPING
        assert controller.is_running()
        controller.start()  # Cannot overlap the old cleanup.
        assert controller.lifecycle == CaptureLifecycle.STOPPING
        release_cleanup.set()
        controller.join()
        assert controller.lifecycle == CaptureLifecycle.STOPPED
        assert not controller.is_running()
        assert controller.queue.get(timeout=2) == ('stopped', None)
    finally:
        ready.set(); release_cleanup.set(); controller.stop(); controller.join()


def test_stop_during_construction_survives_late_ready_callback(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    stopped = threading.Event()
    class Service:
        def __init__(self, config, observer):
            self.observer = observer
            self.loop = None
            entered.set()
            assert release.wait(3)
        def set_full_analysis_required(self, required): pass
        def request_stop(self): stopped.set()
        async def run(self):
            self.observer.on_state_change(ServiceState.WAITING_GAME, None, None)
            while not stopped.is_set():
                await asyncio.sleep(.001)
    monkeypatch.setattr(gui_service, 'DamageLogService', Service)
    controller = gui_service.ServiceController(default_service_config())
    try:
        controller.start()
        assert entered.wait(2)
        controller.stop()
        assert controller.lifecycle == CaptureLifecycle.STOPPING
        release.set()
        controller.join()
        assert stopped.is_set()
        assert controller.lifecycle == CaptureLifecycle.STOPPED
        assert not controller.is_running()
    finally:
        release.set(); controller.stop(); controller.join()


def test_waiting_game_readiness_without_state_change_becomes_running(monkeypatch):
    class Service:
        def __init__(self, config, observer):
            self.observer = observer
            self.started = threading.Event()
            self.stopped = threading.Event()
        def set_full_analysis_required(self, required): pass
        def wait_started(self, timeout): return self.started.wait(timeout)
        def request_stop(self): self.stopped.set()
        async def run(self):
            self.started.set()  # Initial WAITING_GAME produces no state change.
            while not self.stopped.is_set():
                await asyncio.sleep(.001)
    monkeypatch.setattr(gui_service, 'DamageLogService', Service)
    controller = gui_service.ServiceController(default_service_config())
    try:
        controller.start()
        assert controller.queue.get(timeout=2) == ('started', None)
        assert controller.lifecycle == CaptureLifecycle.RUNNING
    finally:
        controller.stop(); controller.join()
    assert controller.lifecycle == CaptureLifecycle.STOPPED


def test_startup_failure_does_not_become_stopped_until_cleanup_finishes(monkeypatch):
    cleaning = threading.Event()
    release = threading.Event()
    class Service:
        def __init__(self, config, observer): self.observer = observer
        def set_full_analysis_required(self, required): pass
        async def run(self):
            try:
                raise OSError('port is occupied')
            finally:
                cleaning.set()
                while not release.is_set():
                    await asyncio.sleep(.001)
    monkeypatch.setattr(gui_service, 'DamageLogService', Service)
    controller = gui_service.ServiceController(default_service_config())
    try:
        controller.start()
        assert cleaning.wait(2)
        assert controller.lifecycle == CaptureLifecycle.STARTING
        assert controller.queue.empty()
        release.set(); controller.join()
        assert controller.lifecycle == CaptureLifecycle.STOPPED
        assert controller.queue.get(timeout=2)[0] == 'error'
        assert controller.queue.get(timeout=2) == ('stopped', None)
    finally:
        release.set(); controller.join()


def test_one_automatic_attempt_and_waiting_game_is_stoppable(main_window, monkeypatch, tmp_path, app):
    window = main_window
    window.app_config.start_capture_on_launch = True
    controller = window.service_controller
    starts = []
    key = tmp_path / 'synthetic-presence-only.pem'
    key.write_text('synthetic marker', encoding='utf8')
    window.app_config.service.rsa_key_txt = key
    monkeypatch.setattr(window, '_ensure_npcap_ready', lambda: True)
    monkeypatch.setattr(capture_actions, '_is_valid_game_dir', lambda path: True)
    monkeypatch.setattr(controller, 'start', lambda: starts.append(True))
    window._auto_start_service(); window._auto_start_service()
    assert starts == [True]
    for state in ServiceState:
        controller._lifecycle = CaptureLifecycle.RUNNING
        monkeypatch.setattr(controller, 'is_running', lambda: True)
        window.current_state = state
        window._update_service_status()
        assert window.home_page.start_service_btn.text() == '停止抓包'
        assert window.home_page.start_service_btn.isEnabled()
    controller._lifecycle = CaptureLifecycle.STOPPED
    monkeypatch.setattr(controller, 'is_running', lambda: False)
    window._finish_service_stop()
    window._auto_start_service()
    assert starts == [True]
    window._update_service_status()
    window.switchTo(window.home_page); QTest.qWait(120)
    assert window.grab().save(str(EVIDENCE / 'gui-capture-stopped.png'))


@pytest.mark.parametrize('missing', ['npcap', 'key', 'directory'])
def test_missing_prerequisite_retains_history(main_window, missing, monkeypatch, app, tmp_path):
    window = main_window
    window.app_config.start_capture_on_launch = True
    monkeypatch.setattr(capture_actions, 'has_npcap', lambda: missing != 'npcap')
    monkeypatch.setattr(capture_actions, '_is_valid_game_dir', lambda path: missing != 'directory')
    monkeypatch.setattr(capture_actions, '_run_game_directory_wizard', lambda *args: False)
    key = tmp_path / 'synthetic-presence-only.pem'
    if missing != 'key':
        key.write_text('synthetic marker', encoding='utf8')
    window.app_config.service.rsa_key_txt = key
    monkeypatch.setattr(window.service_controller, 'start', lambda: pytest.fail('must remain offline'))
    window._auto_start_service()
    assert window.home_page.start_service_btn.text() == '启动抓包'
    assert window.home_page.start_service_btn.isEnabled()
    assert window._capture_error
    source = tmp_path / 'trace_20261023-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    window._inspect_selected_history()
    wait_for(lambda: window._history_detail_dialog is not None, app)
    assert window._history_detail_dialog.snapshot['battle']['total_damage'] > 0


def test_logs_collect_off_page_copy_clear_only_display_and_open_folder(main_window, app, tmp_path, monkeypatch):
    window = main_window
    page = window.logs_page
    page.log_directory = tmp_path / 'runtime-logs'
    page.log_directory.mkdir()
    disk = page.log_directory / 'launcher.log'
    disk.write_text('keep this file', encoding='utf8')
    window.switchTo(window.home_page)
    logging.getLogger(__name__).warning('background runtime log')
    window._drain_queue()
    assert 'background runtime log' in '\n'.join(page._lines)
    assert page.log_view.toPlainText() == ''  # Off-page logs don't relayout Qt text.
    page.copy_btn.click()
    assert 'background runtime log' in QApplication.clipboard().text()
    opened = []
    monkeypatch.setattr('endfield_pcap.gui.pages.logs.view.QDesktopServices.openUrl', lambda url: opened.append(url.toLocalFile()))
    page.open_folder_btn.click()
    assert Path(opened[0]) == page.log_directory
    page.clear_btn.click()
    assert page.log_view.toPlainText() == ''
    assert disk.read_text(encoding='utf8') == 'keep this file'
    logging.getLogger(__name__).warning('after clear')
    window._drain_queue()
    assert 'after clear' in '\n'.join(page._lines)
    for i in range(900): page.append_log(f'line {i}')
    assert len(page._lines) == 800
    page.flush_display()
    assert page.log_view.document().blockCount() == 800
    window.switchTo(page); QTest.qWait(120)
    assert window.grab().save(str(EVIDENCE / 'gui-runtime-logs.png'))
    window._apply_gui_theme('light')
    QTest.qWait(100)
    assert window.grab().save(str(EVIDENCE / 'gui-runtime-logs-light.png'))


def launcher(tmp_path):
    spec = importlib.util.spec_from_file_location('isolated_gui_launcher', ROOT / 'launch_gui.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PROFILE = tmp_path / 'profile'
    return module


def test_detached_launcher_passes_arguments_and_logs_native_output(tmp_path, monkeypatch):
    launch = launcher(tmp_path)
    calls = []
    def spawn(args, **kwargs):
        calls.append((args, kwargs))
        Path(kwargs['env']['ENDFIELD_GUI_READY_FILE']).touch()
    monkeypatch.setattr(launch.subprocess, 'Popen', spawn)
    monkeypatch.setattr(launch, 'bootstrap', lambda: pytest.fail('parent must not initialize GUI'))
    assert launch.main(['--detach', '--ws-port', '31234']) == 0
    args, options = calls[0]
    assert args[-2:] == ['--ws-port', '31234']
    assert '--detach' not in args
    assert Path(args[0]).name.lower() in {'pythonw.exe', 'python.exe'}
    assert options['creationflags'] == launch.subprocess.CREATE_NO_WINDOW
    assert Path(options['stderr'].name).name == 'launcher-stdio.log'
    assert options['stdout'] is options['stderr']


def test_startup_exception_shows_brief_message_with_log_path(tmp_path, monkeypatch):
    launch = launcher(tmp_path)
    monkeypatch.setattr(launch, 'bootstrap', lambda: None)
    monkeypatch.setattr(launch.importlib, 'import_module', lambda name: (_ for _ in ()).throw(ImportError('missing Qt')))
    shown = []
    monkeypatch.setattr(launch, 'show_startup_error', shown.append)
    assert launch.main([]) == 1
    assert len(shown) == 1 and 'missing Qt' in shown[0]
    assert 'missing Qt' in (launch.PROFILE / 'logs/launcher.log').read_text(encoding='utf8')


def test_detached_launcher_keeps_isolated_environment_flag(tmp_path, monkeypatch):
    from types import SimpleNamespace
    launch = launcher(tmp_path)
    monkeypatch.setattr(launch, 'sys', SimpleNamespace(
        executable=launch.sys.executable, platform=launch.sys.platform,
        flags=SimpleNamespace(isolated=True)))
    calls = []
    def spawn(command, **kwargs):
        calls.append(command)
        Path(kwargs['env']['ENDFIELD_GUI_READY_FILE']).touch()
    monkeypatch.setattr(launch.subprocess, 'Popen', spawn)
    assert launch.launch_detached([]) == 0
    assert calls[0][1:3] == ['-I', '-B']


def test_actual_windowless_child_waits_for_ready_but_not_shutdown_and_has_no_console(tmp_path, monkeypatch):
    launch = launcher(tmp_path)
    child = tmp_path / 'windowless_probe.py'
    child.write_text('''import ctypes, json, os, pathlib, time
root = pathlib.Path(__file__).parent
time.sleep(.3)
(root / "result.json").write_text(json.dumps({"console": bool(ctypes.windll.kernel32.GetConsoleWindow())}), encoding="utf8")
pathlib.Path(os.environ['ENDFIELD_GUI_READY_FILE']).touch()
deadline = time.monotonic() + 8
while not (root / "release").exists() and time.monotonic() < deadline:
    time.sleep(.01)
(root / "stopped").touch()
''', encoding='utf8')
    monkeypatch.setattr(launch, '__file__', str(child))
    monkeypatch.setattr(launch, 'ROOT', tmp_path)
    try:
        started = time.monotonic()
        assert launch.launch_detached([]) == 0
        assert time.monotonic()-started >= .3
        assert json.loads((tmp_path / 'result.json').read_text(encoding='utf8')) == {'console': False}
        assert not (tmp_path / 'stopped').exists()
    finally:
        (tmp_path / 'release').touch()
    deadline = time.monotonic() + 5
    while not (tmp_path / 'stopped').exists() and time.monotonic() < deadline:
        time.sleep(.01)
    assert (tmp_path / 'stopped').exists()


@pytest.mark.parametrize('exit_code', [0, 2])
def test_child_exit_before_window_is_startup_failure(tmp_path, monkeypatch, capsys, exit_code):
    from types import SimpleNamespace
    launch = launcher(tmp_path)
    monkeypatch.setattr(launch.subprocess, 'Popen', lambda *args, **kwargs: SimpleNamespace(poll=lambda: exit_code))
    assert launch.launch_detached([]) == (exit_code or 1)
    output = capsys.readouterr().out
    assert '正在打开 GUI' in output and 'launcher.log' in output
    assert not list((launch.PROFILE/'logs').glob('startup-*'))


def test_gui_reports_ready_after_window_is_exposed(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QWidget
    import endfield_pcap.gui.main as gui_main
    from endfield_pcap.gui.config import AppConfig, save_app_config
    config = tmp_path/'settings.json'
    save_app_config(AppConfig(service=default_service_config()), config)
    windows, states = [], []
    class ProbeWindow(QWidget):
        def __init__(self, *args):
            super().__init__()
            windows.append(self)
    monkeypatch.setattr(gui_main, 'MainWindow', ProbeWindow)
    def ready():
        window = windows[0]
        states.append((window.isVisible(), window.windowHandle().isExposed()))
        window.close()
        app.quit()
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(app.quit)
    timer.start(5000)
    try:
        assert gui_main.run_gui(config_path=config, on_ready=ready) == 0
        assert states == [(True, True)]
    finally:
        timer.stop()
        for window in windows:
            window.close()


def test_native_startup_dialog_includes_log_location(tmp_path, monkeypatch):
    import ctypes
    launch = launcher(tmp_path)
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, 'MessageBoxW', lambda *args: calls.append(args))
    launch.show_startup_error('missing Qt')
    assert 'missing Qt' in calls[0][1]
    assert str(launch.PROFILE / 'logs/launcher.log') in calls[0][1]


def test_check_does_not_detach_or_show_error_dialog(tmp_path, monkeypatch):
    launch = launcher(tmp_path)
    monkeypatch.setattr(launch, 'bootstrap', lambda: None)
    monkeypatch.setattr(launch, 'launch_detached', lambda *args: pytest.fail('check must be synchronous'))
    monkeypatch.setattr(launch.importlib, 'import_module', lambda name: (_ for _ in ()).throw(ImportError('missing Qt')))
    monkeypatch.setattr(launch, 'show_startup_error', lambda *args: pytest.fail('check must stay in console'))
    assert launch.main(['--detach', '--check']) == 1
