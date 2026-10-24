from PySide6.QtWidgets import QFileDialog, QMessageBox
import endfield_pcap.gui.pages.settings.paths as settings_paths
import endfield_pcap.gui.pages.home.actions as capture_actions
"""Discrete typography controls, state-driven Fluent switches, optional capture."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from qfluentwidgets import Theme, setTheme
import endfield_pcap.gui.main as gui_main
from endfield_pcap.gui.shared.widgets import FluentSwitchButton
from endfield_pcap.gui.shared.widgets import IntegerStepEdit
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import two_battles, wait_for
from app_test_support.ui.qt import EVIDENCE


@pytest.mark.parametrize('select_exe', [True, False])
def test_settings_game_path_selection_persists_without_restarting_capture(main_window, app, tmp_path, monkeypatch, select_exe):
    from endfield_pcap.gui.config import load_app_config
    window = main_window
    directory = tmp_path / 'new game location'
    directory.mkdir()
    (directory / 'Endfield.exe').write_bytes(b'test marker; never executed')
    (directory / 'GameAssembly.dll').write_bytes(b'test marker; never loaded')
    calls = []
    def choose_file(*args):
        calls.append('exe')
        return str(directory / 'Endfield.exe'), ''
    def choose_dir(*args):
        calls.append('directory')
        return str(directory)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', choose_file)
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', choose_dir)
    def forbidden(*args):
        raise AssertionError('changing a path must not start or stop capture')
    with monkeypatch.context() as scoped:
        scoped.setattr(window.service_controller, 'start', forbidden)
        scoped.setattr(window.service_controller, 'stop', forbidden)
        button = window.settings_page.game_exe_btn if select_exe else window.settings_page.game_dir_btn
        button.click()
    assert calls == (['exe'] if select_exe else ['directory'])
    assert window.app_config.service.dll_dir == directory.resolve()
    assert window.settings_page.game_exe_edit.text() == str(directory.resolve() / 'Endfield.exe')
    assert window.settings_page.game_exe_edit.isReadOnly()
    assert load_app_config(window.config_path).service.dll_dir == directory.resolve()
    window.switchTo(window.settings_page)
    QTest.qWait(120)
    assert window.settings_page.game_exe_btn.isVisible()
    assert window.settings_page.game_dir_btn.isVisible()
    if select_exe:
        assert window.grab().save(str(EVIDENCE / 'gui-settings-game-path.png'))


@pytest.mark.parametrize('selection', ['cancel', 'wrong_exe', 'missing_dll'])
def test_invalid_or_cancelled_game_exe_selection_preserves_saved_path(main_window, tmp_path, monkeypatch, selection):
    window = main_window
    original = window.app_config.service.dll_dir
    directory = tmp_path / 'invalid selection'
    directory.mkdir()
    (directory / 'Endfield.exe').write_bytes(b'test marker')
    if selection == 'wrong_exe':
        (directory / 'launcher.exe').write_bytes(b'test marker')
        (directory / 'GameAssembly.dll').write_bytes(b'test marker')
    selected = '' if selection == 'cancel' else str(directory / ('launcher.exe' if selection == 'wrong_exe' else 'Endfield.exe'))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a: (selected, ''))
    warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: warnings.append(a))
    window.settings_page.game_exe_btn.click()
    assert window.app_config.service.dll_dir == original
    assert bool(warnings) == (selection != 'cancel')


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
    from endfield_pcap.gui.shared.typography import apply_fonts
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
    monkeypatch.setattr(capture_actions, 'has_npcap', lambda: False)
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
    monkeypatch.setattr(capture_actions, 'has_npcap', lambda: True)
    assert window._ensure_npcap_ready()
    assert window._npcap_infobar is None


def test_startup_without_npcap_skips_game_directory_wizard(app, tmp_path, monkeypatch):
    from endfield_pcap.gui.config import AppConfig
    from endfield_pcap.gui.config import default_service_config
    config = AppConfig(service=default_service_config())
    monkeypatch.setattr(gui_main, 'load_app_config', lambda path: config)
    monkeypatch.setattr(capture_actions, 'has_npcap', lambda: False)
    monkeypatch.setattr(capture_actions, '_is_valid_game_dir', lambda path: False)
    def forbidden(*args):
        raise AssertionError('offline GUI must not require the game-directory wizard')
    monkeypatch.setattr(settings_paths, '_run_game_directory_wizard', forbidden)
    shown = []
    from types import SimpleNamespace
    monkeypatch.setattr(gui_main, 'MainWindow', lambda *args: SimpleNamespace(show=lambda: shown.append(True)))
    monkeypatch.setattr(app, 'exec', lambda: 0)
    assert gui_main.run_gui(tmp_path/'settings.json') == 0
    assert shown == [True]
