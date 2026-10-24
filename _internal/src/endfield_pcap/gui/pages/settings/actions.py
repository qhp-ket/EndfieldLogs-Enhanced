from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox
from endfield_pcap.gui.config import save_app_config
from endfield_pcap.gui.resources import ROOT
from endfield_pcap.gui.pages.settings.paths import (
    _is_valid_game_dir,
    _select_game_directory_from_dialog,
)


def _directory_size(path: Path) -> int:
    total = 0
    try:
        if not path.exists():
            return 0
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


class SettingsActions:
    def _refresh_settings_page(self) -> None:
        self.settings_page.gui_font_edit.blockSignals(True)
        self.settings_page.gui_font_edit.setValue(self.app_config.gui_font_percent)
        self.settings_page.gui_font_edit.blockSignals(False)
        self.settings_page.port_edit.blockSignals(True)
        self.settings_page.port_edit.setValue(self.app_config.service.ws_port)
        self.settings_page.port_edit.blockSignals(False)
        self.settings_page.theme_combo.blockSignals(True)
        self.settings_page.hotkey_edit.blockSignals(True)
        self.settings_page.merge_multi_phase_switch.blockSignals(True)
        self.settings_page.set_theme_mode(self.app_config.theme_mode)
        self.settings_page.set_hotkey(self.app_config.toggle_overlays_hotkey)
        self.settings_page.set_merge_multi_phase_enemy_battles(self.app_config.service.merge_multi_phase_enemy_battles)
        self.settings_page.theme_combo.blockSignals(False)
        self.settings_page.hotkey_edit.blockSignals(False)
        self.settings_page.merge_multi_phase_switch.blockSignals(False)
        self.settings_page.set_log_dir(self.app_config.service.log_dir)
        self.settings_page.set_service_info(self.app_config.service)
        self._refresh_log_dir_size()
        self._update_overlay_shortcut()

    def _refresh_log_dir_size(self) -> None:
        self.settings_page.set_log_size(_directory_size(self.app_config.service.log_dir))

    def _apply_gui_font_size(self, value):
        self.app_config.gui_font_percent = value
        self.gui_typography.set_scale(value/100)
        save_app_config(self.app_config, self.config_path)

    def _apply_merge_multi_phase_enemy_battles(self, checked: bool) -> None:
        if checked == self.app_config.service.merge_multi_phase_enemy_battles:
            return
        self.app_config.service.merge_multi_phase_enemy_battles = checked
        service = getattr(self.service_controller, "_service", None)
        active_session = getattr(service, "active_session", None) if service is not None else None
        if active_session is not None:
            active_session.merge_multi_phase_enemy_battles = checked
        save_app_config(self.app_config, self.config_path)

    def _choose_log_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择日志目录", str(self.app_config.service.log_dir))
        if not selected:
            return
        target = Path(selected).resolve()
        self.app_config.service.log_dir = target
        save_app_config(self.app_config, self.config_path)
        self._refresh_settings_page()
        self._load_records()

    def _set_overlay_port(self, port: int) -> None:
        self.overlay_manager.ws_port = port
        for window in self.overlay_manager._windows.values():
            if window.config.ws_port != port:
                window.config.ws_port = port
                window._load_overlay()

    def _apply_service_port(self, port: int) -> None:
        if port == self.app_config.service.ws_port:
            return
        self.app_config.service.ws_port = port
        save_app_config(self.app_config, self.config_path)
        self.settings_page.port_hint.setText('端口已保存；下次启动抓包生效。')
        self._update_service_status()

    def _choose_game_dir(self, *, select_exe: bool = False) -> None:
        start_dir = self.app_config.service.dll_dir or ROOT
        target = _select_game_directory_from_dialog(self, start_dir, select_exe=select_exe)
        if target is None:
            return
        if not _is_valid_game_dir(target):
            QMessageBox.warning(self, "目录无效", "所选目录中没有找到 Endfield.exe 或 GameAssembly.dll。")
            self._show_game_dir_infobar()
            return
        self.app_config.service.dll_dir = target
        self.app_config.service.game_exe = "Endfield.exe"
        save_app_config(self.app_config, self.config_path)
        self._clear_game_dir_infobar()
        if self._capture_error == '未设置有效游戏目录；仍可使用历史分析。':
            self._capture_error = ''
        self._refresh_settings_page()
        self._update_service_status()

    def _apply_theme_mode(self, *_args) -> None:
        mode = self.settings_page.theme_mode()
        if mode != self.app_config.theme_mode:
            self.app_config.theme_mode = mode
            save_app_config(self.app_config, self.config_path)
        self._apply_gui_theme(mode)

    def _apply_overlay_hotkey(self, *_args) -> None:
        hotkey = self.settings_page.hotkey()
        if self._update_overlay_shortcut(hotkey):
            if hotkey != self.app_config.toggle_overlays_hotkey:
                self.app_config.toggle_overlays_hotkey = hotkey
                save_app_config(self.app_config, self.config_path)
            self.settings_page.hotkey_edit.blockSignals(True)
            self.settings_page.set_hotkey(self.app_config.toggle_overlays_hotkey)
            self.settings_page.hotkey_edit.blockSignals(False)
            return
        self.settings_page.hotkey_edit.blockSignals(True)
        self.settings_page.set_hotkey(self.app_config.toggle_overlays_hotkey)
        self.settings_page.hotkey_edit.blockSignals(False)


    def _bind_settings_events(self) -> None:
        self.settings_page.port_edit.valueChanged.connect(self._apply_service_port)
        self.settings_page.theme_combo.currentIndexChanged.connect(self._apply_theme_mode)
        self.settings_page.gui_font_edit.valueChanged.connect(self._apply_gui_font_size)
        self.settings_page.log_dir_btn.clicked.connect(self._choose_log_dir)
        self.settings_page.game_exe_btn.clicked.connect(lambda: self._choose_game_dir(select_exe=True))
        self.settings_page.game_dir_btn.clicked.connect(self._choose_game_dir)
        self.settings_page.log_dir_refresh_btn.clicked.connect(self._refresh_log_dir_size)
        self.settings_page.hotkey_edit.editingFinished.connect(self._apply_overlay_hotkey)
        self.settings_page.merge_multi_phase_switch.checkedChanged.connect(self._apply_merge_multi_phase_enemy_battles)
