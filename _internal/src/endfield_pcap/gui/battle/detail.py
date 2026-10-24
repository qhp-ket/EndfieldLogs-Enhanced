"""Native, lazy history detail window using the existing canonical snapshot."""
from __future__ import annotations
from PySide6.QtCore import Qt, QRectF, QSignalBlocker
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QHeaderView,
    QTableWidgetItem,
    QLayout,
    QSizePolicy,
    QScrollArea,
    QFrame,
    QStackedWidget,
)
from qfluentwidgets import (
    CaptionLabel,
    StrongBodyLabel,
    ComboBox,
    Slider,
    PushButton,
    CheckBox,
    TableWidget,
    isDarkTheme,
    qconfig,
)
from endfield_pcap.analysis.battle.detail import skill_rows
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.gui.battle.timeline.view import BattleTimeline
from endfield_pcap.gui.shared.placement import schedule_initial_placement
from endfield_pcap.gui.battle.inspector import BlockInspector, EnemyEvidencePage
from endfield_pcap.gui.battle.panel import BattleDetailSplitter


class _NumberItem(QTableWidgetItem):
    def __init__(self, value, text):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        return self.value < other.value if isinstance(other, _NumberItem) else super().__lt__(other)


class _DetailBody(QWidget):
    def heightForWidth(self, width):
        # A graphics scene's preferred extent belongs inside its viewport.
        # Let layouts shrink the expanding tabs/splitter to their minima;
        # scrolling the outer body is needed only below that minimum.
        return self.minimumSizeHint().height()


class BattleDetailDialog(QDialog):
    def __init__(self, snapshot: dict, label: str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.WindowTitleHint
                            | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinMaxButtonsHint
                            | Qt.WindowType.WindowCloseButtonHint)
        self.snapshot = snapshot
        self._record_label = label
        self.web_analysis = None
        self._web_extra_state = {}
        self._web_pending_state = None
        self.setObjectName('battleDetailDialog')
        self.setWindowTitle(f'战斗分析 · {label}')
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        screen = parent.screen() if parent else QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRectF(0, 0, 1200, 840)
        width, height = max(1, min(1160, int(available.width())-40)), max(1, min(760, int(available.height())-60))
        self.setMinimumSize(min(720, width), min(480, height))
        self.resize(width, height)
        # A scrollable body also prevents native Windows height-for-width
        # negotiation from growing the whole dialog beyond a small work area.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        mode_bar = QHBoxLayout()
        mode_bar.setContentsMargins(16, 8, 16, 0)
        mode_bar.addWidget(CaptionLabel('界面风格', self))
        self.view_mode_combo = ComboBox(self)
        self.view_mode_combo.addItem('现有 Qt 界面', userData='native')
        self.view_mode_combo.addItem('官网风格（本地）', userData='web')
        self.view_mode_combo.setToolTip('两个界面使用同一份本地分析结果；切换不重新解析日志。')
        mode_bar.addWidget(self.view_mode_combo)
        mode_bar.addStretch()
        outer.addLayout(mode_bar)
        self.view_stack = QStackedWidget(self)
        outer.addWidget(self.view_stack, 1)
        body = _DetailBody(self)
        body.setObjectName('battleDetailBody')
        self.body_scroll = QScrollArea(self)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setWidget(body)
        self.view_stack.addWidget(self.body_scroll)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        heading = self.heading = StrongBodyLabel(label, self)
        heading.setWordWrap(False)
        heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        heading.setToolTip(label)
        header = QHBoxLayout()
        header.addWidget(heading, 1)
        battle = snapshot.get('battle') or {}
        self.metrics_label = CaptionLabel(f"DMG {float(battle.get('total_damage') or 0):,.2f}  ·  DPS {float(battle.get('total_dps') or 0):,.2f}  ·  {float(battle.get('duration_ms') or 0)/1000:.2f} 秒", self)
        self.metrics_label.setToolTip(self._quality_text(snapshot))
        header.addWidget(self.metrics_label)
        layout.addLayout(header)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        timeline_page = QWidget(self)
        timeline_page.setObjectName('battleTimelinePage')
        tl = QVBoxLayout(timeline_page)
        filters = QHBoxLayout()
        filters.addWidget(CaptionLabel('角色', timeline_page))
        self.character_combo = self._character_selector(timeline_page)
        filters.addWidget(self.character_combo)
        self.buff_check = CheckBox('BUFF 轨道', timeline_page)
        self.buff_check.setChecked(False)
        filters.addWidget(self.buff_check)
        self.skill_frames_check = CheckBox('固定起止配置回退', timeline_page)
        self.skill_frames_check.setChecked(False)
        self.skill_frames_check.setToolTip('完整技能起止始终直接采用日志。仅缺失起止时，虚线块使用首个实际命中点 + AKEData 固定配置时长（30F/s）；无命中或配置时保留日志区间。')
        filters.addWidget(self.skill_frames_check)
        filters.addStretch()
        self.hover_time_label = CaptionLabel('时间 —', timeline_page)
        filters.addWidget(self.hover_time_label)
        self.details_toggle = PushButton('展开详情', timeline_page)
        self.details_toggle.setCheckable(True)
        self.details_toggle.setChecked(False)
        self.details_toggle.setToolTip('收起/展开事件概况、贡献分配、逐击证据和原始证据')
        filters.addWidget(self.details_toggle)
        tl.addLayout(filters)
        toolbar = QHBoxLayout()
        toolbar.addWidget(CaptionLabel('时间范围', timeline_page))
        self.zoom_slider = Slider(Qt.Orientation.Horizontal, timeline_page)
        self.zoom_slider.setRange(100, 1000)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setMaximumWidth(200)
        self.zoom_slider.setMinimumWidth(60)
        toolbar.addWidget(self.zoom_slider, 1)
        fit = PushButton('适合窗口', timeline_page)
        fit.clicked.connect(lambda: self.zoom_slider.setValue(100))
        toolbar.addWidget(fit)
        toolbar.addWidget(CaptionLabel('单位', timeline_page))
        self.time_unit_combo = ComboBox(timeline_page)
        self.time_unit_combo.addItem('秒', userData='seconds')
        self.time_unit_combo.addItem('帧（30F/s）', userData='frames')
        self.time_unit_combo.setToolTip('显示单位换算：1s = 30F；保留小数帧，不量化日志时间')
        toolbar.addWidget(self.time_unit_combo)
        toolbar.addSpacing(12)
        toolbar.addWidget(CaptionLabel('图形大小', timeline_page))
        self.graphics_zoom_slider = Slider(Qt.Orientation.Horizontal, timeline_page)
        self.graphics_zoom_slider.setRange(75, 250)
        self.graphics_zoom_slider.setValue(100)
        self.graphics_zoom_slider.setMaximumWidth(200)
        self.graphics_zoom_slider.setMinimumWidth(60)
        self.graphics_zoom_value = CaptionLabel('100%', timeline_page)
        toolbar.addWidget(self.graphics_zoom_slider, 1)
        toolbar.addWidget(self.graphics_zoom_value)
        toolbar.addStretch()
        tl.addLayout(toolbar)
        self.timeline = BattleTimeline(timeline_page)
        self.inspector = BlockInspector(timeline_page)
        split = BattleDetailSplitter(self.timeline, self.inspector, timeline_page)
        self.detail_split = split
        self.event_detail = self.inspector.event_detail
        tl.addWidget(split, 1)
        self.timeline.setToolTip('红菱形：实际命中；蓝点：BUFF 层数变化。虚线块为固定配置回退。拖动左侧两条列分隔线调整角色名及轨道列宽。')
        self.tabs.addTab(timeline_page, '战斗时间轴')

        skill_page = QWidget(self)
        skill_page.setObjectName('battleSkillPage')
        sl = QVBoxLayout(skill_page)
        skill_filters = QHBoxLayout()
        skill_filters.addWidget(CaptionLabel('角色', skill_page))
        self.skill_character_combo = self._character_selector(skill_page)
        skill_filters.addWidget(self.skill_character_combo)
        skill_filters.addStretch()
        sl.addLayout(skill_filters)
        self.skill_table = TableWidget(skill_page)
        self.skill_table.setColumnCount(8)
        self.skill_table.setHorizontalHeaderLabels(['角色', '分类', '技能', '次数', '总伤害', 'DMG rate', '平均单次', '最大单次'])
        self.skill_table.verticalHeader().hide()
        self.skill_table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.skill_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.skill_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.skill_table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.skill_table.setSortingEnabled(True)
        self.skill_table.setToolTip('DMG rate 为该角色总伤占比；次数、平均和最大按核心合并后的单次施放统计。点击表头排序。')
        sl.addWidget(self.skill_table, 1)
        self.skill_empty = CaptionLabel('此记录没有技能构成数据', skill_page)
        sl.addWidget(self.skill_empty)
        self.tabs.addTab(skill_page, '角色技能构成')
        self.enemy_page = EnemyEvidencePage(snapshot, self)
        self.tabs.addTab(self.enemy_page, '敌方数据')
        self.timeline.set_skill_frames_visible(False)
        self.timeline.set_snapshot(snapshot)
        self.timeline.blockActivated.connect(self._inspect_block)
        self.timeline.timeHovered.connect(self._update_hover_time)
        self.zoom_slider.valueChanged.connect(self.timeline.set_zoom)
        self.graphics_zoom_slider.valueChanged.connect(self.timeline.set_graphics_zoom)
        self.timeline.graphicsZoomChanged.connect(self.graphics_zoom_slider.setValue)
        self.graphics_zoom_slider.valueChanged.connect(lambda value: self.graphics_zoom_value.setText(f'{value}%'))
        self.time_unit_combo.currentIndexChanged.connect(self._set_time_unit)
        self.skill_frames_check.toggled.connect(self.timeline.set_skill_frames_visible)
        self.details_toggle.toggled.connect(self._set_details_expanded)
        self.detail_split.detailsChanged.connect(self._sync_details_controls)
        self.inspector.collapseRequested.connect(lambda: self._set_details_expanded(False))
        self.inspector.maximizeRequested.connect(self.detail_split.toggle_details_maximized)
        self.buff_check.stateChanged.connect(self._refresh_filter)
        self.character_combo.currentIndexChanged.connect(self._refresh_filter)
        self.skill_character_combo.currentIndexChanged.connect(self._refresh_filter)
        qconfig.themeChanged.connect(self._apply_theme)
        self._apply_theme()
        self._refresh_filter()
        from endfield_pcap.gui.shared.typography import apply_fonts
        scale = getattr(getattr(parent, 'app_config', None), 'gui_font_percent', 115)/100
        apply_fonts(self, scale)
        self.view_mode_combo.currentIndexChanged.connect(self._set_view_mode)
        if getattr(getattr(parent, 'app_config', None), 'battle_analysis_view', 'native') == 'web':
            self.view_mode_combo.setCurrentIndex(1)

    def set_record_label(self, label):
        self._record_label = label
        self.heading.setText(label)
        self.heading.setToolTip(label)
        self.setWindowTitle(f'战斗分析 · {label}')
        if self.web_analysis is not None:
            self.web_analysis.set_record_label(label)

    def _native_view_state(self):
        import json
        selected = self.inspector._block
        selected_id = next((i for i, block in enumerate(self.timeline._blocks) if block is selected), None)
        return dict(self._web_extra_state, character=self.character_combo.currentData() or '',
            buffs=self.buff_check.isChecked(), fallback=self.skill_frames_check.isChecked(),
            zoom=self.zoom_slider.value(), graphics=self.graphics_zoom_slider.value(),
            unit=self.time_unit_combo.currentData(), details=self.detail_split.details_expanded(),
            detailsMaximized=self.detail_split.details_maximized(),
            expanded=[json.dumps(list(k), ensure_ascii=False, separators=(',', ':')) for k in self.timeline._expanded_lanes],
            roleWidth=self.timeline._role_column_width, trackWidth=self.timeline._track_column_width,
            tab=('timeline', 'skills', 'enemy')[self.tabs.currentIndex()], selectedBlock=selected_id,
            selectedHit=self.inspector.hits.currentRow() if self.inspector.hits.currentRow() >= 0 else None,
            detailTab=('overview', 'allocation', 'hits', 'raw')[self.inspector.currentIndex()])

    def _read_web_state(self, raw):
        import json
        self._web_pending_state = json.loads(raw)

    def _apply_web_state(self):
        import json
        state = self._web_pending_state
        if state is None:
            return
        self._web_pending_state = None
        self._web_extra_state = {k: state[k] for k in ('curve',) if k in state}
        self.character_combo.setCurrentIndex(max(0, self.character_combo.findData(state.get('character', ''))))
        self.buff_check.setChecked(bool(state.get('buffs')))
        self.skill_frames_check.setChecked(state.get('fallback', False))
        self.zoom_slider.setValue(int(state.get('zoom', 100)))
        self.graphics_zoom_slider.setValue(int(state.get('graphics', 100)))
        self.time_unit_combo.setCurrentIndex(max(0, self.time_unit_combo.findData(state.get('unit', 'seconds'))))
        self._set_details_expanded(state.get('details', False))
        if state.get('details') and state.get('detailsMaximized'):
            self.detail_split.setSizes([0, max(1, sum(self.detail_split.sizes()))])
        self.timeline._expanded_lanes = {tuple(json.loads(k)) for k in state.get('expanded', [])}
        self.timeline._role_column_width = float(state.get('roleWidth', 82))
        self.timeline._track_column_width = float(state.get('trackWidth', 180))
        self.tabs.setCurrentIndex({'timeline': 0, 'skills': 1, 'enemy': 2}.get(state.get('tab'), 0))
        selected = state.get('selectedBlock')
        if isinstance(selected, int) and 0 <= selected < len(self.timeline._blocks):
            self.inspector.set_block(self.timeline._blocks[selected])
            hit = state.get('selectedHit')
            if isinstance(hit, int) and 0 <= hit < self.inspector.hits.rowCount():
                self.inspector.hits.selectRow(hit)
            self.inspector.setCurrentIndex({'overview': 0, 'allocation': 1, 'hits': 2, 'raw': 3}.get(state.get('detailTab'), 0))

    def _set_view_mode(self, *args):
        web_mode = self.view_mode_combo.currentData() == 'web'
        if web_mode:
            if self.web_analysis is None:
                from endfield_pcap.gui.battle.web import WebBattleView
                self.web_analysis = WebBattleView(self.snapshot, self._record_label, self)
                self.web_analysis.set_gui_font_scale(self.property('gui_font_scale') or 1.15)
                self.web_analysis.bridge.stateEdited.connect(self._read_web_state)
                self.view_stack.addWidget(self.web_analysis)
            self.web_analysis.set_view_state(self._native_view_state())
            self.view_stack.setCurrentWidget(self.web_analysis)
        else:
            self._apply_web_state()
            self.view_stack.setCurrentWidget(self.body_scroll)
            self.timeline.render_timeline()
        parent = self.parentWidget()
        config = getattr(parent, 'app_config', None)
        if config is not None:
            config.battle_analysis_view = 'web' if web_mode else 'native'
            if getattr(parent, 'config_path', None):
                from endfield_pcap.gui.config import save_app_config
                save_app_config(config, parent.config_path)

    def _character_selector(self, parent):
        combo = ComboBox(parent)
        combo.setMaximumWidth(200)
        combo.addItem('全部角色', userData='')
        for participant in self.snapshot.get('participants') or []:
            key = str(participant['character_key'])
            combo.addItem(character_name(key, participant.get('character_name', '')), userData=key)
        return combo

    def showEvent(self, event):
        super().showEvent(event)
        schedule_initial_placement(self, self.parentWidget())

    def _inspect_block(self, block):
        self.inspector.set_block(block)

    def _set_details_expanded(self, expanded):
        self.detail_split.set_details_expanded(expanded)

    def _sync_details_controls(self, expanded, maximized):
        with QSignalBlocker(self.details_toggle):
            self.details_toggle.setChecked(expanded)
        self.details_toggle.setText('收起详情' if expanded else '展开详情')
        self.inspector.set_panel_maximized(maximized)

    def _update_hover_time(self, text):
        self.hover_time_label.setText('时间 '+text.split(' · ', 1)[0] if text else '时间 —')
        self.hover_time_label.setToolTip(text)

    def _set_time_unit(self, *args):
        unit = self.time_unit_combo.currentData() or 'seconds'
        self.timeline.set_time_unit(unit)
        self.inspector.set_time_unit(unit)

    def _apply_theme(self, *args):
        if self.web_analysis is not None:
            self.web_analysis.set_environment()
        dark = isDarkTheme()
        background, panel, text, border = ('#202020', '#272727', '#f3f3f3', '#444444') if dark else ('#f3f3f3', '#fafafa', '#202020', '#d6d6d6')
        self.setStyleSheet(f'''
            QDialog#battleDetailDialog {{ background: {background}; color: {text}; }}
            QWidget#battleDetailBody, QScrollArea {{ background: {background}; }}
            QWidget#battleTimelinePage, QWidget#battleSkillPage, QWidget#battleEnemyPage, QWidget#battleEnergyPage {{ background: {panel}; }}
            QTabWidget::pane {{ border: 1px solid {border}; background: {panel}; }}
            QTabBar::tab {{ background: {background}; color: {text}; padding: 9px 18px; border: 1px solid {border}; }}
            QTabBar::tab:selected {{ background: {panel}; border-bottom: 2px solid #009faa; }}
            QPlainTextEdit {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 5px; }}
            QTableView {{ background: {panel}; color: {text}; alternate-background-color: {background}; }}
            QHeaderView::section {{ background: {panel}; color: {text}; border: none; padding: 8px; }}
        ''')
        self.event_detail.setStyleSheet(f'QPlainTextEdit {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 5px; }}')
        self.skill_table.setStyleSheet(f'QTableView {{ background: {panel}; color: {text}; alternate-background-color: {background}; }} QHeaderView::section {{ background: {panel}; color: {text}; border: none; padding: 8px; }}')
        self.timeline.render_timeline()

    @staticmethod
    def _quality_text(snapshot):
        quality = snapshot.get('snapshot_quality') or {}
        names = {'verified': '已验证', 'provisional': '暂定', 'unavailable': '证据不足'}
        rdps = names.get((quality.get('rdps') or {}).get('status'), '未知')
        timing = names.get((quality.get('timing') or {}).get('status'), '未知')
        return f'rDPS：{rdps} · 计时：{timing}。明细仅展示日志中已有的证据；缺失事件不补猜。'

    def _refresh_filter(self, *args):
        source = self.sender()
        if source in (self.character_combo, self.skill_character_combo):
            other = self.skill_character_combo if source is self.character_combo else self.character_combo
            with QSignalBlocker(other):
                other.setCurrentIndex(other.findData(source.currentData()))
        character = self.character_combo.currentData() or ''
        self.timeline.set_filter(character, self.buff_check.isChecked())
        rows = skill_rows(self.snapshot, character)
        table = self.skill_table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, value in enumerate([row['display_character'], row['category'], row['display_skill']]):
                item = QTableWidgetItem(value)
                item.setToolTip(str(row.get('skill_key') or ''))
                table.setItem(i, j, item)
            for j, field in enumerate(['cast_count', 'total_damage', 'damage_percent', 'avg_damage', 'max_damage'], 3):
                value = float(row.get(field) or 0)
                text = f'{int(value)}' if field == 'cast_count' else (f'{value:.2f}%' if field == 'damage_percent' else f'{value:,.2f}')
                table.setItem(i, j, _NumberItem(value, text))
        table.setSortingEnabled(True)
        table.sortItems(4, Qt.SortOrder.DescendingOrder)
        self.skill_empty.setVisible(not rows)
