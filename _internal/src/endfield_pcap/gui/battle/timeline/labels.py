"""Resizable sticky character/track columns and full-text label tooltips."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPen, QFont, QFontMetricsF, QColor, QPolygonF
from endfield_pcap.gui.battle.style import stroke, compact_number, CATEGORY_COLORS
from endfield_pcap.analysis.battle.buffs.states import buff_state_text
from endfield_pcap.analysis.battle.buffs.labels import buff_source_text
from endfield_pcap.gui.shared.avatars import avatar_pixmap
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.analysis.battle.layout import CATEGORY_NAMES
from endfield_pcap.analysis.battle.lane_config import resolved_lanes


ROLE_LABEL_PIXELS = 17
SKILL_TYPE_LABEL_PIXELS = 16
BASE_LABEL_PIXELS = 13  # BUFF names, stacks, axes and ruler retain this size.
ROLE_AVATAR_PIXELS = 40


def fit_label_columns(view):
    """Measure on open/appearance changes; ordinary repaints keep dragged widths."""
    scale = view._graphics_zoom*view._font_scale
    def width(text, pixels):
        font = QFont(view.font())
        font.setPixelSize(round(pixels*scale))
        return QFontMetricsF(font).horizontalAdvance(text)/scale
    blocks = view._display_blocks()
    owners = set(b.character_key for b in blocks)
    roles = [width(character_name(key) if key else '公共 BUFF', ROLE_LABEL_PIXELS)
             + (ROLE_AVATAR_PIXELS*view.avatar_scale+5
                if view.show_character_avatars and key.startswith('chr_') else 0)
             for key in owners]
    view._role_column_width = max(64., width('角色', BASE_LABEL_PIXELS)+16,
                                  max(roles, default=0)+36)
    tracks = [width('轨道 / 时间', BASE_LABEL_PIXELS)+16]
    for owner in owners:
        tracks.extend(width(row['name'], SKILL_TYPE_LABEL_PIXELS)+32
                      for row in resolved_lanes(blocks, owner, view.lane_configs.get(owner)))
    for block in blocks:
        if block.lane == 'skill':
            tracks.append(width('▸ '+CATEGORY_NAMES.get(block.category, block.category), SKILL_TYPE_LABEL_PIXELS)+16)
        else:
            tracks.append(max(width(block.name, BASE_LABEL_PIXELS),
                              width(buff_state_text(block.buff_states), BASE_LABEL_PIXELS))+16)
    view._track_column_width = max(96., min(900., max(tracks)))


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
    draw_role_labels(view, painter, origin, scale, font, below_ruler)
    draw_track_labels(view, painter, origin, scale, font, below_ruler)
    font.setPixelSize(round(BASE_LABEL_PIXELS*scale))
    painter.setFont(font)
    axes = [getattr(view, '_energy_axis', None), getattr(view, '_damage_axis', None),
            *(a for a in getattr(view, '_poise_axes', []) if 'ticks' in a)]
    for axis in axes:
        if not axis or axis['bottom'] <= axis['top']:
            continue
        values = axis.get('ticks', range(int(axis['low']), int(axis['high'])+1, 100))
        for value in values:
            ay = axis['bottom']-(value-axis['low'])/(axis['high']-axis['low'])*(axis['bottom']-axis['top'])
            painter.drawText(QRectF(origin.x()+view.LEFT-65*scale, ay-10*scale, 55*scale, 20*scale),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, compact_number(value))
    seen = set()
    for y, block in view._buff_labels:
        if y in seen:
            continue
        seen.add(y)
        painter.setPen(stroke(view._row_border))
        # Horizontal edges shared by adjacent tracks are emitted only once.
        left, right, bottom = origin.x()+role_width, origin.x()+view.LEFT, y+view._buff_pitch
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        if not any(abs(by-bottom) < .01 for by, _ in view._buff_labels):
            painter.drawLine(QPointF(left, bottom), QPointF(right, bottom))
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
        painter.setPen(stroke(view._accent, 1))
        painter.drawLine(QPointF(hx, origin.y()+view.TOP), QPointF(hx, origin.y()+view.viewport().height()))
        painter.setPen(view._fg)
    for x, label in view._ticks:
        if x >= origin.x()+view.LEFT:
            painter.drawText(QRectF(x-9, origin.y(), 80*scale, view.TOP), Qt.AlignmentFlag.AlignVCenter, label)
    for left, width, text in [(0, role_width, '角色'), (role_width, view.LEFT-role_width, '轨道 / 时间')]:
        painter.drawText(QRectF(origin.x()+left+8, origin.y(), width-16, view.TOP),
                         Qt.AlignmentFlag.AlignVCenter, text)
    painter.setPen(stroke(view._row_border, 1))
    for x in (role_width, view.LEFT):
        painter.drawLine(QPointF(origin.x()+x, origin.y()), QPointF(origin.x()+x, origin.y()+view.viewport().height()))
    painter.drawLine(QPointF(origin.x(), origin.y()+view.TOP), QPointF(origin.x()+view.viewport().width(), origin.y()+view.TOP))
    handle = getattr(view, '_hover_handle', None)
    if handle:
        x = origin.x()+(role_width if handle == 'role' else view.LEFT)
        middle = origin.y()+view.viewport().height()/2
        painter.setPen(stroke(view._accent, 2))
        painter.drawLine(QPointF(x, middle-18), QPointF(x, middle+18))


def draw_role_labels(view, painter, origin, scale, font, below_ruler):
    role_width = view._role_width
    for index, (y, height, name, owner) in enumerate(view._role_cells):
        cell = QRectF(origin.x(), y, role_width, height-4)
        tint = QColor(view._fg)
        tint.setAlpha(7 if index % 2 == 0 else 2)
        painter.fillRect(QRectF(origin.x(), y, view.LEFT, height), tint)
        visible = cell.intersected(below_ruler)
        reserve = 26*scale if owner in view._role_buttons else 0
        content = visible.adjusted(0, 0, -reserve, 0)
        text_rect = content.adjusted(5, 0, -5, 0)
        if view.show_character_avatars and owner.startswith('chr_'):
            size = min(ROLE_AVATAR_PIXELS*scale*view.avatar_scale, max(1, visible.height()-4), max(1, content.width()-10))
            pixmap = avatar_pixmap(owner, size, view.devicePixelRatioF())
            # Compact cells use one line; tall cross-row cells center the group.
            if visible.height() >= size+font.pixelSize()+8:
                top = visible.center().y()-(size+font.pixelSize()+6)/2
                painter.drawPixmap(QPointF(content.center().x()-size/2, top), pixmap)
                text_rect.setTop(top+size+4)
                text_rect.setHeight(font.pixelSize()+5)
            else:
                painter.drawPixmap(QPointF(visible.left()+5, visible.center().y()-size/2), pixmap)
                text_rect.setLeft(text_rect.left()+size+5)
        text = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, max(1, int(text_rect.width())))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.setPen(stroke(view._row_border, 1.2))
        painter.drawLine(cell.topRight(), cell.bottomRight())
        painter.drawLine(cell.bottomLeft(), QPointF(origin.x()+view.LEFT, cell.bottom()))
        painter.setPen(view._fg)


def draw_track_labels(view, painter, origin, scale, font, below_ruler):
    role_width = view._role_width
    for y, height, name, lane, key in view._labels:
        if lane == 'buff' or y+height < origin.y()+view.TOP:
            continue
        label_y = max(y, origin.y()+view.TOP+2)
        if y+height-4-label_y < 25*scale:
            continue
        font.setPixelSize(round((SKILL_TYPE_LABEL_PIXELS if lane == 'skill' else BASE_LABEL_PIXELS)*scale))
        painter.setFont(font)
        indent = role_width+26 if lane == 'skill' else 10
        if lane == 'skill':
            key = next((k for top, h, k in view._expand_rows if top == y), None)
            cx, cy = origin.x()+role_width+10, label_y+12*scale
            points = [(cx-3, cy-2), (cx+3, cy-2), (cx, cy+3)] if key in view._expanded_lanes else [(cx-2, cy-3), (cx+3, cy), (cx-2, cy+3)]
            painter.setBrush(view._fg)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(a, b) for a, b in points]))
            categories = view._lane_categories.get(key, ())
            for i, category in enumerate(categories):
                painter.fillRect(QRectF(cx+8, cy-4+i*8/len(categories), 3, 8/len(categories)),
                                 QColor(CATEGORY_COLORS.get(category, '#747e8b')))
            painter.setPen(view._fg)
            name = name[2:]  # Arrow is drawn with geometry, independent of fonts.
        label_rect = QRectF(origin.x()+indent, label_y, view.LEFT-indent-8, 25*scale)
        text = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, int(label_rect.width()))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, text)
        painter.setPen(stroke(view._grid))
        painter.drawLine(QPointF(origin.x()+(role_width if lane == 'skill' else 0), y+height-4),
                         QPointF(origin.x()+view.LEFT, y+height-4))
        painter.setPen(view._fg)
