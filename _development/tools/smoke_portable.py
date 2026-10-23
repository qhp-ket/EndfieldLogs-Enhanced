"""Run with the packaged interpreter to check relocation, GUI and WebEngine.

Only the first-run game-directory dialog and global hotkey are bypassed. No
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

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme
    from endfield_pcap import gui_main
    from endfield_pcap.gui_config import load_app_config
    from endfield_pcap.gui_battle_detail import BattleDetailDialog


    def wait(condition, seconds=45):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            app.processEvents()
            if condition():
                return
            QTest.qWait(20)
        raise TimeoutError('Portable GUI smoke check timed out')


    def js(view, source):
        results=[]
        view.page.runJavaScript(source, lambda value: results.append(value))
        wait(lambda: bool(results))
        return results[0]


    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    setTheme(Theme.DARK)
    gui_main.MainWindow._ensure_game_directory_ready = lambda self: True
    gui_main.MainWindow._update_overlay_shortcut = lambda self: None
    gui_main.MainWindow._auto_start_service = lambda self: None
    config_path = launcher.PROFILE / 'settings.json'
    window = gui_main.MainWindow(load_app_config(config_path), config_path)
    window.setMicaEffectEnabled(False)
    window.show()
    window.switchTo(window.overlay_page)
    QTest.qWait(500)
    assert window.overlay_page.reset_layout_btn.isVisible()
    overlay = next(iter(window.overlay_manager._windows.values()))
    wait(lambda: overlay.webview.url().isLocalFile())
    result = dict(python=sys.version.split()[0], isolated=bool(sys.flags.isolated),
                  executable_inside_package=Path(sys.executable).resolve().is_relative_to(root),
                  gui_visible=window.isVisible(), overlay_visible=overlay.isVisible(),
                  web_console_errors=[], parsed_battle=None)
    assert result['isolated'] and result['executable_inside_package']
    if app.platformName() == 'windows':
        window.screen().grabWindow(int(window.winId())).save(str(output / 'main-gui.png'))
    else:
        window.grab().save(str(output / 'main-gui.png'))

    snapshot = {}
    if trace:
        from endfield_pcap.trace_import import load_trace_records
        from endfield_pcap.history_analysis import load_record_snapshot
        records = load_trace_records(trace)
        selected = next((row for row in records if row.record_index == 2), records[-1])
        snapshot = load_record_snapshot(selected)
        result['parsed_battle'] = {k: snapshot['battle'].get(k) for k in ('total_damage', 'duration_ms')}
        window.overlay_manager.show_history(snapshot, 'portable-smoke')
        QTest.qWait(500)
        damage=[]
        overlay.webview.page().runJavaScript('window.endfieldOverlay.snapshots.analysis_snapshot.snapshot.battle.total_damage', lambda value: damage.append(value))
        wait(lambda: bool(damage))
        assert damage[0] == snapshot['battle']['total_damage']

    dialog = BattleDetailDialog(snapshot, '便携包离线验证', window)
    dialog.show()
    dialog.view_mode_combo.setCurrentIndex(1)
    view = dialog.web_analysis
    wait(lambda: view.bridge.ready or bool(view.page.console_errors))
    assert not view.page.console_errors
    assert js(view, 'document.body.dataset.ready') == 'true'
    for tab in ('skills', 'enemy', 'timeline'):
        js(view, f'document.querySelector("[data-tab={tab}]").click()')
    QTest.qWait(400)
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
    from endfield_pcap.snapshot_process import SnapshotProcess
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
