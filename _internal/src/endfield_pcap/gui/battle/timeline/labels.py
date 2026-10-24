"""Resizable sticky character/track columns and full-text label tooltips."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen
from endfield_pcap.analysis.battle.buffs.states import buff_state_text
from endfield_pcap.analysis.battle.buffs.labels import buff_source_text


ROLE_LABEL_PIXELS = 17
SKILL_TYPE_LABEL_PIXELS = 16
BASE_LABEL_PIXELS = 13  # BUFF names, stacks, axes and ruler retain this size.


def layout_columns(view, scale):
    total = min((view._role_column_width+view._track_column_width)*scale,
                max(150., view.viewport().width()-180.))
    view._role_width = min(view._role_column_width*scale, total-65*scale)
    view._role_width = max(35., view._role_width)
    view.LEFT = round(max(view._role_width+65., total))


def column_handle(view, x):
    if abs(x-view._role_width) <= 5:
        return 'role'
    if abs(x-view.LEFT) <= 5:
        return 'track'
    return None


def label_tooltip(view, x, scene_y):
    if x >= view.LEFT:
        return ''
    if x < view._role_width:
        return next((name for y, height, name, _ in view._role_cells
                     if y <= scene_y < y+height), '')
    rows = [(y, b) for y, b in view._buff_labels
            if y <= scene_y < y+view._buff_pitch]
    if rows:
        block = rows[0][1]
        states = [state for _, b in rows for state in b.buff_states]
        return (block.name+'\n来源：'+buff_source_text(block.events[0])+'\n'
                +buff_state_text(states, view._hover_ms)+'\n'+str(block.events[0].get('event_key') or ''))
    return next((name for y, height, name, lane, _ in view._labels
                 if lane != 'buff' and y <= scene_y < y+height), '')


def draw_sticky_labels(view, painter):
    if not hasattr(view, '_bg'):
        return
    origin = view.mapToScene(0, 0)
    painter.fillRect(QRectF(origin.x(), origin.y(), view.LEFT, view.viewport().height()), view._bg)
    painter.fillRect(QRectF(origin.x(), origin.y(), view.viewport().width(), view.TOP), view._bg)
    font = painter.font()
    scale = view._graphics_zoom*view._font_scale
    font.setPixelSize(round(BASE_LABEL_PIXELS*scale))
    painter.setFont(font)
    painter.setPen(view._fg)
    role_width = view._role_width
    below_ruler = QRectF(origin.x(), origin.y()+view.TOP, view.LEFT,
                         view.viewport().height()-view.TOP)
    painter.save()
    painter.setClipRect(below_ruler)
    font.setPixelSize(round(ROLE_LABEL_PIXELS*scale))
    painter.setFont(font)
    for y, height, name, owner in view._role_cells:
        cell = QRectF(origin.x(), y, role_width, height-4)
        visible = cell.intersected(below_ruler)
        painter.drawText(visible.adjusted(5, 0, -5, 0),
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, name)
        painter.setPen(view._grid)
        painter.drawLine(cell.topRight(), cell.bottomRight())
        painter.drawLine(cell.bottomLeft(), QPointF(origin.x()+view.LEFT, cell.bottom()))
        painter.setPen(view._fg)
    for y, height, name, lane, key in view._labels:
        if lane == 'buff' or y+height < origin.y()+view.TOP:
            continue
        label_y = max(y, origin.y()+view.TOP+2)
        if y+height-4-label_y < 25*scale:
            continue
        font.setPixelSize(round((SKILL_TYPE_LABEL_PIXELS if lane == 'skill' else BASE_LABEL_PIXELS)*scale))
        painter.setFont(font)
        indent = role_width+8 if lane == 'skill' else 10
        label_rect = QRectF(origin.x()+indent, label_y, view.LEFT-indent-8, 25*scale)
        text = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(label_rect.width()))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, text)
        painter.setPen(view._grid)
        painter.drawLine(QPointF(origin.x()+(role_width if lane == 'skill' else 0), y+height-4),
                         QPointF(origin.x()+view.LEFT, y+height-4))
        painter.setPen(view._fg)
    font.setPixelSize(round(BASE_LABEL_PIXELS*scale))
    painter.setFont(font)
    axis = getattr(view, '_energy_axis', None)
    if axis:
        for value in range(int(axis['low']), int(axis['high'])+1, 100):
            ay = axis['bottom']-(value-axis['low'])/(axis['high']-axis['low'])*(axis['bottom']-axis['top'])
            painter.drawText(QRectF(origin.x()+view.LEFT-65*scale, ay-10*scale, 55*scale, 20*scale),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(value))
    seen = set()
    for y, block in view._buff_labels:
        if y in seen:
            continue
        seen.add(y)
        painter.setPen(QPen(view._row_border, 1))
        painter.drawRect(QRectF(origin.x()+role_width, y, view.LEFT-role_width, view._buff_pitch))
        painter.setPen(view._fg)
        episodes = [b for by, b in view._buff_labels if by == y]
        states = [s for b in episodes for s in b.buff_states]
        width = max(1, int(view.LEFT-role_width-16))
        name = painter.fontMetrics().elidedText(block.name, Qt.TextElideMode.ElideRight, width)
        state = painter.fontMetrics().elidedText(buff_state_text(states, view._hover_ms), Qt.TextElideMode.ElideRight, width)
        painter.drawText(QRectF(origin.x()+role_width+8, y, width, 22*scale), Qt.AlignmentFlag.AlignVCenter, name)
        painter.drawText(QRectF(origin.x()+role_width+8, y+22*scale, width, 22*scale), Qt.AlignmentFlag.AlignVCenter, state)
    painter.restore()
    if view._hover_ms is not None:
        start, duration, width = view._time_extent
        hx = view.LEFT+(view._hover_ms-start)/duration*width
        painter.setPen(QPen(view._accent, 1))
        painter.drawLine(QPointF(hx, origin.y()+view.TOP), QPointF(hx, origin.y()+view.viewport().height()))
        painter.setPen(view._fg)
    for x, label in view._ticks:
        if x >= origin.x()+view.LEFT:
            painter.drawText(QRectF(x-9, origin.y(), 80*scale, view.TOP), Qt.AlignmentFlag.AlignVCenter, label)
    for left, width, text in [(0, role_width, '角色'), (role_width, view.LEFT-role_width, '轨道 / 时间')]:
        painter.drawText(QRectF(origin.x()+left+8, origin.y(), width-16, view.TOP),
                         Qt.AlignmentFlag.AlignVCenter, text)
    painter.setPen(QPen(view._row_border, 1))
    for x in (role_width, view.LEFT):
        painter.drawLine(QPointF(origin.x()+x, origin.y()), QPointF(origin.x()+x, origin.y()+view.viewport().height()))
    painter.drawLine(QPointF(origin.x(), origin.y()+view.TOP), QPointF(origin.x()+view.viewport().width(), origin.y()+view.TOP))
