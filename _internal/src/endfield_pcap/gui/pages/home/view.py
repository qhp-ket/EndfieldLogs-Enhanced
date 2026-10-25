"""Home page: capture controls, connection status and current party."""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout
from qfluentwidgets import (
    CaptionLabel,
    HeaderCardWidget,
    ImageLabel,
    StrongBodyLabel,
    PrimaryPushButton,
    PushButton,
)
from endfield_pcap.gui.shared.widgets import InterfacePage
from endfield_pcap.models import SquadMemberPayload


class StatusPartyCard(HeaderCardWidget):
    def __init__(self, avatar_index: dict[str, Path], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("状态和小队")
        self.avatar_index = avatar_index

        wrapper = QWidget(self.view)
        self.viewLayout.addWidget(wrapper)
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.program_status = CaptionLabel("未启动", wrapper)
        self.game_status = CaptionLabel("等待客户端运行", wrapper)
        self.server_status = CaptionLabel("未连接", wrapper)
        self.flow_status = CaptionLabel("-", wrapper)

        status_grid = QGridLayout()
        status_grid.setContentsMargins(30, 0, 0, 0)
        status_grid.setHorizontalSpacing(20)
        status_grid.setVerticalSpacing(10)
        status_grid.setColumnStretch(2, 1)
        layout.addLayout(status_grid)
        for row, (label, value) in enumerate((
            ("解析服务", self.program_status),
            ("游戏客户端", self.game_status),
            ("服务器", self.server_status),
            ("当前会话", self.flow_status),
        )):
            labelname = StrongBodyLabel(label, wrapper)
            status_grid.addWidget(labelname, row, 0)
            status_grid.addWidget(value, row, 1)

        squad_title = StrongBodyLabel("当前小队", wrapper)
        squad_title.setFixedWidth(100)
        self.squad_row = QHBoxLayout()
        self.squad_row.addWidget(squad_title)
        self.squad_row.setSpacing(20)
        self.squad_row.setContentsMargins(30,0,0,0)
        layout.addLayout(self.squad_row)

    def set_status(self, program: str, game: str, server: str, flow: str) -> None:
        self.program_status.setText(program)
        self.game_status.setText(game)
        self.server_status.setText(server)
        self.flow_status.setText(flow)

    def set_squad_members(self, members: list[SquadMemberPayload]) -> None:
        while self.squad_row.count():
            item = self.squad_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not members:
            self.squad_row.addWidget(CaptionLabel("暂无小队信息", self))
            self.squad_row.addStretch()
            return
        for member in sorted(members, key=lambda item: item.squad_index):
            tile = QWidget(self)
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(0, 0, 0, 0)
            tile_layout.setSpacing(6)
            avatar_path = self.avatar_index.get(member.templateid or "")
            if avatar_path and avatar_path.exists():
                avatar = ImageLabel(str(avatar_path), tile)
            else:
                avatar = ImageLabel(tile)
                avatar.setImage(QPixmap())
                avatar.setText((member.display_name or "?")[:1])
            avatar.setFixedSize(56, 56)
            avatar.setBorderRadius(12, 12, 12, 12)
            avatar.setScaledContents(True)
            name = CaptionLabel(member.display_name or member.templateid or str(member.battle_inst_id), tile)
            name.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name.setWordWrap(True)
            badge = CaptionLabel("队长" if member.is_leader else f"#{member.squad_index + 1}", tile)
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(avatar, 0, Qt.AlignmentFlag.AlignCenter)
            tile_layout.addWidget(name)
            tile_layout.addWidget(badge)
            self.squad_row.addWidget(tile)
        self.squad_row.addStretch()


class HomePage(InterfacePage):
    def __init__(self, avatar_index: dict[str, Path], parent: QWidget | None = None) -> None:
        super().__init__("homeInterface", "首页", "查看抓包状态、连接状态和当前小队。", parent)
        actions = QHBoxLayout()
        self.start_service_btn = PrimaryPushButton("启动抓包", self)
        self.service_hint = CaptionLabel("已停止", self)
        self.service_hint.setWordWrap(True)
        actions.addWidget(self.start_service_btn)
        actions.addWidget(self.service_hint, 1)
        self.hide_gui_btn = PushButton('隐藏到托盘', self)
        self.hide_gui_btn.setToolTip('一起隐藏 GUI 窗口；抓包、输入记录和悬浮窗继续运行。设置中可修改恢复快捷键。')
        actions.addWidget(self.hide_gui_btn)
        self.content_layout.addLayout(actions)
        self.capture_note = CaptionLabel("停止后再启动无法接续正在运行的游戏会话，需要重开游戏。", self)
        self.capture_note.setWordWrap(True)
        self.content_layout.addWidget(self.capture_note)
        self.status_card = StatusPartyCard(avatar_index, self)
        self.content_layout.addWidget(self.status_card)
        card = HeaderCardWidget('输入记录', self)
        grid = QGridLayout()
        self.input_service_btn = PrimaryPushButton('开始记录输入', card)
        self.input_status = CaptionLabel('已停止', card)
        self.input_status.setWordWrap(True)
        self.input_settings_btn = PushButton('输入记录设置', card)
        grid.addWidget(self.input_service_btn,0,0)
        grid.addWidget(self.input_status,0,1)
        grid.addWidget(self.input_settings_btn,0,2)
        note = CaptionLabel('仅记录游戏前台输入，无需 Npcap。启动时仅输入记录进程申请管理员权限。',card)
        note.setWordWrap(True)
        grid.addWidget(note,1,0,1,3)
        grid.setColumnStretch(1,1)
        card.viewLayout.addLayout(grid)
        self.content_layout.addWidget(card)
        vision_card = HeaderCardWidget('连携 CD 图像识别', self)
        self.vision_status = CaptionLabel('已停止', vision_card)
        self.vision_status.setWordWrap(True)
        self.vision_overlays_btn = PushButton('前往悬浮窗', vision_card)
        vision_layout = QGridLayout()
        vision_layout.addWidget(self.vision_status, 0, 0)
        vision_layout.addWidget(self.vision_overlays_btn, 0, 1)
        vision_note = CaptionLabel('请在“悬浮窗”页启用连携 CD。识别游戏画面，无需 Npcap；抓包可补充角色身份。', vision_card)
        vision_note.setWordWrap(True)
        vision_layout.addWidget(vision_note, 1, 0, 1, 2)
        vision_layout.setColumnStretch(0, 1)
        vision_card.viewLayout.addLayout(vision_layout)
        self.content_layout.addWidget(vision_card)
        self.content_layout.addStretch()
