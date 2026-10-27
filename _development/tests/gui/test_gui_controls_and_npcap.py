from PySide6.QtWidgets import QFileDialog, QMessageBox
import endfield_pcap.gui.pages.home.actions as capture_actions
"""Typography controls, state-driven Fluent switches, optional capture."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from qfluentwidgets import Slider, Theme, setTheme
from endfield_pcap.gui.shared.widgets import FluentSwitchButton
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import two_battles, wait_for
from app_test_support.ui.qt import EVIDENCE


@pytest.mark.parametrize('select_exe', [True, False])
def test_settings_game_path_selection_persists_without_restarting_capture(main_window, app, tmp_path, monkeypatch, select_exe):
    from endfield_pcap.settings import load_app_config
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


def test_gui_and_overlay_font_sliders(main_window, app):
    window = main_window
    slider = window.settings_page.gui_font_slider
    assert isinstance(slider, Slider)
    slider.setValue(137)
    assert window.app_config.gui_font_percent == 137
    assert window.settings_page.gui_font_value.text() == '137%'
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert window.app_config.gui_font_percent == 138
    QTest.keyClick(slider, Qt.Key.Key_Left)
    assert window.app_config.gui_font_percent == 137
    slider.setValue(180)
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert slider.value() == 180
    overlay = window.overlay_page.font_size_slider
    assert isinstance(overlay, Slider)
    overlay.setValue(125)
    QTest.keyClick(overlay, Qt.Key.Key_Right)
    assert window._selected_overlay().font_scale == 1.26
    assert window.overlay_page.font_size_value.text() == '126%'
    avatar = window.overlay_page.setting_widgets['avatar_size_percent']
    assert isinstance(avatar, Slider)
    avatar.setValue(175)
    assert window._selected_overlay().template_settings['avatar_size_percent'] == 175
    from endfield_pcap.settings import load_app_config
    saved = load_app_config(window.config_path)
    assert next(e for e in saved.overlays if e.id == window._selected_overlay().id).template_settings['avatar_size_percent'] == 175


def test_default_game_path_is_independent_of_application_directory(tmp_path, monkeypatch):
    from pathlib import Path
    from endfield_pcap.settings import codec as config
    monkeypatch.setattr(config, 'app_root', lambda: tmp_path / 'relocated app')
    fresh = config.load_app_config(tmp_path / 'fresh-settings.json')
    assert fresh.service.dll_dir / fresh.service.game_exe == Path(
        r'C:\Program Files\Hypergryph Launcher\games\Endfield Game\Endfield.exe')


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
    window.history_presenter.import_files([path])
    wait_for(lambda: not window.history_controller.import_pending, app)
    window.history_presenter.inspect_selected()
    wait_for(lambda: window.history_presenter.dialog is not None, app)
    assert window.history_presenter.dialog.snapshot['battle']['total_damage'] > 0
    monkeypatch.setattr(capture_actions, 'has_npcap', lambda: True)
    assert window._ensure_npcap_ready()
    assert window._npcap_infobar is None


@pytest.mark.parametrize('choice', ['exe', 'directory', 'defer', 'close'])
def test_missing_game_startup_prompts_once_and_allows_manual_setup_or_history(
        main_window, app, tmp_path, monkeypatch, choice):
    from endfield_pcap.settings import load_app_config
    window = main_window
    original = tmp_path / 'missing-game'
    window.app_config.start_capture_on_launch = True
    window.app_config.service.dll_dir = original
    directory = tmp_path / 'selected game'
    directory.mkdir()
    (directory / 'Endfield.exe').write_bytes(b'synthetic presence marker')
    (directory / 'GameAssembly.dll').write_bytes(b'synthetic presence marker')
    prompts, starts = [], []
    def answer(box):
        prompts.append(box.windowTitle())
        assert '未找到终末地' in box.windowTitle()
        assert str(original) in box.informativeText()
        assert '历史分析' in box.informativeText()
        # Reentry while a modal dialog runs must not schedule another start.
        window._auto_start_service()
        text = {'exe': '选择 Endfield.exe', 'directory': '选择游戏目录', 'defer': '暂不设置'}
        if choice == 'close':
            box.reject()
        else:
            next(button for button in box.buttons() if button.text() == text[choice]).click()
    monkeypatch.setattr(QMessageBox, 'exec', answer)
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(directory / 'Endfield.exe'), ''))
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: str(directory))
    monkeypatch.setattr(window, '_ensure_npcap_ready', lambda: True)
    key = tmp_path / 'synthetic-key-marker.pem'
    key.write_bytes(b'synthetic presence marker')
    window.app_config.service.rsa_key_txt = key
    monkeypatch.setattr(window.service_controller, 'start', lambda: starts.append(True))
    window._auto_start_service()
    window._auto_start_service()
    assert len(prompts) == 1
    assert window.isVisible() and window.home_page.start_service_btn.isEnabled()
    if choice in ('exe', 'directory'):
        assert starts == [True]
        assert load_app_config(window.config_path).service.dll_dir == directory
        assert window.settings_page.game_exe_edit.text() == str(directory / 'Endfield.exe')
    else:
        assert not starts
        assert window.app_config.service.dll_dir == original
        assert '历史分析' in window._capture_error
        assert window._game_dir_infobar is not None
