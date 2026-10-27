"""Native battle page components; the dialog coordinates shared state."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QHeaderView, QTableWidgetItem
from qfluentwidgets import CaptionLabel, CheckBox, PushButton, Slider, ComboBox, TableWidget
from endfield_pcap.analysis.battle.detail import skill_rows
from endfield_pcap.gui.shared.avatars import avatar_pixmap
from endfield_pcap.gui.battle.timeline.view import BattleTimeline
from endfield_pcap.gui.battle.inspector import BlockInspector
from endfield_pcap.gui.battle.panel import BattleDetailSplitter
from endfield_pcap.gui.battle.controls import WrapLayout, group, popup, character_selector
from endfield_pcap.gui.battle.tables import style_table

SKILL_AVATAR_PIXELS = 32


class _NumberItem(QTableWidgetItem):
    def __init__(self, value, text):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        return self.value < other.value if isinstance(other, _NumberItem) else super().__lt__(other)


class TimelinePage(QWidget):
    def __init__(self, snapshot, input_history, settings_layout, config, parent=None):
        super().__init__(parent)
        self.input_history = input_history
        settings_panel = settings_layout.parentWidget()
        timeline_page = self
        timeline_page.setObjectName('battleTimelinePage')
        tl = QVBoxLayout(timeline_page)
        tl.setContentsMargins(6, 4, 6, 4)
        tl.setSpacing(4)
        self.character_combo = character_selector(snapshot, timeline_page)
        self.buff_check = CheckBox('BUFF', timeline_page)
        self.buff_check.setChecked(False)
        self.skill_frames_check = CheckBox('固定起止配置回退', timeline_page)
        self.skill_frames_check.setChecked(False)
        self.skill_frames_check.setToolTip('完整技能起止始终直接采用日志。仅缺失起止时，虚线块使用首个实际命中点 + AKEData 固定配置时长（30F/s）；无命中或配置时保留日志区间。')
        settings_layout.addWidget(self.skill_frames_check)
        self.details_toggle = PushButton('展开详情', timeline_page)
        self.details_toggle.setCheckable(True)
        self.details_toggle.setChecked(False)
        self.details_toggle.setToolTip('收起/展开事件概况、贡献分配、逐击证据和原始证据')
        self.zoom_slider = Slider(Qt.Orientation.Horizontal, timeline_page)
        self.zoom_slider.setRange(100, 1000)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(80)
        fit = PushButton('适合窗口', timeline_page)
        fit.clicked.connect(lambda: self.zoom_slider.setValue(100))
        self.time_unit_combo = ComboBox(timeline_page)
        self.time_unit_combo.addItem('秒', userData='seconds')
        self.time_unit_combo.addItem('帧', userData='frames')
        self.time_unit_combo.setToolTip('显示单位换算：1s = 30F；保留小数帧，不量化日志时间')
        graphics_label = CaptionLabel('图形大小', timeline_page)
        self.graphics_zoom_slider = Slider(Qt.Orientation.Horizontal, timeline_page)
        self.graphics_zoom_slider.setRange(75, 250)
        self.graphics_zoom_slider.setValue(100)
        self.graphics_zoom_slider.setFixedWidth(65)
        self.graphics_zoom_value = CaptionLabel('100%', timeline_page)
        # Keep logical groups intact when the toolbar wraps on narrow windows.
        toolbar = WrapLayout()
        toolbar.addWidget(group(timeline_page, CaptionLabel('角色', timeline_page), self.character_combo, self.buff_check))
        self.input_button = PushButton('输入', timeline_page)
        self.input_menu = popup(self.input_button, self.input_history)
        toolbar.addWidget(group(timeline_page, self.input_history.visible, self.input_button))
        toolbar.addWidget(group(timeline_page, CaptionLabel('时间缩放', timeline_page), self.zoom_slider, fit, self.time_unit_combo))
        toolbar.addWidget(group(timeline_page, graphics_label, self.graphics_zoom_slider, self.graphics_zoom_value))
        toolbar.addWidget(group(timeline_page, self.details_toggle))
        self.fallback_status = CaptionLabel('固定起止回退已开启', timeline_page)
        self.fallback_status.hide()
        toolbar.addWidget(self.fallback_status)
        self.skill_frames_check.toggled.connect(self.fallback_status.setVisible)
        tl.addLayout(toolbar)
        curve_row = QHBoxLayout()
        curve_row.addWidget(CaptionLabel('伤害曲线', settings_panel))
        self.curve_combo = ComboBox(settings_panel)
        for text, key in [('累计 rDMG', 'rdmg'), ('累计 DMG', 'dmg'), ('累计 rDPS', 'rdps'), ('累计 DPS', 'dps'), ('隐藏', 'none')]:
            self.curve_combo.addItem(text, userData=key)
        curve_row.addWidget(self.curve_combo, 1)
        settings_layout.addLayout(curve_row)
        self.timeline = BattleTimeline(timeline_page)
        self.timeline.lane_configs = getattr(config, 'battle_lane_configs', {})
        self.timeline.show_character_avatars = getattr(config, 'show_character_avatars', True)
        self.timeline.avatar_scale = getattr(config, 'character_avatar_percent', 100)/100
        self.inspector = BlockInspector(timeline_page)
        split = BattleDetailSplitter(self.timeline, self.inspector, timeline_page)
        self.detail_split = split
        self.event_detail = self.inspector.event_detail
        tl.addWidget(split, 1)
        self.timeline.setToolTip('红菱形：实际命中；蓝点：BUFF 层数变化。虚线块为固定配置回退。拖动左侧两条列分隔线调整角色名及轨道列宽。')


class SkillCompositionPage(QWidget):
    def __init__(self, snapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        skill_page = self
        skill_page.setObjectName('battleSkillPage')
        sl = QVBoxLayout(skill_page)
        skill_filters = QHBoxLayout()
        skill_filters.addWidget(CaptionLabel('角色', skill_page))
        self.character_combo = character_selector(snapshot, skill_page)
        skill_filters.addWidget(self.character_combo)
        skill_filters.addStretch()
        sl.addLayout(skill_filters)
        self.table = TableWidget(skill_page)
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(['角色', '分类', '技能', '次数', '总伤害', 'DMG rate', '平均单次', '最大单次'])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        style_table(self.table)
        self.table.setToolTip('DMG rate 为该角色总伤占比；次数、平均和最大按核心合并后的单次施放统计。点击表头排序。')
        sl.addWidget(self.table, 1)
        self.empty = CaptionLabel('此记录没有技能构成数据', skill_page)
        sl.addWidget(self.empty)


    def refresh(self, character, *, avatars, avatar_percent, font_scale):
        rows = skill_rows(self.snapshot, character)
        table = self.table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        icon_size = round(SKILL_AVATAR_PIXELS*font_scale*avatar_percent/100)
        table.setIconSize(QSize(icon_size, icon_size))
        table.verticalHeader().setDefaultSectionSize(max((icon_size+8) if avatars else 0, table.fontMetrics().height()+8))
        for i, row in enumerate(rows):
            for j, value in enumerate([row['display_character'], row['category'], row['display_skill']]):
                item = QTableWidgetItem(value)
                if j == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.get('character_key'))
                if j == 0 and avatars:
                    item.setIcon(QIcon(avatar_pixmap(row.get('character_key'), icon_size, self.devicePixelRatioF())))
                item.setToolTip(value if j != 2 else value+'\n'+str(row.get('skill_key') or ''))
                table.setItem(i, j, item)
            for j, field in enumerate(['cast_count', 'total_damage', 'damage_percent', 'avg_damage', 'max_damage'], 3):
                value = float(row.get(field) or 0)
                text = f'{int(value)}' if field == 'cast_count' else (f'{value:.2f}%' if field == 'damage_percent' else f'{value:,.2f}')
                table.setItem(i, j, _NumberItem(value, text))
        table.setSortingEnabled(True)
        table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.empty.setVisible(not rows)

    def set_avatar_scale(self, scale, avatar_percent, avatars):
        size = round(SKILL_AVATAR_PIXELS*scale*avatar_percent/100)
        table = self.table
        changed = table.iconSize().width() != size
        table.setIconSize(QSize(size, size))
        table.verticalHeader().setDefaultSectionSize(max((size+8) if avatars else 0, table.fontMetrics().height()+8))
        if changed and avatars:
            for i in range(table.rowCount()):
                item = table.item(i, 0)
                if item:
                    item.setIcon(QIcon(avatar_pixmap(item.data(Qt.ItemDataRole.UserRole), size, self.devicePixelRatioF())))
        for column in (0, 1):
            table.resizeColumnToContents(column)
