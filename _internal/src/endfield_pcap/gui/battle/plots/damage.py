"""Native cumulative damage/rD curves from canonical evidence."""
from bisect import bisect_right
from html import escape
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainterPath
from endfield_pcap.analysis.battle.damage import damage_series
from endfield_pcap.analysis.battle.time import format_time
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.gui.battle.style import ROLE_COLORS, stroke

METRICS = {'dmg': '累计 DMG', 'dps': '累计 DPS', 'rdmg': '累计 rDMG', 'rdps': '累计 rDPS'}


def draw_damage_track(view, y, scale, font, x_at):
    view._damage_axis = None
    metric = view._damage_metric
    if metric not in METRICS:
        return y
    key = metric, view._character
    if key not in view._damage_cache:
        view._damage_cache[key] = damage_series(view._snapshot, metric, view._character)
    series = view._damage_cache[key]
    points = series['points']
    height = (145 if points else 42)*scale
    top, bottom = y+34*scale, y+height-18*scale
    high = max(1., max((v for p in points for v in p['values'].values()), default=0.))
    axis = dict(y=y, height=height, top=top, bottom=bottom, low=0., high=high,
                ticks=[0., high/2, high], series=series, stamps=[p['time_ms'] for p in points])
    view._damage_axis = axis
    view._labels.append((y, height, METRICS[metric], 'damage', ''))
    scene = view.scene()
    py = lambda value: bottom-value/high*(bottom-top)
    for value in axis['ticks'] if points else []:
        scene.addLine(view.LEFT, py(value), view._plot_right, py(value), stroke(view._grid, .7))
    owners = list(points[0]['values']) if points else []
    all_owners = [str(p['character_key']) for p in view._snapshot.get('participants') or []]
    legend = []
    for owner in owners:
        color = ROLE_COLORS[(all_owners.index(owner) if owner in all_owners else owners.index(owner)) % len(ROLE_COLORS)]
        path = QPainterPath(QPointF(x_at(0), py(0)))
        for a, b in zip(points, points[1:]):
            path.lineTo(x_at(b['time_ms']), py(a['values'].get(owner, 0)))
            path.lineTo(x_at(b['time_ms']), py(b['values'].get(owner, 0)))
        item = scene.addPath(path, stroke(color, 1.9))
        item.setToolTip(f'{character_name(owner)} · {METRICS[metric]}\n一秒分桶；DPS = 截至桶终点的累计伤害 / 已过秒数')
        legend.append(f'<span style="color:{color}">● {escape(character_name(owner))}</span>')
    note = ' · '.join(legend) if points else 'rD 分配未知：缺少逐击分配证据'
    if series['missing']:
        note += f" · 仅已分配部分（{series['missing']}/{series['hits']} 击缺少分配）"
    caption = scene.addText('', font)
    caption.setHtml(note)
    caption.setDefaultTextColor(view._fg)
    caption.setTextWidth(max(1, view._plot_right-view.LEFT-12))
    caption.setPos(view.LEFT+6, y)
    caption.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
    return y+height+8*scale


def damage_hover_text(view, stamp, scene_y):
    axis = getattr(view, '_damage_axis', None)
    if not axis or not axis['y'] <= scene_y < axis['y']+axis['height']:
        return None
    series = axis['series']
    prefix = f"{format_time(stamp, view._time_unit)} · {METRICS[series['metric']]}"
    if not series['points']:
        return prefix+' · 未知（缺少 rD 分配证据）'
    # Each point describes the bucket ending here, not an interpolated value.
    index = max(0, bisect_right(axis['stamps'], stamp)-1)
    point = series['points'][index]
    rows = [prefix, f"桶终点 {format_time(point['time_ms'], view._time_unit)} · 一秒分桶"]
    rows.extend(f'{character_name(owner)} {value:,.2f}' for owner, value in point['values'].items())
    if series['missing']:
        rows.append(f"仅已有分配；{series['missing']}/{series['hits']} 击分配未知")
    return '\n'.join(rows)
