"""Observed enemy poise tracks and cursor previews, without interpolating state."""
from bisect import bisect_right
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QPainterPath
from endfield_pcap.analysis.battle.time import format_time


def draw_poise_tracks(view, y, scale, font, x_at):
    scene = view.scene()
    view._poise_axes = []
    for enemy in view.enemy_tracks:
        samples = enemy['samples']
        height = (112 if samples else 44)*scale
        view._labels.append((y, height, enemy['name'], 'enemy', ''))
        view._poise_axes.append(dict(y=y, height=height, enemy=enemy,
                                     stamps=[p['time_ms'] for p in samples]))
        if samples:
            peak = max(1., enemy['peak'])
            base = y+height-16
            py = lambda value: base-min(1., max(0., value/peak))*(height-36)
            path = QPainterPath(QPointF(x_at(samples[0]['time_ms']), py(samples[0]['value'])))
            for previous, point in zip(samples, samples[1:]):
                path.lineTo(x_at(point['time_ms']), py(previous['value']))
                path.lineTo(x_at(point['time_ms']), py(point['value']))
            scene.addPath(path, QPen(QColor('#d79b28'), 1.8))
            for point in samples:
                dot = scene.addEllipse(x_at(point['time_ms'])-2.5, py(point['value'])-2.5, 5, 5,
                    QPen(Qt.PenStyle.NoPen), QBrush(QColor('#de4b55' if point['value'] <= 0 else '#d79b28')))
                dot.setToolTip(f"{format_time(point['time_ms'], view._time_unit)} · 失衡观测值 {point['value']:g}\nPOISE_V1，同刻技能匹配；不推断缺失状态")
            caption = scene.addText(f"失衡观测值 · 峰值 {enemy['peak']:g}（非上限） · {len(samples)} 个采样", font)
        else:
            caption = scene.addText('失衡值未知：没有可配对的 POISE_V1 采样', font)
        caption.setDefaultTextColor(view._fg)
        caption.setPos(view.LEFT+6, y)
        scene.addLine(view.LEFT, y+height, view._plot_right, y+height, QPen(view._grid))
        y += height+8
    return y


def poise_hover_text(view, stamp, scene_y):
    axis = next((a for a in getattr(view, '_poise_axes', [])
                 if a['y'] <= scene_y < a['y']+a['height']), None)
    if axis is None:
        return None
    enemy = axis['enemy']
    index = bisect_right(axis['stamps'], stamp)-1
    prefix = f"{format_time(stamp, view._time_unit)} · {enemy['name']}"
    if index < 0:
        return prefix+' · 失衡值未知（此前没有观测）'
    point = enemy['samples'][index]
    note = '实测' if abs(point['time_ms']-stamp) < .001 else (
        '最近观测 '+format_time(point['time_ms'], view._time_unit)+'；不推算期间变化')
    return f"{prefix} · 失衡观测值 {point['value']:g}（{note}）"
