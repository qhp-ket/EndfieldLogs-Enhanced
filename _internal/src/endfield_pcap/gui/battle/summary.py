"""On-demand participant totals and raw quality evidence from the loaded report."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QTabWidget, QVBoxLayout
from qfluentwidgets import PlainTextEdit

from endfield_pcap._version import APP_NAME
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.gui.battle.inspector import display_number, fill, table
from endfield_pcap.gui.battle.tables import remember_columns
from endfield_pcap.gui.shared.placement import schedule_initial_placement
from endfield_pcap.gui.shared.typography import apply_fonts


class BattleSummaryDialog(QDialog):
    def __init__(self, snapshot, parent):
        super().__init__(parent)
        self.setWindowTitle(f'{APP_NAME} · 战斗概况与质量')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        available = parent.screen().availableGeometry()
        self.resize(min(900, available.width()-40), min(440, available.height()-60))
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs)
        self.participants = table(self, ['角色', 'DMG', 'rDMG', 'DPS', 'rDPS', '暴击率'], 0)
        rows = []
        for participant in snapshot.get('participants') or []:
            key = str(participant.get('character_key') or '')
            rate = participant.get('crit_rate')
            rate_text = display_number(rate*100) if type(rate) in (int, float) else '未知'
            rows.append([character_name(key, participant.get('character_name', '')),
                         *[display_number(participant.get(field))
                           for field in ('total_damage', 'total_rd', 'dps', 'rdps')],
                         rate_text+'%' if rate_text != '未知' else rate_text])
        fill(self.participants, rows)
        self.participants.setSortingEnabled(True)
        self.participants.setToolTip('直接展示核心报告中的角色统计；缺失字段显示未知。')
        self.tabs.addTab(self.participants, '角色统计')
        self.quality = PlainTextEdit(self)
        self.quality.setReadOnly(True)
        self.quality.setPlainText(json.dumps(snapshot.get('snapshot_quality') or {},
                                             ensure_ascii=False, indent=2))
        self.tabs.addTab(self.quality, '快照质量与原始字段')
        apply_fonts(self, parent.property('gui_font_scale') or 1.15)
        self._table_timer = remember_columns(self, self.participants, 'participants')

    def showEvent(self, event):
        super().showEvent(event)
        schedule_initial_placement(self, self.parentWidget())
