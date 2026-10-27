"""Timeline blocks and evidence markers, independent of viewport interaction."""
from html import escape
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen, QBrush, QPolygonF
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsPolygonItem
from endfield_pcap.analysis.battle.detail import TimelineBlock
from endfield_pcap.analysis.battle.buffs.states import buff_state_text
from endfield_pcap.analysis.battle.time import format_time
from endfield_pcap.gui.battle.style import CATEGORY_COLORS, stroke
from endfield_pcap.gui.battle.timeline.frames import draw_skill_reference

COLORS = CATEGORY_COLORS


class _BlockItem(QGraphicsRectItem):
    def __init__(self, rect: QRectF, block: TimelineBlock, selected, scale=1., unit='seconds', reference=False):
        super().__init__(rect)
        self.block, self.selected = block, selected
        self.scale = scale
        self.reference = reference
        self.setPen(QPen(QColor('#ffffff'), .5))
        self.setBrush(QColor(COLORS.get(block.category, COLORS['其他'])))
        self.setFlag(self.GraphicsItemFlag.ItemIsSelectable)
        self.setAcceptHoverEvents(True)
        self.hovered = False
        self.setToolTip('<pre>' + escape(block.description(unit)) + '</pre>')

    def hoverEnterEvent(self, event):
        self.hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None):
        rect = self.rect()
        color = self.brush().color()
        if self.hovered:
            color = color.lighter(120)
        if self.reference:
            color.setAlpha(155)
        painter.setBrush(color)
        pen = stroke('#18b5bf' if self.isSelected() else '#d4dce5', 2. if self.isSelected() else .7)
        if self.reference:
            pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        if self.block.lane == 'buff':
            painter.drawRect(rect)  # Adjacent states must not look severed by bevels.
        else:
            painter.drawRoundedRect(rect, min(3., rect.width()/3), 3.)
        if self.isSelected() and rect.width() > 8:
            # Inset outline remains recognizable independently of hue.
            painter.setPen(stroke('#ffffff', .8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 1, 1)
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


def draw_block_items(view, placements, scale, x_at):
    scene = view.scene()
    for block, x, end, by in placements:
        skill = block.lane == 'skill'
        reference = bool(skill and view._show_skill_frames and block.frame_reference.get('end_ms') is not None)
        item = _BlockItem(QRectF(x, by, end-x, (25 if skill else 22)*scale), block,
                          view._activate, scale, view._time_unit, reference)
        scene.addItem(item)
        item.setSelected(block is view._selected_block)
        if not skill:
            view._buff_labels.append((by, block))
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
                    view.buff_change_markers += 1
                previous = stacks
        view.drawn_blocks += 1
        if skill:
            draw_skill_reference(view, block, by, scale, x_at, COLORS.get(block.category, COLORS['其他']))
            for e in block.events:
                if e.get('event_type') != 'damage':
                    continue
                hx, hy = x_at(float(e.get('ts_ms_from_start') or 0)), by+32*scale
                radius = 4*scale
                marker = QGraphicsPolygonItem(QPolygonF([QPointF(hx, hy-radius), QPointF(hx+radius, hy), QPointF(hx, hy+radius), QPointF(hx-radius, hy)]))
                marker.setBrush(QColor('#db4c55'))
                marker.setPen(QPen(Qt.PenStyle.NoPen))
                marker.setToolTip(f"{format_time(float(e.get('ts_ms_from_start') or 0), view._time_unit)} · DMG {float(e.get('value') or 0):,.2f}\n点击上方技能块查看逐击贡献")
                scene.addItem(marker)
                view.hit_markers += 1
