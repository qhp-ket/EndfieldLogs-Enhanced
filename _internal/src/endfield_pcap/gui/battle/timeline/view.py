"""Native history timeline: sticky labels/ruler, cast blocks and hit markers."""
from __future__ import annotations
from html import escape
from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QPainter
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QToolTip
from qfluentwidgets import isDarkTheme, TransparentToolButton, FluentIcon
from endfield_pcap.analysis.battle.detail import timeline_blocks
from endfield_pcap.analysis.battle.enemy import enemy_observations
from endfield_pcap.analysis.battle.energy import energy_tracks
from endfield_pcap.analysis.battle.lane_config import normalize_lane_configs, skill_options, resolved_lanes
from endfield_pcap.gui.battle.plots.energy import draw_energy_tracks, resource_hover_text
from endfield_pcap.gui.shared.scrolling import install_immediate_scrolling
from endfield_pcap.analysis.battle.time import ruler_ticks, format_time
from endfield_pcap.gui.battle.timeline.items import draw_block_items
from endfield_pcap.gui.battle.timeline.layout import layout_role_tracks
from endfield_pcap.gui.battle.plots.poise import draw_poise_tracks, poise_hover_text
from endfield_pcap.gui.battle.plots.damage import draw_damage_track, damage_hover_text
from endfield_pcap.gui.battle.style import CATEGORY_COLORS, stroke
from endfield_pcap.gui.battle.timeline.labels import (
    layout_columns,
    column_handle,
    label_tooltip,
    draw_sticky_labels,
    fit_label_columns,
)


COLORS = CATEGORY_COLORS


class BattleTimeline(QGraphicsView):
    blockSelected = Signal(str)  # Keep the plain summary API for existing consumers.
    blockActivated = Signal(object)
    graphicsZoomChanged = Signal(int)
    timeHovered = Signal(str)
    laneSettingsRequested = Signal(str)
    LEFT, TOP = 170, 32

    def __init__(self, parent=None):
        super().__init__(parent)
        install_immediate_scrolling()
        self.setScene(QGraphicsScene(self))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(self.DragMode.ScrollHandDrag)
        self.setMinimumHeight(160)
        self._snapshot, self._blocks = {}, []
        self.input_evidence = {}
        self.input_markers = 0
        self._character, self._show_buffs, self._zoom = '', True, 1.
        self._graphics_zoom, self._font_scale = 1., 1.
        self._hover_ms = None
        self._time_unit = 'seconds'
        self._show_skill_frames = False
        self.show_character_avatars = True
        self.avatar_scale = 1.
        self._role_column_width, self._track_column_width = 82., 180.
        self._role_width = 82.
        self._column_drag = None
        self._hover_handle = None
        self._selected_block = None
        self._damage_metric = 'rdmg'
        self._damage_cache = {}
        self.setMouseTracking(True)
        self._labels, self._ticks = [], []
        self.drawn_blocks = self.hit_markers = 0
        self.buff_change_markers = 0
        self.enemy_tracks = []
        self._expanded_lanes = set()
        self._expand_rows = []
        self.skill_lane_rows = {}
        self._role_cells = []
        self.lane_configs = {}
        self._role_buttons = {}
        self._lane_categories = {}
        self.reference_blocks = self.reference_markers = 0
        self._buff_labels, self._poise_axes = [], []

    def set_snapshot(self, snapshot):
        self._snapshot = snapshot
        self._damage_cache.clear()
        self._selected_block = None
        self._blocks = timeline_blocks(snapshot)
        self.enemy_tracks, _ = enemy_observations(snapshot)
        fit_label_columns(self)
        self.render_timeline()

    def sizeHint(self):
        return QSize(700, 280)

    def set_input_evidence(self, evidence):
        self.input_evidence = evidence
        self.render_timeline()

    def set_filter(self, character, show_buffs=True):
        self._character, self._show_buffs = character, show_buffs
        self.render_timeline()

    def set_damage_metric(self, metric):
        self._damage_metric = metric if metric in {'dmg', 'dps', 'rdmg', 'rdps'} else 'none'
        self.render_timeline()

    def set_lane_configs(self, configs):
        self.lane_configs = normalize_lane_configs(configs)
        fit_label_columns(self)
        self.render_timeline()

    def role_lane_options(self, owner):
        """Return editable preferences and labels, without exposing block evidence."""
        return dict(skills=skill_options(self._blocks, owner),
                    lanes=resolved_lanes(self._blocks, owner, self.lane_configs.get(owner)))

    def _sync_role_buttons(self):
        if not hasattr(self, '_role_buttons'):
            return
        eligible = {block.character_key for block in self._blocks if block.lane == 'skill'}
        for owner in list(self._role_buttons):
            if owner not in eligible:
                self._role_buttons.pop(owner).deleteLater()
            else:
                self._role_buttons[owner].hide()
        size = round(20*self._graphics_zoom*self._font_scale)
        for top, height, name, owner in self._role_cells:
            if owner not in eligible:
                continue
            button = self._role_buttons.get(owner)
            if button is None:
                button = TransparentToolButton(FluentIcon.SETTING, self.viewport())
                button.setToolTip(name+' · 时间轴设置')
                button.setAccessibleName(name+'时间轴设置')
                button.clicked.connect(lambda checked=False, key=owner: self.laneSettingsRequested.emit(key))
                self._role_buttons[owner] = button
            y = max(self.TOP+2, self.mapFromScene(0, top).y()+2)
            bottom = min(self.viewport().height(), self.mapFromScene(0, top+height).y())
            button.setFixedSize(size, size)
            button.setIconSize(QSize(max(12, round(size*.7)), max(12, round(size*.7))))
            button.move(max(2, round(self._role_width-size-6)), round(y))
            button.setVisible(bottom-y >= size+2 and self._role_width >= size+10)
            button.raise_()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._sync_role_buttons()

    def set_zoom(self, value):
        self._zoom = value / 100
        self.render_timeline()

    def set_time_unit(self, unit):
        unit = 'frames' if unit == 'frames' else 'seconds'
        if unit != self._time_unit:
            self._time_unit = unit
            self.render_timeline()
            if self._hover_ms is not None:
                self.timeHovered.emit(self._hover_text(self._hover_ms))

    def set_skill_frames_visible(self, visible):
        self._show_skill_frames = bool(visible)
        self.render_timeline()

    def _hover_text(self, stamp):
        text = resource_hover_text(self, stamp)
        # Resource values stay unchanged; replace only the time prefix.
        return format_time(stamp, self._time_unit)+' · '+text.split(' · ', 1)[1]

    def set_graphics_zoom(self, value):
        value = max(75, min(250, int(value)))
        if value/100 == self._graphics_zoom:
            return
        self._graphics_zoom = value/100
        self.render_timeline()
        self.graphicsZoomChanged.emit(value)

    def set_gui_font_scale(self, scale):
        if self._font_scale != scale:
            self._font_scale = scale
            fit_label_columns(self)
            self.render_timeline()

    def fit_columns(self):
        fit_label_columns(self)
        self.render_timeline()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.set_graphics_zoom(round(self._graphics_zoom*100) + (10 if event.angleDelta().y() > 0 else -10))
            event.accept()
        else:
            super().wheelEvent(event)

    def mouseMoveEvent(self, event):
        x = event.position().x()
        if self._column_drag:
            column, start_x, width = self._column_drag
            scale = self._graphics_zoom*self._font_scale
            value = max(48. if column == 'role' else 80., min(900., width+(x-start_x)/scale))
            setattr(self, '_role_column_width' if column == 'role' else '_track_column_width', value)
            self.render_timeline()
            event.accept()
            return
        handle = column_handle(self, x)
        if handle != self._hover_handle:
            self._hover_handle = handle
            self.viewport().update()
        self.viewport().setCursor(Qt.CursorShape.SplitHCursor if handle else Qt.CursorShape.ArrowCursor)
        if handle:
            QToolTip.hideText()
            event.accept()
            return
        point = self.mapToScene(event.position().toPoint())
        if x < self.LEFT and event.position().y() >= self.TOP:
            text = label_tooltip(self, x, point.y())
            if text:
                QToolTip.showText(event.globalPosition().toPoint(), text, self.viewport())
            else:
                QToolTip.hideText()
            event.accept()
            return
        if hasattr(self, '_time_extent') and event.position().x() >= self.LEFT:
            start, duration, width = self._time_extent
            self._hover_ms = max(start, min(start+duration, start + (point.x()-self.LEFT)/width*duration))
            poise = poise_hover_text(self, self._hover_ms, point.y())
            damage = damage_hover_text(self, self._hover_ms, point.y())
            text = damage or poise or self._hover_text(self._hover_ms)
            self.timeHovered.emit(text)
            axis = getattr(self, '_energy_axis', None)
            if event.position().y() >= self.TOP and (damage or poise or (axis and axis['y'] <= point.y() <= axis['y']+axis['height'])):
                QToolTip.showText(event.globalPosition().toPoint(), text, self.viewport())
            else:
                nearby = self.scene().items(QRectF(point.x()-5, point.y()-5, 10, 10))
                tips = list(dict.fromkeys(item.toolTip() for item in nearby if item.toolTip()))
                if tips:
                    html = [tip if tip.startswith('<pre>') else '<pre>'+escape(tip)+'</pre>' for tip in tips]
                    QToolTip.showText(event.globalPosition().toPoint(), '<hr>'.join(html), self.viewport())
                else:
                    QToolTip.hideText()
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_ms = None
        self._hover_handle = None
        QToolTip.hideText()
        self.timeHovered.emit('')
        self.viewport().unsetCursor()
        self.viewport().update()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_timeline()

    def _activate(self, block):
        self._selected_block = block
        self.blockSelected.emit(block.description(self._time_unit))
        self.blockActivated.emit(block)

    def _display_blocks(self):
        blocks = [b for b in self._blocks if (not self._character or b.character_key == self._character)
                  and (self._show_buffs or b.lane != 'buff')]
        return blocks

    def render_timeline(self):
        scene = self.scene()
        if scene is None:
            return
        scene.clear()
        self._role_cells = []
        scale = self._graphics_zoom*self._font_scale
        layout_columns(self, scale)
        self.TOP = round(34*scale)
        skill_pitch, buff_pitch = 37*scale, 47*scale
        self._buff_pitch = buff_pitch
        scene_font = QFont(self.font())
        scene_font.setPixelSize(round(13*scale))
        self._buff_labels = []
        self._expand_rows = []
        self.skill_lane_rows = {}
        self._lane_categories = {}
        self._labels, self._ticks = [], []
        self.drawn_blocks = self.hit_markers = 0
        self.buff_change_markers = 0
        self.reference_blocks = self.reference_markers = 0
        dark = isDarkTheme()
        self._fg = QColor('#e7e9ed' if dark else '#252930')
        self._bg = QColor('#202226' if dark else '#fafbfc')
        self._grid = QColor('#343940' if dark else '#e5e8ed')
        self._row_border = QColor('#49515d' if dark else '#c7ced7')
        self._accent = QColor('#009faa')
        self.buff_row_borders = []
        self.setBackgroundBrush(QBrush(self._bg))
        blocks = self._display_blocks()
        energy = energy_tracks(self._snapshot, self._character)
        end_ms = max(1.,float(self._snapshot.get('battle', {}).get('duration_ms') or 0))
        start_ms = 0.
        duration = max(1., end_ms-start_ms)
        plot_width = max(240, self.viewport().width()-self.LEFT-24) * self._zoom * self._graphics_zoom
        self._time_extent = start_ms, duration, plot_width
        def x_at(stamp):
            return self.LEFT + (stamp-start_ms)/duration*plot_width
        self._plot_right = self.LEFT+plot_width
        placements, y = layout_role_tracks(self, blocks, scale, x_at, plot_width, dark)
        if not blocks:
            item = scene.addText('此筛选没有技能 / BUFF 事件', scene_font)
            item.setDefaultTextColor(self._fg)
            item.setPos(self.LEFT+12, self.TOP+15)
            y = max(y, self.TOP+65)
        draw_block_items(self, placements, scale, x_at)
        y = draw_damage_track(self, y, scale, scene_font, x_at)
        y = draw_energy_tracks(self, y, scale, scene_font, x_at)
        # Enemy observations stay global when filtering an attacker.
        y = draw_poise_tracks(self, y, scale, scene_font, x_at)
        from endfield_pcap.gui.battle.timeline.inputs import draw_inputs
        y = draw_inputs(self, y, scale, x_at)
        scene.setSceneRect(0, 0, self._plot_right+22, max(200, y+8))
        for stamp, label in ruler_ticks(start_ms, end_ms, plot_width, scale, self._time_unit):
            x = x_at(stamp)
            line = scene.addLine(x, self.TOP, x, y, stroke(self._grid, 1.))
            line.setZValue(-1)
            self._ticks.append((x, label))
        for (a, _), (b, _) in zip(self._ticks, self._ticks[1:]):
            if b-a >= 90*scale:
                minor = QColor(self._grid)
                minor.setAlpha(100)
                line = scene.addLine((a+b)/2, self.TOP, (a+b)/2, y, stroke(minor, .7))
                line.setZValue(-1)
        self._sync_role_buttons()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        draw_sticky_labels(self, painter)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            handle = column_handle(self, event.position().x())
            if handle:
                width = self._role_column_width if handle == 'role' else self._track_column_width
                self._column_drag = handle, event.position().x(), width
                self.viewport().setCursor(Qt.CursorShape.SplitHCursor)
                QToolTip.hideText()
                event.accept()
                return
        if event.position().x() < self.LEFT or event.position().y() < self.TOP:
            if (event.button() == Qt.MouseButton.LeftButton and event.position().y() >= self.TOP
                    and event.position().x() >= self._role_width):
                y = self.mapToScene(event.position().toPoint()).y()
                for start, height, key in self._expand_rows:
                    if start <= y < start+height:
                        self.toggle_lane(key)
                        break
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._column_drag and event.button() == Qt.MouseButton.LeftButton:
            self._column_drag = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def toggle_lane(self, key):
        if key in self._expanded_lanes:
            self._expanded_lanes.remove(key)
        else:
            self._expanded_lanes.add(key)
        self.render_timeline()
