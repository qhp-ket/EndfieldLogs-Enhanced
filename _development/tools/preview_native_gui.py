"""Capture native GUI examples using a tracked synthetic trace and a disposable profile."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--platform', choices=('windows', 'offscreen'), default='offscreen')
    parser.add_argument('--theme', choices=('dark', 'light'), default='dark')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ['QT_QPA_PLATFORM'] = args.platform
    sys.path.insert(0, str(ROOT / '_internal/src'))
    from endfield_pcap.runtime.environment import configure_paths
    dll_handles = configure_paths(ROOT)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtTest import QTest
    from qfluentwidgets import setTheme
    from endfield_pcap.gui.main import MainWindow
    from endfield_pcap.gui.theme import _theme_from_mode
    from endfield_pcap.settings import AppConfig, default_service_config, default_overlay_entries

    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    cjk_font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if args.platform == 'offscreen' and cjk_font.is_file():
        QFontDatabase.addApplicationFont(str(cjk_font))
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    setTheme(_theme_from_mode(args.theme))
    config = AppConfig(default_service_config(), default_overlay_entries(),
                       theme_mode=args.theme, check_updates_on_start=False)
    # Preview owns no global shortcuts, so an active application can keep them.
    MainWindow._update_overlay_shortcut = lambda self: None
    MainWindow._update_gui_shortcut = lambda self, *args: None
    config.service.log_dir = output / 'logs'
    trace = output / 'synthetic.log'
    shutil.copyfile(ROOT / '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log', trace)
    window = MainWindow(config, output / 'profile/settings.json')
    window.setMicaEffectEnabled(False)
    window.resize(1280, 840)
    captures = []

    def wait(predicate):
        deadline = time.monotonic() + 30
        while not predicate():
            if time.monotonic() >= deadline:
                raise TimeoutError('Native preview did not reach the requested state')
            app.processEvents()
            time.sleep(.01)
        app.processEvents()

    def capture(widget, name):
        # This opt-in visual tool allows Fluent's page transition to settle.
        QTest.qWait(400)
        if args.platform == 'offscreen':
            widget.resize(1280, 840) if widget is window else widget.resize(1160, 760)
            QTest.qWait(100)
        app.processEvents()
        widget.repaint()
        path = output / f'{name}.png'
        if not widget.grab().save(str(path)):
            raise OSError('Cannot save ' + path.name)
        captures.append(path.name)

    try:
        window.show()
        wait(lambda: window.isVisible())
        window.history_presenter.import_files([trace])
        wait(lambda: not window.history_controller.import_pending and not window.history_controller.records_pending)
        window.switchTo(window.records_page)
        wait(lambda: window.records_page.isVisible())
        window.records_page.select_all_btn.click()
        capture(window, 'history-selection')
        window.records_page.load_overlay_btn.click()
        wait(lambda: not window.history_controller.busy)
        window.records_page.analysis_detail_btn.click()
        wait(lambda: window.history_presenter.dialog is not None)
        dialog = window.history_presenter.dialog
        for index, name in enumerate(('timeline', 'skills', 'enemies')):
            dialog.tabs.setCurrentIndex(index)
            capture(dialog, name)
        for page, name in ((window.home_page, 'home'), (window.overlay_page, 'overlay-settings')):
            window.switchTo(page)
            wait(lambda: page.isVisible())
            capture(window, name)
        result = dict(platform=args.platform, theme=args.theme, screenshots=captures,
                      source='tracked synthetic rdps_snapshot_contract.log',
                      records=len(window.history_controller.records))
        (output / 'preview.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        window.close()
        wait(lambda: window._close_ready)
        app.processEvents()


if __name__ == '__main__':
    main()
