"""Tables for canonical per-hit allocation and separately sourced enemy evidence."""
from __future__ import annotations
import json
from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QIcon, QIconEngine, QPen, QColor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QHeaderView,
    QTableWidgetItem,
)
from qfluentwidgets import (
    CaptionLabel,
    PlainTextEdit,
    TableWidget,
    TransparentToolButton,
    FluentIcon,
    isDarkTheme,
)
from endfield_pcap.analysis.battle.enemy import (
    enemy_observations,
    enemy_label,
    hit_resistance,
    ELEMENT_NAMES,
    number,
)
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.analysis.battle.time import format_time
from endfield_pcap.gui.battle.tables import EvidenceItem, style_table


def display_number(value):
    n = number(value)
    return f'{n:,.2f}' if n is not None else '未知'


def table(parent, headers, stretch=0):
    view = TableWidget(parent)
    view.setColumnCount(len(headers))
    view.setHorizontalHeaderLabels(headers)
    view.verticalHeader().hide()
    view.verticalHeader().setDefaultSectionSize(28)
    view.horizontalHeader().setFixedHeight(32)
    view.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
    view.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    view.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    view.setMinimumHeight(70)
    style_table(view)
    return view


def fill(view, rows):
    sorting = view.isSortingEnabled()
    view.setSortingEnabled(False)
    view.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            item = EvidenceItem(value)
            item.setData(Qt.ItemDataRole.UserRole, i)
            view.setItem(i, j, item)
    view.setSortingEnabled(sorting)


class _PanelSizeIcon(QIconEngine):
    """Theme-aware panel maximize/restore outlines without font glyph fallback."""

    def __init__(self, restored=False):
        super().__init__()
        self.restored = restored

    def clone(self):
        return _PanelSizeIcon(self.restored)

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setPen(QPen(QColor('#f3f3f3' if isDarkTheme() else '#202020'), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        box = QRectF(rect).adjusted(2, 2, -2, -2)
        if self.restored:
            painter.drawRect(box.adjusted(3, 0, 0, -3))
            painter.fillRect(box.adjusted(0, 3, -3, 0), QColor('#272727' if isDarkTheme() else '#fafafa'))
            box.adjust(0, 3, -3, 0)
        painter.drawRect(box)
        painter.restore()


class BlockInspector(QTabWidget):
    maximizeRequested = Signal()
    collapseRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        actions = QWidget(self)
        action_layout = QHBoxLayout(actions)
        action_layout.setContentsMargins(0, 0, 2, 0)
        action_layout.setSpacing(2)
        self.maximize_button = TransparentToolButton(QIcon(_PanelSizeIcon()), actions)
        self.collapse_button = TransparentToolButton(FluentIcon.CLOSE, actions)
        for button, name in ((self.maximize_button, '最大化详情'), (self.collapse_button, '收起详情')):
            button.setFixedSize(28, 28)
            button.setToolTip(name)
            button.setAccessibleName(name)
            action_layout.addWidget(button)
        self.maximize_button.clicked.connect(self.maximizeRequested)
        self.collapse_button.clicked.connect(self.collapseRequested)
        self.setCornerWidget(actions, Qt.Corner.TopRightCorner)
        self.event_detail = PlainTextEdit(self)
        self.event_detail.setReadOnly(True)
        self.event_detail.setPlaceholderText('点击上方技能块，查看伤害、贡献分配与逐击证据。')
        self.addTab(self.event_detail, '事件概况')
        page = QWidget(self)
        layout = QVBoxLayout(page)
        self.allocation_label = CaptionLabel('尚未选择技能块', page)
        self.allocation_label.setWordWrap(True)
        layout.addWidget(self.allocation_label)
        self.contributions = table(page, ['贡献者', 'rDMG', '占已分配 rDMG'], 0)
        layout.addWidget(self.contributions, 1)
        self.addTab(page, '贡献分配')
        self.hits = table(self, ['时间 / s', '目标', 'DMG', 'rD 基数', 'rDMG 分配', '本击抗性 / 点', '核心匹配失衡值'], 1)
        self.addTab(self.hits, '逐击证据')
        self.raw = PlainTextEdit(self)
        self.raw.setReadOnly(True)
        self.addTab(self.raw, '原始证据')
        self.hits.itemSelectionChanged.connect(self._select_hit)
        self._events = []
        self._block = None
        self._time_unit = 'seconds'
        self.contributions.setSortingEnabled(True)
        self.hits.setSortingEnabled(True)

    def set_panel_maximized(self, maximized):
        self.maximize_button.setIcon(QIcon(_PanelSizeIcon(maximized)))
        name = '还原详情' if maximized else '最大化详情'
        self.maximize_button.setToolTip(name)
        self.maximize_button.setAccessibleName(name)

    def set_time_unit(self, unit):
        self._time_unit = 'frames' if unit == 'frames' else 'seconds'
        self.hits.horizontalHeaderItem(0).setText('时间 / F（30F/s）' if unit == 'frames' else '时间 / s')
        if self._block is not None:
            self.set_block(self._block)

    def set_block(self, block):
        self._block = block
        self.event_detail.setPlainText(block.description(self._time_unit))
        summary = block.contribution_summary()
        self.allocation_label.setText(f"DMG {summary['damage']:,.2f} · rD 基数 {display_number(summary['basis'])} · 已分配 {summary['allocated']:,.2f}\n"
                                      f"有分配证据 {summary['covered']}/{summary['hits']} 击；占比以已分配 rDMG 为分母。直接使用核心结果，不补猜缺失份额。")
        fill(self.contributions, [(c['name'], f"{c['value']:,.2f}", f"{c['percent']:.2f}%") for c in summary['contributions']])
        self._events = [e for e in block.events if e.get('event_type') == 'damage']
        rows = []
        for event in self._events:
            split = '；'.join(f"{character_name(str(c.get('character_key') or ''), str(c.get('character_name') or ''))} {float(c.get('value') or 0):,.2f}"
                             for c in event.get('rdps_contributions') or []) or '未知'
            resistance = hit_resistance(event)
            element = ELEMENT_NAMES.get(event.get('damage_element'), '未知属性')
            rows.append((format_time(float(event.get('ts_ms_from_start') or 0), self._time_unit, suffix=False), enemy_label(event), display_number(event.get('value')),
                         display_number(event.get('rdps_basis_value')), split, f'{element} {display_number(resistance)}',
                         display_number((event.get('poise_damage') or {}).get('current_value'))))
        fill(self.hits, rows)
        self.raw.setPlainText(json.dumps(block.events, ensure_ascii=False, indent=2))

    def _select_hit(self):
        row = self.hits.currentRow()
        item = self.hits.item(row, 0) if row >= 0 else None
        index = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(index, int) and 0 <= index < len(self._events):
            self.raw.setPlainText(json.dumps(self._events[index], ensure_ascii=False, indent=2))


class EnemyEvidencePage(QWidget):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.setObjectName('battleEnemyPage')
        layout = QVBoxLayout(self)
        hint = CaptionLabel('实体抗性是 ENTITY_STATS 在记录时刻的观测点数，不等同于之后每一击的有效抗性；本击抗性（含临时忽抗等）仅在 PKT_ATTR 有一致证据时展示。没有证据显示「未知」，不会当作 0。', self)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.stats = table(self, ['敌人 / 实例', '属性记录时间', '防御', '物理抗性', '自然抗性', '寒冷抗性', '电磁抗性', '灼热抗性', '源石抗性', '证据'], 0)
        self.tracks, observations = enemy_observations(snapshot)
        rows = []
        for obs in observations:
            points = obs.get('target_resistance_points') or {}
            ts = number(obs.get('target_stats_snapshot_ts_ms'))
            stamp = f'{int(ts)//3600000%24:02}:{int(ts)//60000%60:02}:{ts/1000%60:06.3f}' if ts is not None else '未知'
            rows.append([obs['name'], stamp, display_number(obs.get('target_defense')),
                         *[display_number(points.get(k)) for k in ELEMENT_NAMES],
                         f"{obs.get('target_resistance_points_source') or '抗性未知'} · 解析段行 {obs.get('target_stats_snapshot_line_no', '未知')}"])
        observed = {obs['key'] for obs in observations}
        for track in self.tracks:
            if track['key'] not in observed:
                rows.append([track['name'], *(['未知']*8), '缺少可绑定的 ENTITY_STATS'])
        fill(self.stats, rows)
        self.stats.setSortingEnabled(True)
        layout.addWidget(self.stats, 2)
        layout.addWidget(CaptionLabel('失衡观测（曲线在时间轴下方；观测峰值不代表真实上限）', self))
        self.poise = table(self, ['敌人 / 实例', '采样数', '首个值', '最后值', '观测峰值', '零值采样数'], 0)
        fill(self.poise, [[t['name'], len(t['samples']), display_number(t['samples'][0]['value'] if t['samples'] else None),
                           display_number(t['samples'][-1]['value'] if t['samples'] else None), display_number(t['peak']),
                           sum(p['value'] <= 0 for p in t['samples']) if t['samples'] else '未知'] for t in self.tracks])
        self.poise.setSortingEnabled(True)
        layout.addWidget(self.poise, 1)
        foot = CaptionLabel('POISE_V1 本身没有目标 ID，沿用核心的同刻技能匹配；同刻命中多个目标时放入「目标未绑定」，不强行归给某个敌人。零值采样不等于完整的失衡持续时间。抗性点数、受伤标量和减抗 BUFF 是不同证据；原始证据可在技能块中查看。', self)
        foot.setWordWrap(True)
        layout.addWidget(foot)
