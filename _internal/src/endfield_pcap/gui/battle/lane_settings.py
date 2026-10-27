"""Edit one character's ordered skill tracks using only evidenced skills."""
from uuid import uuid4
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QListWidgetItem, QAbstractItemView
from qfluentwidgets import CaptionLabel, ListWidget, LineEdit, PushButton, PrimaryPushButton, isDarkTheme, qconfig
from endfield_pcap.analysis.battle.lane_config import skill_options, default_lanes, resolved_lanes, normalize_lane_configs
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.gui.shared.placement import schedule_initial_placement


class RoleLanesDialog(QDialog):
    def __init__(self, blocks, owner, saved=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName('roleLanesDialog')
        self.owner = owner
        self.options = skill_options(blocks, owner)
        self.rows = resolved_lanes(blocks, owner, saved)
        self.setWindowTitle(character_name(owner)+' · 时间轴设置')
        self.resize(660, 480)
        self.setMinimumSize(520, 360)
        layout = QVBoxLayout(self)
        hint = CaptionLabel('选择轨道后勾选技能；勾选会将技能移到当前轨道。拖动轨道或使用上下移动调整顺序。', self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.tracks = ListWidget(self)
        self.tracks.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tracks.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.tracks.setAccessibleName('轨道顺序')
        left.addWidget(self.tracks, 1)
        actions = QHBoxLayout()
        self.add_button = PushButton('添加轨道', self)
        self.remove_button = PushButton('删除', self)
        actions.addWidget(self.add_button)
        actions.addWidget(self.remove_button)
        left.addLayout(actions)
        order = QHBoxLayout()
        self.up_button = PushButton('上移', self)
        self.down_button = PushButton('下移', self)
        order.addWidget(self.up_button)
        order.addWidget(self.down_button)
        left.addLayout(order)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        self.name_edit = LineEdit(self)
        self.name_edit.setMaxLength(60)
        self.name_edit.setPlaceholderText('轨道名称')
        self.name_edit.setAccessibleName('轨道名称')
        right.addWidget(self.name_edit)
        right.addWidget(CaptionLabel('本场记录中的技能块', self))
        self.skills = ListWidget(self)
        self.skills.setAccessibleName('当前轨道包含的技能')
        right.addWidget(self.skills, 1)
        body.addLayout(right, 2)
        layout.addLayout(body, 1)
        self.status = CaptionLabel('', self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.reset_button = PushButton('恢复默认', self)
        self.save_button = PrimaryPushButton('保存', self)
        self.cancel_button = PushButton('取消', self)
        footer.addWidget(self.reset_button)
        footer.addStretch()
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        for option in self.options:
            category = '终结' if option['category'] == '大招' else option['category']
            item = QListWidgetItem(f"{category} · {option['name']}")
            item.setData(Qt.ItemDataRole.UserRole, option['key'])
            item.setToolTip(option['name']+'\n'+option['key'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.skills.addItem(item)
        self.tracks.currentRowChanged.connect(self._select)
        self.tracks.model().rowsMoved.connect(self._reordered)
        self.skills.itemChanged.connect(self._check)
        self.name_edit.textEdited.connect(self._rename)
        self.add_button.clicked.connect(self._add)
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.reset_button.clicked.connect(self._reset)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)
        self._reload(0)
        qconfig.themeChanged.connect(self._apply_theme)
        self._apply_theme()
        from endfield_pcap.gui.shared.typography import apply_fonts
        apply_fonts(self, parent.property('gui_font_scale') or 1. if parent else 1.)

    def _apply_theme(self, *_):
        background = '#202020' if isDarkTheme() else '#f3f3f3'
        self.setStyleSheet(f'QDialog#roleLanesDialog {{ background: {background}; }}')

    def showEvent(self, event):
        super().showEvent(event)
        schedule_initial_placement(self, self.parentWidget())

    def _reload(self, selected):
        with QSignalBlocker(self.tracks):
            self.tracks.clear()
            for row in self.rows:
                item = QListWidgetItem(row['name'])
                item.setData(Qt.ItemDataRole.UserRole, row['id'])
                self.tracks.addItem(item)
            self.tracks.setCurrentRow(min(selected, len(self.rows)-1))
        self._select(self.tracks.currentRow())

    def _select(self, index):
        row = self.rows[index] if 0 <= index < len(self.rows) else None
        self.name_edit.setText(row['name'] if row else '')
        self.name_edit.setEnabled(row is not None)
        self.skills.setEnabled(row is not None)
        with QSignalBlocker(self.skills):
            for i in range(self.skills.count()):
                item = self.skills.item(i)
                checked = row is not None and item.data(Qt.ItemDataRole.UserRole) in row['skills']
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_status()

    def _check(self, item):
        index = self.tracks.currentRow()
        if not 0 <= index < len(self.rows):
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            for row in self.rows:
                row['skills'] = [skill for skill in row['skills'] if skill != key]
            self.rows[index]['skills'].append(key)
        else:
            self.rows[index]['skills'] = [skill for skill in self.rows[index]['skills'] if skill != key]
        self._update_status()

    def _rename(self, text):
        index = self.tracks.currentRow()
        if 0 <= index < len(self.rows):
            self.rows[index]['name'] = text.strip() or f'轨道 {index+1}'
            self.tracks.item(index).setText(self.rows[index]['name'])

    def _reordered(self, *_):
        by_id = {row['id']: row for row in self.rows}
        self.rows = [by_id[self.tracks.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.tracks.count())]
        self._select(self.tracks.currentRow())

    def _add(self):
        if len(self.rows) < 32:
            self.rows.append(dict(id='user:'+uuid4().hex, name=f'轨道 {len(self.rows)+1}', skills=[]))
            self._reload(len(self.rows)-1)

    def _remove(self):
        index = self.tracks.currentRow()
        if 0 <= index < len(self.rows):
            self.rows.pop(index)
            self._reload(index)

    def _move(self, delta):
        index = self.tracks.currentRow()
        target = index+delta
        if 0 <= index < len(self.rows) and 0 <= target < len(self.rows):
            self.rows[index], self.rows[target] = self.rows[target], self.rows[index]
            self._reload(target)

    def _reset(self):
        self.rows = default_lanes(self.options)
        self._reload(0)

    def _update_status(self):
        assigned = {skill for row in self.rows for skill in row['skills']}
        self._missing = [option for option in self.options if option['key'] not in assigned]
        self.status.setText(f'{len(self._missing)} 个未分配技能将显示在“其他”轨道。' if self._missing
                            else '每个技能显示一次；空轨道在时间轴中隐藏。')
        self.save_button.setEnabled(bool(self.options))
        index = self.tracks.currentRow()
        self.add_button.setEnabled(len(self.rows) < 32)
        self.remove_button.setEnabled(index >= 0)
        self.up_button.setEnabled(index > 0)
        self.down_button.setEnabled(0 <= index < len(self.rows)-1)

    def value(self):
        return normalize_lane_configs({self.owner: self.rows}).get(self.owner, [])

    def accept(self):
        self._update_status()
        if self.save_button.isEnabled():
            super().accept()
