"""Connect independent-service controls and format their display state."""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer
from qfluentwidgets import InfoBar


class IndependentServicesPresenter(QObject):
    def __init__(self, home_page, overlay_page, controller, settings, publish_combo,
                 show_overlays, parent):
        super().__init__(parent)
        self.home = home_page
        self.controller = controller
        self.settings = settings
        self._publish_combo = publish_combo
        self.home.input_service_btn.clicked.connect(self.toggle_input)
        self.home.input_settings_btn.clicked.connect(self.show_input_settings)
        self.home.vision_overlays_btn.clicked.connect(show_overlays)
        overlay_page.vision_settings_btn.clicked.connect(self.show_vision_settings)
        if settings.current.start_input_recording_on_launch:
            QTimer.singleShot(0, self, self.start_input)

    def start_input(self):
        try:
            self.controller.start_input()
        except Exception as exc:
            InfoBar.error(title='输入记录不可用', content=str(exc), parent=self.parent(), duration=8000)

    def toggle_input(self):
        try:
            self.controller.toggle_input()
        except Exception as exc:
            InfoBar.error(title='输入记录不可用', content=str(exc), parent=self.parent(), duration=8000)

    def drain(self):
        state = self.controller.poll()
        if state.combo_snapshot is not None:
            self._publish_combo(state.combo_snapshot)
        if not self.home.isVisible():
            return
        value = state.input_status
        status = value.get('status', 'stopped')
        title = {'stopped': '已停止', 'starting': '正在启动…', 'recording': '正在记录游戏前台输入',
                 'waiting_game': '等待游戏前台', 'error': '输入记录故障'}.get(status, status)
        received, filtered = value.get('input_received', {}), value.get('input_filtered', {})
        keyboard = max(0, received.get('key', 0) - filtered.get('key', 0))
        mouse = sum(max(0, received.get(key, 0) - filtered.get(key, 0)) for key in ('button', 'motion', 'wheel'))
        text = f'{title} · 键盘 {keyboard} · 鼠标 {mouse} · 缺失 {value.get("lost", 0)} 条'
        if value.get('privilege'):
            text += ' · ' + value['privilege']
        if value.get('errors'):
            text += ' · ' + value['errors'][-1]
        if value.get('error'):
            text += ' · ' + value['error'].splitlines()[-1][:180]
        if self.home.input_status.text() != text:
            self.home.input_status.setText(text)
        self.home.input_status.setToolTip(value.get('path', '') +
            f'\n文件记录 {value.get("count", 0)} 条（含元数据）\n原始报告计数：{value.get("raw_received", {})}'
            f'\n管理员权限：{value.get("administrator", False)}\n采集健康状态：{value.get("capture_health", {})}')
        self.home.input_service_btn.setText('停止记录输入' if state.input_running else '开始记录输入')
        if self.home.vision_status.text() != state.visual_status:
            self.home.vision_status.setText(state.visual_status)

    def show_input_settings(self):
        from .input_settings import InputSettingsDialog
        dialog = InputSettingsDialog(self.settings.current.input_settings, self.parent())
        if dialog.exec():
            self.settings.set_input_settings(dialog.value())

    def show_vision_settings(self):
        from .vision_settings import VisionSettingsDialog
        self.controller.set_preview(True)
        try:
            dialog = VisionSettingsDialog(self.controller.vision, self.settings.current.vision_settings, self.parent())
            if dialog.exec():
                self.controller.configure_vision(dialog.value())
        finally:
            self.controller.set_preview(False)
