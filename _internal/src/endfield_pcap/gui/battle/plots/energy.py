"""Read-only team-energy and control tracks shared by the history timeline."""
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QBrush, QPen, QPainterPath
from PySide6.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem
from endfield_pcap.analysis.battle.energy import control_segments, energy_series, energy_value_at
from endfield_pcap.gui.battle.style import stroke


CONTROL_COLORS = ('#357ca6', '#96713b', '#7865b1', '#268573')


def draw_energy_tracks(view, y, scale, font, x_at):
    scene = view.scene()
    view._control_segments = control_segments(view._snapshot)
    view._energy_series = energy_series(view._snapshot)
    view._energy_axis = None
    if view._control_segments:
        height = 46*scale
        view._labels.append((y, height, '主控（观测）', 'control', ''))
        owners = [p['character_key'] for p in view._snapshot.get('participants') or []]
        colors = {key: CONTROL_COLORS[i % len(CONTROL_COLORS)] for i, key in enumerate(owners)}
        for segment in view._control_segments:
            rect = QRectF(x_at(segment['start_ms']), y+3*scale,
                          max(.5, x_at(segment['end_ms'])-x_at(segment['start_ms'])), 29*scale)
            item = scene.addRect(rect, QPen(Qt.PenStyle.NoPen),
                QBrush(QColor(colors.get(segment['character_key'], '#777d87'))))
            item.setToolTip(f"{segment['start_ms']/1000:.3f}–{segment['end_ms']/1000:.3f}s · {segment['name']}\n{segment['evidence']}")
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemClipsChildrenToShape)
            text = QGraphicsSimpleTextItem(segment['name'], item)
            text.setFont(font)
            text.setBrush(QBrush(QColor('white')))
            text.setPos(rect.left()+4*scale, rect.top()+4*scale)
            text.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        y += height
    samples = view._energy_series['samples']
    if not samples:
        return y
    height = 145*scale
    extent = [p['value'] for p in samples]
    extent.extend(p['end_value'] for p in view._energy_series['segments'])
    capacity = view._energy_series.get('capacity')
    high = max(100., math.ceil(max([*extent, capacity or 0])/100)*100)
    low = min(0., math.floor(min(p['value'] for p in samples)/100)*100)
    top, bottom = y+36*scale, y+height-18*scale
    view._energy_axis = dict(y=y, height=height, top=top, bottom=bottom, low=low, high=high)
    view._labels.append((y, height, '全队技力', 'energy', ''))
    py = lambda value: bottom-(value-low)/(high-low)*(bottom-top)
    for value in range(int(low), int(high)+1, 100):
        scene.addLine(view.LEFT, py(value), view._plot_right, py(value), stroke(view._grid, .7))
    pen = stroke('#199cce', 1.9)
    pen.setStyle(Qt.PenStyle.DashLine)
    path = QPainterPath()
    previous_stop = None
    anchors = {point['time_ms']: point['value'] for point in samples}
    for segment in view._energy_series['segments']:
        a, b = segment['start_ms'], segment['end_ms']
        value, final, rate = segment['start_value'], segment['end_value'], segment['rate']
        if previous_stop == a:
            path.lineTo(x_at(a), py(value))
        else:
            path.moveTo(x_at(a), py(value))
        if rate and math.isfinite(segment['capacity']):
            limit = segment['capacity'] if rate > 0 else 0
            saturation = a+(limit-value)/rate*1000
            if a < saturation < b:
                path.lineTo(x_at(saturation), py(limit))
        path.lineTo(x_at(b), py(final))
        if b in anchors:
            path.lineTo(x_at(b), py(anchors[b]))
        previous_stop = b
    scene.addPath(path, pen)
    for point in samples:
        radius = 3.5*scale
        dot = scene.addEllipse(x_at(point['time_ms'])-radius, py(point['value'])-radius,
            2*radius, 2*radius, QPen(view._bg, 1), QBrush(QColor('#199cce')))
        dot.setZValue(3)
        speed = point.get('recovery_speed')
        dot.setToolTip(f"{point['time_ms']/1000:.3f}s · 全队技力 {point['value']:g}（实测）\n"
                       f"变化 {point.get('delta')} · 恢复速度 {speed if speed is not None else '未知'}\n"
                       f"{point.get('reason') or '未知原因'} · {point.get('source') or ''}")
    caption = scene.addText('实心点：实测   虚线：推算（非精确曲线）', font)
    caption.setDefaultTextColor(view._fg)
    caption.setPos(view.LEFT+6, y)
    caption.setToolTip('\n'.join(view._energy_series['notes']))
    scene.addLine(view.LEFT, bottom, view._plot_right, bottom, QPen(view._grid))
    return y+height+8*scale


def resource_hover_text(view, stamp):
    value, quality = energy_value_at(getattr(view, '_energy_series', dict(samples=[], segments=[])), stamp)
    energy = f'全队技力 {value:.2f} · {quality}' if value is not None else f'全队技力 {quality}'
    main = next((row['name'] for row in getattr(view, '_control_segments', [])
                 if row['start_ms'] <= stamp < row['end_ms']), '未知')
    return f'{stamp/1000:.3f}s · {energy} · 主控观测 {main}'
