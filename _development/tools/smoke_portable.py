"""Run with the packaged interpreter to check relocation, GUI and WebEngine.

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
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    trace = args.trace.resolve() if args.trace else None
    output.mkdir(parents=True, exist_ok=True)

    spec = importlib.util.spec_from_file_location('portable_launcher', root / 'launch_gui.py')
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    launcher.PROFILE = output / 'profile'
    assert launcher.main(['--check']) == 0

    from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
    from PySide6.QtGui import QFont, QKeyEvent
    from PySide6.QtWidgets import QApplication, QLabel, QMessageBox
    from qfluentwidgets import Slider, Theme, setTheme
    import endfield_pcap.gui.main as gui_main
    from endfield_pcap.gui.config import load_app_config
    from endfield_pcap.gui.battle.detail import BattleDetailDialog


    def wait(condition, seconds=45):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            time.sleep(0.02)
        raise TimeoutError('Portable GUI smoke check timed out')


    def js(view, source):
        results=[]
        page = view.page() if callable(view.page) else view.page
        page.runJavaScript(source, lambda value: results.append(value))
        wait(lambda: bool(results))
        return results[0]


    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont('Microsoft YaHei UI', 10))
    setTheme(Theme.DARK)
    gui_main.MainWindow._ensure_game_directory_ready = lambda self: True
    gui_main.MainWindow._update_overlay_shortcut = lambda self: None
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
    auto_start(window)
    auto_start(window)
    assert len(prompts) == 1 and not window.service_controller.is_running()
    assert window.isVisible() and window.home_page.start_service_btn.isEnabled()
    window.app_config.service.dll_dir = expected_game_exe.parent
    window._refresh_settings_page()
    window.switchTo(window.overlay_page)
    wait_until = time.monotonic()+0.5
    wait(lambda: time.monotonic() >= wait_until)
    assert window.overlay_page.reset_layout_btn.isVisible()
    overlay = next(iter(window.overlay_manager._windows.values()))
    wait(lambda: overlay.webview.url().isLocalFile())
    result = dict(python=sys.version.split()[0], isolated=bool(sys.flags.isolated),
                  executable_inside_package=Path(sys.executable).resolve().is_relative_to(root),
                  gui_visible=window.isVisible(), overlay_visible=overlay.isVisible(),
                  web_console_errors=[], parsed_battle=None,
                  default_game_exe=str(expected_game_exe), font_slider_verified=True,
                  missing_game_prompt_verified=True)
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
        wait(lambda: js(overlay.webview,
            'window.endfieldOverlay?.snapshots?.analysis_snapshot?.snapshot?.battle?.total_damage')
            == snapshot['battle']['total_damage'])

    dialog = BattleDetailDialog(snapshot, '便携包离线验证', window)
    dialog.show()
    dialog.view_mode_combo.setCurrentIndex(1)
    view = dialog.web_analysis
    wait(lambda: view.bridge.ready or bool(view.page.console_errors))
    assert not view.page.console_errors
    assert js(view, 'document.body.dataset.ready') == 'true'
    for tab in ('skills', 'enemy', 'timeline'):
        js(view, f'document.querySelector("[data-tab={tab}]").click()')
    wait_until = time.monotonic()+0.4
    wait(lambda: time.monotonic() >= wait_until)
    assert not view.page.console_errors
    dialog.grab().save(str(output / 'analysis-web.png'))
    result['web_blocks'] = len(view.bridge.model.blocks)
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
        result['analysis_worker_spawn'] = True
    finally:
        worker.close()
    result['capture_started'] = window.service_controller.is_running()
    assert not result['capture_started']
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    dialog.close()
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
