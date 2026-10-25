"""Native history timeline: sticky labels/ruler, cast blocks and hit markers."""
from __future__ import annotations
from html import escape
from PySide6.QtCore import Qt, QRectF, QPointF, QSize, Signal
from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsRectItem,
    QGraphicsPolygonItem,
    QToolTip,
)
from qfluentwidgets import isDarkTheme
from endfield_pcap.analysis.battle.detail import TimelineBlock, timeline_blocks
from endfield_pcap.analysis.battle.enemy import enemy_observations
from endfield_pcap.analysis.battle.buffs.states import buff_state_text
from endfield_pcap.analysis.battle.energy import energy_tracks
from endfield_pcap.analysis.battle.layout import skill_lanes, CATEGORY_NAMES
from endfield_pcap.gui.battle.plots.energy import draw_energy_tracks, resource_hover_text
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.gui.shared.scrolling import install_immediate_scrolling
from endfield_pcap.analysis.battle.time import ruler_ticks, format_time
from endfield_pcap.data.skill_frames import display_bounds
from endfield_pcap.gui.battle.timeline.frames import draw_skill_reference
from endfield_pcap.gui.battle.plots.poise import draw_poise_tracks, poise_hover_text
from endfield_pcap.gui.battle.timeline.labels import (
    layout_columns,
    column_handle,
    label_tooltip,
    draw_sticky_labels,
    fit_label_columns,
)


COLORS = {'重击': '#68829d', '战技': '#168c7b', '大招': '#b97919', '连携': '#8060b4',
          '其他': '#747e8b', 'BUFF': '#ad526a'}


class _BlockItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, block: TimelineBlock, selected, scale=1., unit='seconds', reference=False):
        super().__init__(rect)
        self.block, self.selected = block, selected
        self.scale = scale
        self.reference = reference
        self.setPen(QPen(QColor('#ffffff'), .5))
        self.setBrush(QColor(COLORS.get(block.category, COLORS['其他'])))
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable)
        self.setToolTip('<pre>' + escape(block.description(unit)) + '</pre>')

    def paint(self, painter, option, widget=None):
        rect = self.rect()
        cut = min(5., rect.width()/3)
        polygon = QPolygonF([rect.topLeft(), rect.topRight()-QPointF(cut, 0),
                            rect.topRight()+QPointF(0, cut), rect.bottomRight(),
                            rect.bottomLeft()+QPointF(cut, 0), rect.bottomLeft()-QPointF(0, cut)])
        color = self.brush().color()
        if self.reference:
            color.setAlpha(155)
        painter.setBrush(color)
        pen = QPen(QColor('#ffe4a0' if self.isSelected() else '#ffffff'), 1.8 if self.isSelected() else .8)
        if self.reference:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if self.block.lane == 'buff':
            painter.drawRect(rect)  # Adjacent states must not look severed by bevels.
        else:
            painter.drawPolygon(polygon)
        if rect.width() > 24:
            font = painter.font()
            font.setPixelSize(round(13*self.scale))
            painter.setFont(font)
            painter.setPen(QColor('white'))
            name = self.block.name if rect.width() > 100*self.scale else self.block.category
            if self.block.buff_states:
                name = buff_state_text(self.block.buff_states)
            text = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(rect.width()-7))
            painter.drawText(rect.adjusted(4, 0, -3, 0), Qt.AlignmentFlag.AlignVCenter, text)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        self.selected(self.block)


class BattleTimeline(QGraphicsView):
    blockSelected = Signal(str)  # Keep the plain summary API for existing consumers.
    blockActivated = Signal(object)
    graphicsZoomChanged = Signal(int)
    timeHovered = Signal(str)
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
        self.setMouseTracking(True)
        self._labels, self._ticks = [], []
        self.drawn_blocks = self.hit_markers = 0
        self.buff_change_markers = 0
        self.enemy_tracks = []
        self._expanded_lanes = set()
        self._expand_rows = []
        self.skill_lane_rows = {}
        self._role_cells = []
        self.reference_blocks = self.reference_markers = 0
        self._buff_labels, self._poise_axes = [], []

    def set_snapshot(self, snapshot):
        self._snapshot = snapshot
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
            text = poise or self._hover_text(self._hover_ms)
            self.timeHovered.emit(text)
            axis = getattr(self, '_energy_axis', None)
            if event.position().y() >= self.TOP and (poise or (axis and axis['y'] <= point.y() <= axis['y']+axis['height'])):
                QToolTip.showText(event.globalPosition().toPoint(), text, self.viewport())
            else:
                QToolTip.hideText()
            self.viewport().update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._hover_ms = None
        QToolTip.hideText()
        self.timeHovered.emit('')
        self.viewport().unsetCursor()
        self.viewport().update()
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render_timeline()

    def _activate(self, block):
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
        skill_pitch, buff_pitch = 40*scale, 47*scale
        self._buff_pitch = buff_pitch
        scene_font = QFont(self.font())
        scene_font.setPixelSize(round(13*scale))
        self._buff_labels = []
        self._expand_rows = []
        self.skill_lane_rows = {}
        self._labels, self._ticks = [], []
        self.drawn_blocks = self.hit_markers = 0
        self.buff_change_markers = 0
        self.reference_blocks = self.reference_markers = 0
        dark = isDarkTheme()
        self._fg = QColor('#e7e9ed' if dark else '#252930')
        self._bg = QColor('#202226' if dark else '#fafbfc')
        self._grid = QColor('#3c4149' if dark else '#dfe3e9')
        self._row_border = QColor('#626a76' if dark else '#b6c0cc')
        self._accent = QColor('#009faa')
        self.buff_row_borders = []
        self.setBackgroundBrush(QBrush(self._bg))
        blocks = self._display_blocks()
        energy = energy_tracks(self._snapshot, self._character)
        bounds = lambda block: display_bounds(block, self._show_skill_frames)
        end_ms = max(1.,float(self._snapshot.get('battle', {}).get('duration_ms') or 0))
        start_ms = 0.
        duration = max(1., end_ms-start_ms)
        plot_width = max(240, self.viewport().width()-self.LEFT-24) * self._zoom * self._graphics_zoom
        self._time_extent = start_ms, duration, plot_width
        def x_at(stamp):
            return self.LEFT + (stamp-start_ms)/duration*plot_width
        self._plot_right = self.LEFT+plot_width
        keys = [str(p['character_key']) for p in self._snapshot.get('participants') or []
                if not self._character or p['character_key'] == self._character]
        groups = skill_lanes(blocks, keys, self._expanded_lanes, x_at, 4*scale, bounds)
        owners = list(dict.fromkeys([*keys, *(b.character_key for b in blocks)]))
        placements = []
        y = self.TOP+10
        for owner in owners:
            owner_groups = [group for group in groups if group.character == owner]
            buffs = [b for b in blocks if b.lane == 'buff' and b.character_key == owner]
            if not owner_groups and not buffs:
                continue
            role_top = y
            for group in owner_groups:
                lane_key = (owner, group.category)
                height = group.rows*skill_pitch+7*scale
                self.skill_lane_rows[lane_key] = group.rows
                arrow = '▾' if lane_key in self._expanded_lanes else '▸'
                name = f'{arrow} {CATEGORY_NAMES.get(group.category, group.category)}'
                self._labels.append((y, height, name, 'skill', owner))
                self._expand_rows.append((y, height, lane_key))
                for block, row, left, right in group.placements:
                    placements.append((block, left, right, y+row*skill_pitch))
                scene.addLine(self.LEFT, y+height-4, self._plot_right, y+height-4, QPen(self._grid))
                y += height
            if buffs:
                rows = {}
                self._labels.append((y, max(1, len({b.buff_track for b in buffs}))*buff_pitch+10*scale, 'BUFF', 'buff', owner))
                for block in sorted(buffs, key=lambda b: b.start_ms):
                    row = rows.setdefault(block.buff_track, len(rows))
                    left = x_at(block.start_ms)
                    right = max(x_at(block.end_ms), left+.8)
                    placements.append((block, left, right, y+row*buff_pitch))
                for row in rows.values():
                    rect = QRectF(self.LEFT, y+row*buff_pitch, plot_width, buff_pitch)
                    border = scene.addRect(rect, QPen(self._row_border, 1), QBrush(Qt.BrushStyle.NoBrush))
                    border.setZValue(-.5)
                    border.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                    self.buff_row_borders.append(rect)
                y += len(rows)*buff_pitch+10*scale
            self._role_cells.append((role_top, y-role_top, character_name(owner) if owner else '公共 BUFF', owner))
        if not blocks:
            item = scene.addText('此筛选没有技能 / BUFF 事件', scene_font)
            item.setDefaultTextColor(self._fg)
            item.setPos(self.LEFT+12, self.TOP+15)
            y = max(y, self.TOP+65)
        for block, x, end, by in placements:
            skill = block.lane == 'skill'
            reference = bool(skill and self._show_skill_frames and block.frame_reference.get('end_ms') is not None)
            scene.addItem(_BlockItem(QRectF(x, by, end-x, (25 if skill else 22)*scale), block,
                                    self._activate, scale, self._time_unit, reference))
            if not skill:
                self._buff_labels.append((by, block))
                previous = 0
                for state in block.buff_states:
                    stacks = state['stacks']
                    if stacks is not None and previous is not None and stacks != previous:
                        radius = 4*scale
                        stamp = state['start_ms']
                        point = scene.addEllipse(x_at(stamp)-radius, by+11*scale-radius, 2*radius, 2*radius,
                            QPen(QColor('#e5f4ff'), .8), QBrush(QColor('#198cff')))
                        point.setZValue(2)
                        point.setToolTip(f"{stamp/1000:.3f}s · 层数 {previous} → {stacks}\n" + buff_state_text(block.buff_states, stamp))
                        self.buff_change_markers += 1
                    previous = stacks
            self.drawn_blocks += 1
            if skill:
                draw_skill_reference(self, block, by, scale, x_at, COLORS.get(block.category, COLORS['其他']))
                for e in block.events:
                    if e.get('event_type') != 'damage':
                        continue
                    hx, hy = x_at(float(e.get('ts_ms_from_start') or 0)), by+32*scale
                    radius = 4*scale
                    marker = QGraphicsPolygonItem(QPolygonF([QPointF(hx, hy-radius), QPointF(hx+radius, hy), QPointF(hx, hy+radius), QPointF(hx-radius, hy)]))
                    marker.setBrush(QColor('#db4c55'))
                    marker.setPen(QPen(Qt.PenStyle.NoPen))
                    marker.setToolTip(f"{format_time(float(e.get('ts_ms_from_start') or 0), self._time_unit)} · DMG {float(e.get('value') or 0):,.2f}\n点击上方技能块查看逐击贡献")
                    scene.addItem(marker)
                    self.hit_markers += 1
        y = draw_energy_tracks(self, y, scale, scene_font, x_at)
        # Enemy observations stay global when filtering an attacker.
        y = draw_poise_tracks(self, y, scale, scene_font, x_at)
        from endfield_pcap.gui.battle.timeline.inputs import draw_inputs
        y = draw_inputs(self, y, scale, x_at)
        scene.setSceneRect(0, 0, self._plot_right+22, max(200, y+8))
        for stamp, label in ruler_ticks(start_ms, end_ms, plot_width, scale, self._time_unit):
            x = x_at(stamp)
            line = scene.addLine(x, self.TOP, x, y, QPen(self._grid, .7))
            line.setZValue(-1)
            self._ticks.append((x, label))

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
