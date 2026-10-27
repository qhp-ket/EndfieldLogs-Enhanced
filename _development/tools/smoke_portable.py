"""Run with the packaged interpreter to check relocation, native GUI and process isolation.

Automatic capture and the global hotkey are bypassed. No
capture, upload or account login is started. Verification uses its own profile.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--trace', type=Path)
    parser.add_argument('--use-app-profile', action='store_true')
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    trace = args.trace.resolve() if args.trace else None
    output.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location('portable_launcher', root / 'launch_gui.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    launcher.PROFILE = root / '.dev-gui' if args.use_app_profile else output / 'profile'
    assert launcher.main(['--check']) == 0

    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
    from PySide6.QtGui import QFont, QKeyEvent
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    from qfluentwidgets import Slider, Theme, setTheme
    import endfield_pcap.gui.main as gui_main
    from endfield_pcap.settings import load_app_config
    from endfield_pcap.gui.battle.presenter import BattleDetailPresenter


    def wait(condition, seconds=45):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.02)
        raise TimeoutError('Portable GUI smoke check timed out')


    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont('Microsoft YaHei UI', 10))
    setTheme(Theme.DARK)
    gui_main.MainWindow._ensure_game_directory_ready = lambda self: True
    gui_main.MainWindow._update_overlay_shortcut = lambda self: None
    gui_main.MainWindow._schedule_update_check = lambda self: None
    auto_start = gui_main.MainWindow._auto_start_service
    gui_main.MainWindow._auto_start_service = lambda self: None
    config_path = launcher.PROFILE / 'settings.json'
    window = gui_main.MainWindow(load_app_config(config_path), config_path)
    window.setMicaEffectEnabled(False)
    window.show()
    window.switchTo(window.settings_page)
    expected_game_exe = Path(r'C:\Program Files\Hypergryph Launcher\games\Endfield Game\Endfield.exe')
    assert Path(window.settings_page.game_exe_edit.text()) == expected_game_exe
    slider = window.settings_page.gui_font_slider
    assert isinstance(slider, Slider) and slider.orientation() == Qt.Orientation.Horizontal
    original_percent = slider.value()
    slider.setValue(137)
    app.sendEvent(slider, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    assert window.app_config.gui_font_percent == 138
    assert window.settings_page.gui_font_value.text() == '138%'
    assert load_app_config(config_path).gui_font_percent == 138
    slider.setValue(original_percent)
    app.processEvents()
    window.grab().save(str(output / 'settings-font-and-game-path.png'))
    # Exercise the real missing-game prompt, including its safe offline choice.
    # This directory cannot contain a game, even on a machine with it installed.
    window.app_config.service.dll_dir = output / 'missing-game'
    prompts = []
    def defer_game_setup():
        box = app.activeModalWidget()
        assert isinstance(box, QMessageBox)
        assert 'Endfield.exe' in box.text() and '历史分析' in box.informativeText()
        information = box.findChild(QLabel, 'qt_msgbox_informativelabel')
        assert information is not None
        assert information.height() >= information.heightForWidth(information.width())
        box.grab().save(str(output / 'missing-game-prompt.png'))
        prompts.append(box.windowTitle())
        next(button for button in box.buttons() if button.text() == '暂不设置').click()
    QTimer.singleShot(0, defer_game_setup)
    assert not window.app_config.start_capture_on_launch
    window.app_config.start_capture_on_launch = True
    auto_start(window)
    auto_start(window)
    assert len(prompts) == 1 and not window.service_controller.is_running()
    assert window.isVisible() and window.home_page.start_service_btn.isEnabled()
    window.app_config.service.dll_dir = expected_game_exe.parent
    window.app_config.start_capture_on_launch = False
    window._refresh_settings_page()
    window.switchTo(window.overlay_page)
    wait_until = time.monotonic()+0.5
    wait(lambda: time.monotonic() >= wait_until)
    assert window.overlay_page.reset_layout_btn.isVisible()
    overlay = next(iter(window.overlay_manager._windows.values()))
    assert overlay.canvas.modules and not overlay.canvas.grab().isNull()
    result = dict(python=sys.version.split()[0], isolated=bool(sys.flags.isolated),
                  executable_inside_package=Path(sys.executable).resolve().is_relative_to(root),
                  gui_visible=window.isVisible(), overlay_visible=overlay.isVisible(),
                  parsed_battle=None,
                  default_game_exe=str(expected_game_exe), font_slider_verified=True,
                  missing_game_prompt_verified=True)
    from endfield_pcap.data.avatars import ROOT as portraits_root, manifest, avatar_path
    from PySide6.QtGui import QImage
    assert portraits_root.is_relative_to(root)
    portraits = manifest()['portraits']
    assert len(portraits) >= 35
    assert all(QImage(str(avatar_path(key))).width() == 128 for key in portraits)
    result['offline_portrait_count'] = len(portraits)
    assert not window.app_config.start_capture_on_launch
    assert window.settings_page.update_status.text() == '未检测到新版'
    assert result['isolated'] and result['executable_inside_package']
    if app.platformName() == 'windows':
        window.screen().grabWindow(int(window.winId())).save(str(output / 'main-gui.png'))
    else:
        window.grab().save(str(output / 'main-gui.png'))

    snapshot = {}
    if trace:
        from endfield_pcap.history.importer import load_trace_records
        from endfield_pcap.history.analysis import load_record_snapshot
        records = load_trace_records(trace)
        selected = next((row for row in records if row.record_index == 2), records[-1])
        snapshot = load_record_snapshot(selected)
        result['parsed_battle'] = {k: snapshot['battle'].get(k) for k in ('total_damage', 'duration_ms')}
        window.overlay_manager.show_history(snapshot, 'portable-smoke')
        wait_until = time.monotonic()+0.5
        wait(lambda: time.monotonic() >= wait_until)
        wait(lambda: overlay.canvas.modules[0].snapshot['battle']['total_damage'] == snapshot['battle']['total_damage'])

    from dataclasses import replace
    for entry in window.app_config.overlays:
        window.overlay_manager.apply_entry(replace(entry, enabled=True))
    app.processEvents()
    kinds = {host.canvas.template.modules[0]['type'] for host in window.overlay_manager._windows.values()}
    assert kinds == {'damage', 'combo_skill', 'uid_mask'}, kinds
    for host in window.overlay_manager._windows.values():
        host.canvas.grab().save(str(output / ('overlay-'+host.canvas.template.modules[0]['type']+'.png')))
        if host.canvas.template.modules[0]['type'] in {'damage', 'combo_skill'}:
            from endfield_pcap.overlays.templates import with_template_value
            host.apply_entry(with_template_value(host.entry, 'theme', 'endfield'))
            app.processEvents()
            assert host.canvas.modules[0].settings['theme'] == 'endfield'
            assert host.canvas.grab().save(str(output / ('overlay-'+host.canvas.template.modules[0]['type']+'-endfield.png')))
    result['native_overlays'] = sorted(kinds)
    result['native_skin_verified'] = 'endfield'
    dialog = BattleDetailPresenter.create(snapshot, '合成战斗', window.settings_store, parent=window)
    dialog.show()
    for tab in range(dialog.tabs.count()):
        dialog.tabs.setCurrentIndex(tab)
        app.processEvents()
        assert dialog.grab().save(str(output / f'analysis-native-{tab}.png'))
    dialog.tabs.setCurrentIndex(0)
    dialog.buff_check.setChecked(True)
    dialog.details_toggle.setChecked(True)
    for tab in range(dialog.inspector.count()):
        dialog.inspector.setCurrentIndex(tab)
        app.processEvents()
    assert dialog.curve_combo.currentData() == 'rdmg'
    result['native_blocks'] = dialog.timeline.drawn_blocks
    result['native_analysis_pages'] = dialog.tabs.count()
    dialog._show_summary()
    app.processEvents()
    assert dialog._summary_dialog.tabs.count() == 2
    dialog._summary_dialog.grab().save(str(output / 'analysis-native-summary.png'))
    dialog._summary_dialog.close()
    import psutil
    checked_processes = set()
    def verify_native_tree():
        assert not any('QtWebEngine' in name or 'QtWebChannel' in name for name in sys.modules)
        tree = [psutil.Process(), *psutil.Process().children(recursive=True)]
        for process in tree:
            assert 'webengine' not in process.name().lower()
            libraries = [region.path.lower() for region in process.memory_maps()]
            assert not any('qt6webengine' in path or 'qt6webchannel' in path for path in libraries)
            checked_processes.add(process.pid)
    verify_native_tree()
    result['browser_processes'] = 0
    # An isolated ._pth must not borrow anything from the developer's Python/site.
    external = []
    for name, module in sys.modules.items():
        location = getattr(module, '__file__', None)
        if location and name not in {__name__, 'portable_launcher'}:
            if not Path(location).resolve().is_relative_to(root):
                external.append(name)
    assert not external, external
    result['external_modules'] = external
    from endfield_pcap.analysis.live.process import SnapshotProcess
    worker = SnapshotProcess()
    try:
        # A real spawn must work with the isolated interpreter and resource paths.
        worker.calculate(0)
        assert worker.last_metrics and worker.process.is_alive()
        verify_native_tree()
        result['analysis_worker_spawn'] = True
    finally:
        worker.close()
    result['capture_started'] = window.service_controller.is_running()
    assert not result['capture_started']
    # Exercise the packaged native receivers in their own process; the real
    # game is not selected, so no foreground user input is collected here.
    from endfield_pcap.inputlog.controller import InputController
    inputs=InputController()
    inputs.start(output/'missing-game/Endfield.exe',output/'input-smoke')
    try:
        wait(lambda:inputs.snapshot()['status'] not in ('starting','stopped'))
        input_status=inputs.snapshot()
        assert input_status['status']=='waiting_game',input_status
        assert not input_status.get('errors'),input_status
        verify_native_tree()
    finally:
        inputs.stop(wait=True)
    sidecars=list((output/'input-smoke').rglob('*.input.jsonl'))
    assert len(sidecars)==1
    events=[json.loads(line) for line in sidecars[0].read_text(encoding='utf8').splitlines()]
    assert any(row['type']=='end' for row in events)
    assert not any(row['type']=='input' for row in events)
    result['input_native_process_verified']=not inputs.running
    from PySide6.QtMultimedia import QWindowCapture,QMediaCaptureSession,QVideoSink
    from endfield_pcap.vision.controller import VisionController
    visual=VisionController(output/'missing-game/Endfield.exe',parent=window)
    try:
        visual.set_enabled(True)
        wait(lambda:visual._latest is not None)
        visual_state=visual.take_snapshot()
        assert visual_state is not None
        assert '不可用' not in visual_state['snapshot']['status'],visual_state
        result['multimedia_worker_verified']=True
        verify_native_tree()
    finally:
        visual.stop()
        wait(lambda: not visual.is_running())
    result['native_processes_checked'] = len(checked_processes)
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    dialog.close()
    window.close()
    wait(lambda: window._close_ready)
    app.processEvents()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
