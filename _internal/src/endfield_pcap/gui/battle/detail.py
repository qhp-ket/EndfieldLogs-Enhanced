"""Native, lazy history detail window using the existing canonical snapshot."""
from __future__ import annotations
from PySide6.QtCore import Qt, QRectF, QSignalBlocker
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QDialog, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QLayout, QSizePolicy, QScrollArea, QFrame
from qfluentwidgets import CaptionLabel, StrongBodyLabel, Slider, PushButton, CheckBox, isDarkTheme, qconfig
from endfield_pcap.gui.battle.pages import TimelinePage, SkillCompositionPage
from endfield_pcap.gui.shared.placement import schedule_initial_placement
from endfield_pcap.gui.battle.inspector import EnemyEvidencePage
from endfield_pcap.gui.battle.controls import popup
from endfield_pcap.gui.battle.tables import remember_columns


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
        self.setObjectName('battleDetailDialog')
        from endfield_pcap._version import APP_NAME
        self.setWindowTitle(f'{APP_NAME} · 战斗分析 · {label}')
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
        settings_panel = QWidget(self)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(12, 10, 12, 10)
        self.avatar_check = CheckBox('显示角色头像', self)
        self.avatar_check.setChecked(getattr(getattr(parent, 'app_config', None), 'show_character_avatars', True))
        avatar_row = QHBoxLayout()
        avatar_row.addWidget(self.avatar_check)
        avatar_row.addWidget(CaptionLabel('头像大小', self))
        self.avatar_size_slider = Slider(Qt.Orientation.Horizontal, self)
        self.avatar_size_slider.setRange(50, 300)
        self.avatar_size_slider.setValue(getattr(getattr(parent, 'app_config', None), 'character_avatar_percent', 100))
        self.avatar_size_slider.setMinimumWidth(60)
        self.avatar_size_slider.setMaximumWidth(150)
        self.avatar_size_slider.setToolTip('独立调整头像比例，并随界面字号、时间轴图形缩放；不改变文字大小。')
        self.avatar_size_value = CaptionLabel(f'{self.avatar_size_slider.value()}%', self)
        avatar_row.addWidget(self.avatar_size_slider, 1)
        avatar_row.addWidget(self.avatar_size_value)
        settings_layout.addLayout(avatar_row)
        self.summary_button = PushButton('角色统计与快照质量', settings_panel)
        self.summary_button.clicked.connect(self._show_summary)
        settings_layout.addWidget(self.summary_button)
        from endfield_pcap.gui.battle.input_history import InputHistoryBar
        self.input_history = InputHistoryBar(self, compact=True)
        body = _DetailBody(self)
        body.setObjectName('battleDetailBody')
        self.body_scroll = QScrollArea(self)
        self.body_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.body_scroll.setWidgetResizable(True)
        self.body_scroll.setWidget(body)
        outer.addWidget(self.body_scroll, 1)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(10, 6, 10, 8)
        layout.setSpacing(4)
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
        self.display_settings = PushButton('显示设置', self)
        header.addWidget(self.display_settings)
        self.display_menu = popup(self.display_settings, settings_panel)
        header.setContentsMargins(10, 4, 10, 0)
        outer.insertLayout(0, header)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)

        self.hover_time_label = CaptionLabel('时间 —', self)
        header.insertWidget(2, self.hover_time_label)
        config = getattr(parent, 'app_config', None)
        self.timeline_page = TimelinePage(snapshot, self.input_history, settings_layout, config, self)
        self.buff_check = self.timeline_page.buff_check
        self.character_combo = self.timeline_page.character_combo
        self.curve_combo = self.timeline_page.curve_combo
        self.detail_split = self.timeline_page.detail_split
        self.details_toggle = self.timeline_page.details_toggle
        self.event_detail = self.timeline_page.event_detail
        self.fallback_status = self.timeline_page.fallback_status
        self.graphics_zoom_slider = self.timeline_page.graphics_zoom_slider
        self.graphics_zoom_value = self.timeline_page.graphics_zoom_value
        self.input_button = self.timeline_page.input_button
        self.input_menu = self.timeline_page.input_menu
        self.inspector = self.timeline_page.inspector
        self.skill_frames_check = self.timeline_page.skill_frames_check
        self.time_unit_combo = self.timeline_page.time_unit_combo
        self.timeline = self.timeline_page.timeline
        self.zoom_slider = self.timeline_page.zoom_slider
        self.tabs.addTab(self.timeline_page, '战斗时间轴')
        self.skill_page = SkillCompositionPage(snapshot, self)
        self.skill_character_combo = self.skill_page.character_combo
        self.skill_table, self.skill_empty = self.skill_page.table, self.skill_page.empty
        self.tabs.addTab(self.skill_page, '角色技能构成')
        self.enemy_page = EnemyEvidencePage(snapshot, self)
        self.tabs.addTab(self.enemy_page, '敌方数据')
        self.timeline.set_skill_frames_visible(False)
        self.timeline.set_snapshot(snapshot)
        self.curve_combo.currentIndexChanged.connect(lambda: self.timeline.set_damage_metric(self.curve_combo.currentData()))
        self.timeline.blockActivated.connect(self._inspect_block)
        self.timeline.timeHovered.connect(self._update_hover_time)
        self.timeline.laneSettingsRequested.connect(self._open_role_lanes)
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
        self.avatar_check.toggled.connect(self._set_character_avatars)
        self.avatar_size_slider.valueChanged.connect(self._set_avatar_size)
        qconfig.themeChanged.connect(self._apply_theme)
        self._apply_theme()
        self._refresh_filter()
        self.skill_table.set_gui_font_scale = self._scale_skill_avatars
        from endfield_pcap.gui.shared.typography import apply_fonts
        scale = getattr(getattr(parent, 'app_config', None), 'gui_font_percent', 115)/100
        apply_fonts(self, scale)
        self._table_timers = [remember_columns(self, table, key) for table, key in (
            (self.skill_table, 'skills'), (self.inspector.contributions, 'contributions'),
            (self.inspector.hits, 'hits'), (self.enemy_page.stats, 'enemy_stats'),
            (self.enemy_page.poise, 'enemy_poise'))]

    def set_record_label(self, label):
        self._record_label = label
        self.heading.setText(label)
        self.heading.setToolTip(label)
        from endfield_pcap._version import APP_NAME
        self.setWindowTitle(f'{APP_NAME} · 战斗分析 · {label}')

    def _show_summary(self):
        from endfield_pcap.gui.battle.summary import BattleSummaryDialog
        self._summary_dialog = BattleSummaryDialog(self.snapshot, self)
        self._summary_dialog.open()

    def _set_character_avatars(self, visible):
        self.timeline.show_character_avatars = bool(visible)
        self.timeline.fit_columns()
        self._refresh_filter()
        parent = self.parentWidget()
        if getattr(parent, 'app_config', None) is not None:
            from endfield_pcap.gui.config import save_app_config
            parent.app_config.show_character_avatars = bool(visible)
            save_app_config(parent.app_config, parent.config_path)

    def _set_avatar_size(self, percent):
        self.avatar_size_value.setText(f'{percent}%')
        self.timeline.avatar_scale = percent/100
        self.timeline.fit_columns()
        self._scale_skill_avatars(self.property('gui_font_scale') or 1.15)
        parent = self.parentWidget()
        if getattr(parent, 'app_config', None) is not None:
            from endfield_pcap.gui.config import save_app_config
            parent.app_config.character_avatar_percent = percent
            save_app_config(parent.app_config, parent.config_path)

    def showEvent(self, event):
        super().showEvent(event)
        schedule_initial_placement(self, self.parentWidget())

    def _inspect_block(self, block):
        self.inspector.set_block(block)

    def _open_role_lanes(self, owner):
        from endfield_pcap.gui.battle.lane_settings import RoleLanesDialog
        dialog = RoleLanesDialog(self.timeline._blocks, owner, self.timeline.lane_configs.get(owner), self)
        self._lane_dialog = dialog
        def apply():
            configs = dict(self.timeline.lane_configs)
            configs[owner] = dialog.value()
            self.timeline.set_lane_configs(configs)
            parent = self.parentWidget()
            config = getattr(parent, 'app_config', None)
            if config is not None:
                from endfield_pcap.gui.config import save_app_config
                config.battle_lane_configs = self.timeline.lane_configs
                if getattr(parent, 'config_path', None):
                    save_app_config(config, parent.config_path)
        dialog.accepted.connect(apply)
        dialog.open()

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
        dark = isDarkTheme()
        background, panel, text, border = ('#202020', '#272727', '#f3f3f3', '#444444') if dark else ('#f3f3f3', '#fafafa', '#202020', '#d6d6d6')
        self.setStyleSheet(f'''
            QDialog#battleDetailDialog {{ background: {background}; color: {text}; }}
            QWidget#battleDetailBody, QScrollArea {{ background: {background}; }}
            QWidget#battleTimelinePage, QWidget#battleSkillPage, QWidget#battleEnemyPage, QWidget#battleEnergyPage {{ background: {panel}; }}
            QTabWidget::pane {{ border: 1px solid {border}; background: {panel}; }}
            QTabBar::tab {{ background: {background}; color: {text}; padding: 5px 12px; border: 1px solid {border}; }}
            QTabBar::tab:selected {{ background: {panel}; border-bottom: 2px solid #009faa; }}
            QPlainTextEdit {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 5px; }}
            QTableView {{ background: {panel}; color: {text}; alternate-background-color: {background}; }}
            QHeaderView::section {{ background: {panel}; color: {text}; border: none; padding: 4px; }}
        ''')
        self.event_detail.setStyleSheet(f'QPlainTextEdit {{ background: {panel}; color: {text}; border: 1px solid {border}; border-radius: 5px; }}')
        self.skill_table.setStyleSheet(f'QTableView {{ background: {panel}; color: {text}; alternate-background-color: {background}; }} QHeaderView::section {{ background: {panel}; color: {text}; border: none; padding: 4px; }}')
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
        self.skill_page.refresh(character, avatars=self.avatar_check.isChecked(),
                                avatar_percent=self.avatar_size_slider.value(),
                                font_scale=self.property('gui_font_scale') or 1.15)

    def _scale_skill_avatars(self, scale):
        self.skill_page.set_avatar_scale(scale, self.avatar_size_slider.value(), self.avatar_check.isChecked())
