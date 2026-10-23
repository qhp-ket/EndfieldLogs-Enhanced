"""Discrete typography controls, state-driven Fluent switches, optional capture."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from qfluentwidgets import Theme, setTheme

from endfield_pcap import gui_main
from endfield_pcap.gui_widgets import FluentSwitchButton, IntegerStepEdit
from test_overlay_controls import main_window
from test_trace_import import two_battles, wait_for
from test_qt_snapshot_bridge import EVIDENCE


def test_global_and_overlay_fonts_accept_integer_input_and_increment_buttons(main_window, app):
    window = main_window
    editor = window.settings_page.gui_font_edit
    assert isinstance(editor, IntegerStepEdit)
    editor.edit.setText('137')
    QTest.keyClick(editor.edit, Qt.Key.Key_Return)
    assert window.app_config.gui_font_percent == 137
    editor.increase_button.click()
    assert window.app_config.gui_font_percent == 138
    editor.decrease_button.click()
    assert window.app_config.gui_font_percent == 137
    editor.setValue(180)
    assert not editor.increase_button.isEnabled()
    overlay = window.overlay_page.font_size_edit
    overlay.setValue(125)
    overlay.increase_button.click()
    assert window._selected_overlay().font_scale == 1.26


def test_switch_knob_draws_current_state_with_blocked_signals_and_large_fonts(app):
    from endfield_pcap.gui_typography import apply_fonts
    for mode in (Theme.LIGHT, Theme.DARK):
        setTheme(mode)
        switch = FluentSwitchButton()
        switch.setOnText('开'); switch.setOffText('关')
        switch.show()
        try:
            apply_fonts(switch, 1.8)
            # Exercise the exact problematic case: state changes while signals
            # are blocked. The animation property cannot update the knob.
            switch.indicator.blockSignals(True)
            switch.indicator.setChecked(True)
            switch.indicator.blockSignals(False)
            switch._updateText()
            app.processEvents()
            indicator = switch.indicator
            image = indicator.grab().toImage()
            factor = image.devicePixelRatio()
            center = image.pixelColor(round((indicator.width()-11)*factor), round(indicator.height()/2*factor))
            expected = indicator._sliderColor()
            assert abs(center.red()-expected.red()) < 5
            switch.grab().save(str(EVIDENCE / f'switch-{mode.value}-on.png'))
            switch.setChecked(False); app.processEvents()
            image = indicator.grab().toImage()
            center = image.pixelColor(round(11*factor), round(indicator.height()/2*factor))
            # Off knobs have alpha; they must remain visible on either theme.
            assert center.alpha() > 0
            switch.grab().save(str(EVIDENCE / f'switch-{mode.value}-off.png'))
            assert indicator.size().width() == 42 and indicator.size().height() == 22
        finally:
            switch.close(); switch.deleteLater(); app.processEvents()


def test_missing_npcap_warns_in_gui_and_console_but_history_still_works(main_window, app, tmp_path, monkeypatch, caplog):
    window = main_window
    monkeypatch.setattr(gui_main, 'has_npcap', lambda: False)
    started = []
    monkeypatch.setattr(window.service_controller, 'start', lambda: started.append(True))
    assert not window._ensure_npcap_ready()
    bar = window._npcap_infobar
    assert bar.titleLabel.text() == '缺少 Npcap'
    assert '本地日志' in bar.contentLabel.text()
    assert '未检测到 Npcap' in caplog.text
    window._start_service_if_needed()
    assert not started
    assert window._npcap_infobar is bar
    path = tmp_path / 'trace_20261022-100000.log'
    path.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([path])
    wait_for(lambda: not window._trace_import_pending, app)
    window._inspect_selected_history()
    wait_for(lambda: window._history_detail_dialog is not None, app)
    assert window._history_detail_dialog.snapshot['battle']['total_damage'] > 0
    monkeypatch.setattr(gui_main, 'has_npcap', lambda: True)
    assert window._ensure_npcap_ready()
    assert window._npcap_infobar is None


def test_startup_without_npcap_skips_game_directory_wizard(app, tmp_path, monkeypatch):
    from endfield_pcap.gui_config import AppConfig, default_service_config
    config = AppConfig(service=default_service_config())
    monkeypatch.setattr(gui_main, 'load_app_config', lambda path: config)
    monkeypatch.setattr(gui_main, 'has_npcap', lambda: False)
    monkeypatch.setattr(gui_main, '_is_valid_game_dir', lambda path: False)
    def forbidden(*args):
        raise AssertionError('offline GUI must not require the game-directory wizard')
    monkeypatch.setattr(gui_main, '_run_game_directory_wizard', forbidden)
    shown = []
    from types import SimpleNamespace
    monkeypatch.setattr(gui_main, 'MainWindow', lambda *args: SimpleNamespace(show=lambda: shown.append(True)))
    monkeypatch.setattr(app, 'exec', lambda: 0)
    assert gui_main.run_gui(tmp_path/'settings.json') == 0
    assert shown == [True]
