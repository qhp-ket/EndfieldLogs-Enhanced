"""Place character skill lanes and complete Buff rows using existing time bounds."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QPen, QBrush
from endfield_pcap.analysis.battle.layout import skill_lanes, CATEGORY_NAMES
from endfield_pcap.data.skill_frames import display_bounds
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.gui.battle.style import stroke


def layout_role_tracks(view, blocks, scale, x_at, plot_width, dark):
    scene = view.scene()
    skill_pitch, buff_pitch = 37*scale, 47*scale
    bounds = lambda block: display_bounds(block, view._show_skill_frames)
    keys = [str(p['character_key']) for p in view._snapshot.get('participants') or []
            if not view._character or p['character_key'] == view._character]
    groups = skill_lanes(blocks, keys, view._expanded_lanes, x_at, 4*scale, bounds, view.lane_configs)
    owners = list(dict.fromkeys([*keys, *(b.character_key for b in blocks)]))
    placements = []
    y = view.TOP+10
    for owner in owners:
        owner_groups = [group for group in groups if group.character == owner]
        buffs = [b for b in blocks if b.lane == 'buff' and b.character_key == owner]
        if not owner_groups and not buffs:
            continue
        role_top = y
        for group in owner_groups:
            lane_key = (owner, group.category)
            height = group.rows*skill_pitch+7*scale
            view.skill_lane_rows[lane_key] = group.rows
            view._lane_categories[lane_key] = group.categories
            arrow = '▾' if lane_key in view._expanded_lanes else '▸'
            name = f'{arrow} {group.name or CATEGORY_NAMES.get(group.category, group.category)}'
            view._labels.append((y, height, name, 'skill', owner))
            view._expand_rows.append((y, height, lane_key))
            for block, row, left, right in group.placements:
                placements.append((block, left, right, y+row*skill_pitch))
            scene.addLine(view.LEFT, y+height-4, view._plot_right, y+height-4, stroke(view._grid))
            y += height
        if buffs:
            rows = {}
            view._labels.append((y, max(1, len({b.buff_track for b in buffs}))*buff_pitch+10*scale, 'BUFF', 'buff', owner))
            for block in sorted(buffs, key=lambda b: b.start_ms):
                row = rows.setdefault(block.buff_track, len(rows))
                left = x_at(block.start_ms)
                right = max(x_at(block.end_ms), left+.8)
                placements.append((block, left, right, y+row*buff_pitch))
            for row in rows.values():
                rect = QRectF(view.LEFT, y+row*buff_pitch, plot_width, buff_pitch)
                # Shared edges are drawn once while each logical row keeps its bounds.
                border = scene.addLine(rect.left(), rect.top(), rect.right(), rect.top(), stroke(view._row_border))
                border.setZValue(-.5)
                border.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                view.buff_row_borders.append(rect)
            if rows:
                scene.addLine(view.LEFT, rect.bottom(), view._plot_right, rect.bottom(), stroke(view._row_border))
                scene.addLine(view.LEFT, rect.top()-(len(rows)-1)*buff_pitch, view.LEFT, rect.bottom(), stroke(view._row_border))
                scene.addLine(view._plot_right, rect.top()-(len(rows)-1)*buff_pitch, view._plot_right, rect.bottom(), stroke(view._row_border))
            y += len(rows)*buff_pitch+10*scale
        view._role_cells.append((role_top, y-role_top, character_name(owner) if owner else '公共 BUFF', owner))
        tint = QColor('#ffffff' if dark else '#52677f')
        tint.setAlpha(7 if len(view._role_cells) % 2 else 2)
        shade = scene.addRect(QRectF(view.LEFT, role_top, plot_width, y-role_top), QPen(Qt.PenStyle.NoPen), QBrush(tint))
        shade.setZValue(-2)
        shade.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        scene.addLine(view.LEFT, y-3, view._plot_right, y-3, stroke(view._row_border, 1.2))
    return placements, y
