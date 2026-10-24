"""Settings page widgets; saves and service actions belong to MainWindow."""
from pathlib import Path
from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QWidget, QFormLayout, QHBoxLayout, QVBoxLayout, QLineEdit
from qfluentwidgets import (
    HeaderCardWidget,
    ComboBox,
    CaptionLabel,
    PrimaryPushButton,
    PushButton,
    HyperlinkLabel,
    LineEdit,
)
from endfield_pcap.gui.shared.widgets import (
    InterfacePage,
    SingleHotkeyEdit,
    OverlayNumberEdit,
    IntegerStepEdit,
    FluentSwitchButton as SwitchButton,
)
from endfield_pcap.service.config import ServiceConfig


THEME_LABELS = {"system": "跟随系统", "light": "亮色", "dark": "暗色"}

def _format_directory_size(size_bytes):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if size_bytes < 1024 or unit == 'TB':
            return f'{size_bytes:.2f} {unit}'
        size_bytes /= 1024

class SettingsPage(InterfacePage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("settingsInterface", "设置", "调整游戏路径、主题、日志目录和悬浮窗快捷键。", parent)

        theme_card = HeaderCardWidget("主题", self)
        self.content_layout.addWidget(theme_card)
        theme_wrapper = QWidget(theme_card)
        theme_card.viewLayout.addWidget(theme_wrapper)
        theme_form = QFormLayout(theme_wrapper)
        theme_form.setContentsMargins(0, 0, 0, 0)
        self.theme_combo = ComboBox(theme_wrapper)
        self.theme_combo.addItems([THEME_LABELS["system"], THEME_LABELS["light"], THEME_LABELS["dark"]])
        self.theme_hint = CaptionLabel("默认跟随系统主题。", theme_wrapper)
        theme_form.addRow("主题模式", self.theme_combo)
        theme_form.addRow("", self.theme_hint)
        font_row = QWidget(theme_wrapper)
        font_layout = QHBoxLayout(font_row)
        font_layout.setContentsMargins(0, 0, 0, 0)
        self.gui_font_edit = IntegerStepEdit(80, 180, 115, font_row)
        self.gui_font_value = CaptionLabel('%', font_row)
        font_layout.addWidget(self.gui_font_edit)
        font_layout.addWidget(self.gui_font_value)
        font_layout.addStretch()
        theme_form.addRow('GUI 字号比例', font_row)
        self.gui_font_hint = CaptionLabel('立即应用到主界面和战斗分析；悬浮窗字号仍在各自配置中调整。', theme_wrapper)
        self.gui_font_hint.setWordWrap(True)
        theme_form.addRow('', self.gui_font_hint)

        game_card = HeaderCardWidget("游戏路径", self)
        self.content_layout.addWidget(game_card)
        game_wrapper = QWidget(game_card)
        game_card.viewLayout.addWidget(game_wrapper)
        game_form = QFormLayout(game_wrapper)
        game_form.setContentsMargins(0, 0, 0, 0)
        self.game_exe_edit = LineEdit(game_wrapper)
        self.game_exe_edit.setReadOnly(True)
        self.game_exe_edit.setPlaceholderText("尚未设置游戏路径")
        self.game_exe_btn = PrimaryPushButton("选择 Endfield.exe", game_wrapper)
        self.game_dir_btn = PushButton("选择游戏目录", game_wrapper)
        game_actions = QWidget(game_wrapper)
        game_actions_layout = QHBoxLayout(game_actions)
        game_actions_layout.setContentsMargins(0, 0, 0, 0)
        game_actions_layout.addWidget(self.game_exe_btn)
        game_actions_layout.addWidget(self.game_dir_btn)
        game_actions_layout.addStretch()
        self.game_path_hint = CaptionLabel("修改后下次启动抓包生效；停止后再启动抓包需要重开游戏。", game_wrapper)
        self.game_path_hint.setWordWrap(True)
        game_form.addRow("当前 EXE", self.game_exe_edit)
        game_form.addRow("", game_actions)
        game_form.addRow("", self.game_path_hint)

        service_card = HeaderCardWidget("服务连接", self)
        self.content_layout.addWidget(service_card)
        service_wrapper = QWidget(service_card)
        service_card.viewLayout.addWidget(service_wrapper)
        service_form = QFormLayout(service_wrapper)
        service_form.setContentsMargins(0, 0, 0, 0)
        self.port_edit = OverlayNumberEdit(service_wrapper)
        self.port_edit.setRange(1, 65535)
        self.port_hint = CaptionLabel("WebSocket 端口；修改后下次启动抓包生效。", service_wrapper)
        self.port_hint.setWordWrap(True)
        service_form.addRow("端口", self.port_edit)
        service_form.addRow("", self.port_hint)
        browser_row = QWidget(service_wrapper)
        browser_layout = QHBoxLayout(browser_row)
        browser_layout.setContentsMargins(0, 0, 0, 0)
        self.browser_ws_edit = LineEdit(browser_row)
        self.browser_ws_edit.setReadOnly(True)
        self.browser_ws_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.copy_browser_ws_btn = PushButton('复制地址', browser_row)
        browser_layout.addWidget(self.browser_ws_edit, 1)
        browser_layout.addWidget(self.copy_browser_ws_btn)
        service_form.addRow('网页访问地址', browser_row)
        browser_hint = CaptionLabel('含访问凭据，仅交给可信页面。使用当前保存的端口，下次启动抓包生效。', service_wrapper)
        browser_hint.setWordWrap(True)
        service_form.addRow('', browser_hint)

        log_card = HeaderCardWidget("日志文件路径", self)
        self.content_layout.addWidget(log_card)
        log_wrapper = QWidget(log_card)
        log_card.viewLayout.addWidget(log_wrapper)
        log_form = QFormLayout(log_wrapper)
        log_form.setContentsMargins(0, 0, 0, 0)
        self.log_dir_label = CaptionLabel("-", log_wrapper)
        self.log_size_label = CaptionLabel("-", log_wrapper)
        self.log_dir_btn = PrimaryPushButton("选择日志目录", log_wrapper)
        self.log_dir_refresh_btn = PushButton("刷新文件夹大小", log_wrapper)
        log_actions = QWidget(log_wrapper)
        log_actions_layout = QHBoxLayout(log_actions)
        log_actions_layout.setContentsMargins(0, 0, 0, 0)
        log_actions_layout.addWidget(self.log_dir_btn)
        log_actions_layout.addWidget(self.log_dir_refresh_btn)
        log_actions_layout.addStretch()
        log_form.addRow("当前路径", self.log_dir_label)
        log_form.addRow("目录大小", self.log_size_label)
        log_form.addRow("", log_actions)

        hotkey_card = HeaderCardWidget("快捷键", self)
        self.content_layout.addWidget(hotkey_card)
        hotkey_wrapper = QWidget(hotkey_card)
        hotkey_card.viewLayout.addWidget(hotkey_wrapper)
        hotkey_form = QFormLayout(hotkey_wrapper)
        hotkey_form.setContentsMargins(0, 0, 0, 0)
        self.hotkey_edit = SingleHotkeyEdit(hotkey_wrapper)
        self.hotkey_hint = CaptionLabel("与一键显隐按钮相同：隐藏并记住当前浮窗，再按恢复；无记录时显示全部。默认 Ctrl+O。", hotkey_wrapper)
        self.hotkey_status = CaptionLabel("-", hotkey_wrapper)
        hotkey_form.addRow("切换悬浮窗", self.hotkey_edit)
        hotkey_form.addRow("", self.hotkey_hint)
        hotkey_form.addRow("", self.hotkey_status)

        battle_card = HeaderCardWidget("战斗行为", self)
        self.content_layout.addWidget(battle_card)
        battle_wrapper = QWidget(battle_card)
        battle_card.viewLayout.addWidget(battle_wrapper)
        battle_form = QFormLayout(battle_wrapper)
        battle_form.setContentsMargins(0, 0, 0, 0)
        self.merge_multi_phase_switch = SwitchButton(battle_wrapper)
        self.merge_multi_phase_switch.setOnText("开")
        self.merge_multi_phase_switch.setOffText("关")
        self.merge_multi_phase_hint = CaptionLabel("注意：开启此选项后，转阶段的动画也会被计入战斗时长，这会导致您的DPS降低。", battle_wrapper)
        battle_form.addRow("合并多阶段敌人的战斗", self.merge_multi_phase_switch)
        battle_form.addRow("", self.merge_multi_phase_hint)

        info_card = HeaderCardWidget("关于", self)
        self.content_layout.addWidget(info_card)
        info_wrapper = QWidget(info_card)
        info_card.viewLayout.addWidget(info_wrapper)
        info_layout = QVBoxLayout(info_wrapper)
        info_layout.setContentsMargins(0, 0, 0, 0)
        from endfield_pcap._version import APP_NAME
        from endfield_pcap._version import __version__
        self.app_name = CaptionLabel(APP_NAME, info_wrapper)
        self.ws_port = CaptionLabel("-", info_wrapper)
        self.service_log_dir = CaptionLabel("-", info_wrapper)
        self.deps = CaptionLabel("前端：PySide6-Fluent-Widgets", info_wrapper)
        self.feedback = CaptionLabel(f"版本：{__version__}", info_wrapper)
        self.bililink = HyperlinkLabel(QUrl('https://github.com/qhp-ket/EndfieldLogs'), 'EndfieldLogs 项目仓库')
        self.groupid = CaptionLabel("基于 ZMDLogs / Endfield Logs，保留上游 MIT 许可", info_wrapper)
        for widget in (self.app_name, self.bililink, self.groupid,self.feedback, self.ws_port, self.service_log_dir, self.deps):
            info_layout.addWidget(widget)

    def set_theme_mode(self, mode: str) -> None:
        index = {"system": 0, "light": 1, "dark": 2}.get(str(mode or "system").strip().lower(), 0)
        self.theme_combo.setCurrentIndex(index)

    def theme_mode(self) -> str:
        return {0: "system", 1: "light", 2: "dark"}.get(self.theme_combo.currentIndex(), "system")

    def set_hotkey(self, hotkey: str) -> None:
        self.hotkey_edit.setKeySequence(QKeySequence(hotkey or "Ctrl+O"))

    def hotkey(self) -> str:
        sequence = self.hotkey_edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        return sequence or "Ctrl+O"

    def set_hotkey_status(self, message: str, is_error: bool = False) -> None:
        self.hotkey_status.setText(message)
        self.hotkey_status.setStyleSheet(f"color: {'#ff5f56' if is_error else '#32b14a'};")

    def set_merge_multi_phase_enemy_battles(self, enabled: bool) -> None:
        self.merge_multi_phase_switch.setChecked(enabled)

    def merge_multi_phase_enemy_battles(self) -> bool:
        return self.merge_multi_phase_switch.isChecked()

    def set_log_dir(self, path: Path) -> None:
        self.log_dir_label.setText(str(path))

    def set_log_size(self, size_bytes: int) -> None:
        self.log_size_label.setText(_format_directory_size(size_bytes))

    def set_service_info(self, config: ServiceConfig) -> None:
        game_exe = str(config.dll_dir / config.game_exe) if config.dll_dir else ""
        self.game_exe_edit.setText(game_exe)
        self.game_exe_edit.setToolTip(game_exe)
        self.game_exe_edit.setCursorPosition(0)
        self.ws_port.setText(f"WS 端口: {config.ws_port}")
        from urllib.parse import urlencode
        self.browser_ws_edit.setText(f'ws://127.0.0.1:{config.ws_port}/ws?' +
            urlencode({'analysis': 'summary', 'access_token': config.ws_browser_token}))
        self.service_log_dir.setText(f"日志目录: {config.log_dir}")
