"""Visibility action; individual analysis and presentation state stay separate."""
from PySide6.QtWidgets import QWidget, QGridLayout
from qfluentwidgets import CaptionLabel, HeaderCardWidget, PushButton
from .models import OverlayEntry

class OverlayStatusCard(HeaderCardWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("一键配置")
        self.enable_all_btn = PushButton("启用全部", self)
        self.disable_all_btn = PushButton("停用全部", self)
        self.visibility_button = PushButton("显示全部", self)
        self.visibility_button.setToolTip('隐藏当前显示的浮窗并记住；再次点击恢复。没有记录时显示全部；不改变分析启用状态。快捷键执行同一操作。')
        self.enabled_count = CaptionLabel("", self)
        controls = QGridLayout()
        controls.addWidget(self.enable_all_btn, 0, 0)
        controls.addWidget(self.disable_all_btn, 0, 1)
        controls.addWidget(self.visibility_button, 0, 2)
        controls.setColumnStretch(3, 1)
        controls.addWidget(self.enabled_count, 1, 0, 1, 4)
        self.viewLayout.addLayout(controls)

    def set_entries(self, entries: list[OverlayEntry], restore_ids=()) -> None:
        shown = sum(entry.enabled and not entry.hidden for entry in entries)
        self.enabled_count.setText(f"{sum(entry.enabled for entry in entries)} / {len(entries)} 项已启用 · {shown} 项显示")
        self.visibility_button.setText('隐藏已显示' if shown else '恢复显示' if restore_ids else '显示全部')


