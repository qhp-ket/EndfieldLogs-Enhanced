"""Local ATB evidence table; the timeline draws the same samples."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import CaptionLabel, TableWidget

from .battle_energy_evidence import energy_tracks, energy_series
from .skill_names import skill_label, character_name


class EnergyEvidencePage(QWidget):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.setObjectName('battleEnergyPage')
        layout = QVBoxLayout(self)
        rows = [(t, p) for t in energy_tracks(snapshot) for p in t['samples']]
        hint = CaptionLabel('全队共用同一份技力；owner 是该次同步的主控观测，不是技力归属。时间轴分别显示主控色块与全队曲线。表内均为 ATB_UPDATE 实测值；曲线虚线为推算，鼠标悬停可查看数值与证据等级。'
                            if rows else '此日志没有 ATB_UPDATE 技力采样，无法还原技力曲线。', self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.table = TableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['时间', '当时主控（观测）', '全队技力', '变化', '恢复速度 / 秒', '原因', '来源技能'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setRowCount(len(rows))
        for i, (track, point) in enumerate(sorted(rows, key=lambda pair: pair[1]['time_ms'])):
            delta = point.get('delta')
            source = str(point.get('source') or '')
            speed = point.get('recovery_speed')
            values = [f"{point['time_ms']/1000:.3f}s", character_name(str(point.get('character_key') or ''), '未知'), f"{point['value']:g}",
                      f'{delta:+g}' if isinstance(delta, (float, int)) else '未知',
                      f'{speed:g}' if isinstance(speed, (float, int)) else '未知',
                      str(point.get('reason') or '未知'), skill_label(source).name]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                if j == 6:
                    item.setToolTip(source)
                self.table.setItem(i, j, item)
        layout.addWidget(self.table, 1)
        notes = CaptionLabel('；'.join(energy_series(snapshot)['notes']), self)
        notes.setWordWrap(True)
        layout.addWidget(notes)
