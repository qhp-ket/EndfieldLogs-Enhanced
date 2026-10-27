"""Damage summary layout and drawing. All totals and allocations are supplied."""
from PySide6.QtCore import Qt, QRectF, QSizeF
from PySide6.QtGui import QFontMetricsF, QColor, QPen
from endfield_pcap.gui.shared.avatars import avatar_pixmap
from endfield_pcap.data.skill_names import character_name
from .model import Layout, SnapshotGate, number, formatted, clock, font, palette, text

COLUMNS = [('damage', 'DMG', 'total_damage'), ('damage_rate', 'DMG rate', 'total_damage'),
           ('rdamage', 'rDMG', 'total_rd'), ('rdamage_rate', 'rDMG rate', 'total_rd')]


class DamageModule:
    def __init__(self):
        self.gate = SnapshotGate()
        self.message = {}
        self.settings, self.theme = {}, {}
        self.connected = True

    @property
    def snapshot(self):
        return self.message.get("snapshot") or {}

    def apply_config(self, settings, theme):
        self.settings, self.theme = settings, theme

    def receive(self, message):
        if not self.gate.accept(message, {'analysis_summary', 'analysis_snapshot'}, 1):
            return False
        changed = any(self.message.get(key) != message.get(key) for key in ('snapshot', 'source', 'error'))
        self.message = message
        return changed

    def measure(self, width=None):
        config, theme = self.settings, self.theme
        endfield = config.get('theme') == 'endfield'
        normal = font(config, theme)
        if endfield:
            normal = font(config, theme, 15)
            normal.setBold(True)
        stat_font = font(config, theme, 19) if endfield else normal
        if endfield:
            stat_font.setFamily('Consolas')
            stat_font.setBold(True)
        stat_fm = QFontMetricsF(stat_font)
        secondary = font(config, theme, 10) if endfield else normal
        if endfield:
            secondary.setFamily('Consolas')
        fm = QFontMetricsF(normal)
        snapshot = self.message.get('snapshot') or {}
        battle = snapshot.get('battle') or {}
        players = [p for p in snapshot.get('participants') or [] if isinstance(p, dict)]
        metric = 'total_damage' if config.get('bar_mode') == 'dps' else 'total_rd'
        players = sorted(players, key=lambda p: number(p.get(metric)) or 0, reverse=True)
        avatar = 40*max(.5, min(3., (number(config.get('avatar_size_percent')) or 100)/100)) if config.get('show_character_avatars') != 'off' else 0
        row_height = max(avatar+6, fm.height()+QFontMetricsF(secondary).height()+8) if endfield else max(avatar+10, fm.height()*2+10)
        columns = [c for c in COLUMNS if c[0] in config.get('columns', [c[0] for c in COLUMNS])]
        total = number(battle.get('total_damage'))
        rows = []
        for p in players:
            name = str(p.get('character_name') or character_name(str(p.get('character_key') or '')))
            cells = []
            for key, label, field in columns:
                value = number(p.get(field))
                display = (formatted(value/total*100, 1)+'%' if value is not None and total and total > 0 else '—') if key.endswith('_rate') else formatted(value, compact=True)
                cells.append((display, label+'：'+formatted(value, 2)))
            rows.append(dict(player=p, name=name, crit='CRIT '+(formatted(p['crit_rate']*100, 1)+'%' if number(p.get('crit_rate')) is not None else '—'), cells=cells))
        name_width = min(420, max([130., *(fm.horizontalAdvance(r['name'])+avatar+22 for r in rows)]))
        widths = [max(80., fm.horizontalAdvance(label)+20,
                      *(stat_fm.horizontalAdvance(r['cells'][i][0])+20 for r in rows)) for i, (_,label,_) in enumerate(columns)]
        strong = font(config, theme, 30 if endfield else 20)
        strong.setBold(True)
        if endfield:
            strong.setFamily('Consolas')
        strong_fm = QFontMetricsF(strong)
        header_values = [formatted(battle.get('total_damage', 0)),
                         formatted(battle.get('total_dps', 0), 1), clock(battle.get('duration_ms', 0))]
        header_cell = max(*(strong_fm.horizontalAdvance(value) for value in header_values),
                          *(fm.horizontalAdvance(label) for label in ('总伤害', 'DPS', '战斗时间'))) + 16
        clock_font = font(config, theme, 17) if endfield else strong
        if endfield:
            clock_font.setFamily('Consolas')
            clock_font.setBold(True)
        header_widths = ([max(strong_fm.horizontalAdvance(value), fm.horizontalAdvance(label))+24
                          for value, label in zip(header_values[:2], ('团队 DMG', '团队 DPS'))]
                         + [QFontMetricsF(clock_font).horizontalAdvance(header_values[2])+40])
        natural_width = max(320., name_width+sum(widths)+24,
                            sum(header_widths)+32 if endfield else header_cell*3+48)
        if endfield:
            spare = max(0., natural_width-name_width-sum(widths)-24)
            if widths:
                widths = [size+spare/len(widths) for size in widths]
            else:
                name_width += spare
        header_height = max(60., fm.height()+strong_fm.height()+10) if endfield else max(68., fm.height()+strong_fm.height()+20)
        head_height = fm.height()+12
        footer_height = QFontMetricsF(secondary).height()+10 if endfield else fm.height()+18
        height = header_height+head_height+max(row_height*len(rows), row_height)+footer_height
        labels = {'verified':'已验证', 'provisional':'暂定', 'unavailable':'证据不可用'}
        quality = snapshot.get('quality_summary') or snapshot.get('snapshot_quality') or {}
        source = self.message.get('source') or {}
        mode = '历史 · '+str(source.get('label') or '已加载') if source.get('mode') == 'history' else '实时'
        status = '分析异常' if self.message.get('error') else (mode+' // '+labels.get(quality.get('status'), '质量未知') if snapshot else 'STANDBY // 等待战斗数据')
        if not self.connected: status += ' / 连接断开'
        tip = '\n'.join(f"{dim}: {(quality.get(dim) or {}).get('status', 'unknown')} {', '.join(map(str, (quality.get(dim) or {}).get('reasons') or []))}" for dim in ('rdps','timing'))
        layout = Layout(QSizeF(natural_width, height), data=dict(font=normal, rows=rows, columns=columns,
            widths=widths, name_width=name_width, row_height=row_height, avatar=avatar, header=header_height,
            heading=head_height, footer=footer_height, battle=battle, status=status, metric=metric,
            strong_font=strong, stat_font=stat_font, secondary_font=secondary,
            clock_font=clock_font, header_widths=header_widths, header_label_height=fm.height()+8))
        layout.hits.append((QRectF(0, height-footer_height, natural_width, footer_height), tip))
        layout.hits.append((QRectF(0, 0, natural_width, header_height),
            f"总伤害 {formatted(battle.get('total_damage'), 2)}\nDPS {formatted(battle.get('total_dps'), 2)}\n时长 {clock(battle.get('duration_ms'))}"))
        for i, row in enumerate(rows):
            y = header_height+head_height+i*row_height
            layout.hits.append((QRectF(12,y,name_width,row_height), row['name']+'\n'+row['crit']))
            x = name_width+12
            for size, (_, tooltip) in zip(widths,row['cells']):
                layout.hits.append((QRectF(x,y,size,row_height),tooltip)); x += size
        return layout

    def paint(self, painter, rect, layout, dpr):
        data = layout.data
        colors = palette(self.settings, self.theme)
        painter.setFont(data['font'])
        battle = data['battle']
        industrial = self.settings.get('theme') == 'endfield'
        if industrial:
            from .decoration import industrial_panel
            industrial_panel(painter, rect, data['header'], data['footer'])
        third = (rect.width()-48)/3
        if industrial:
            # The previous overlay used two prominent metrics and a smaller
            # right-aligned clock, rather than three equal statistic columns.
            available = rect.width()-32
            widths = data['header_widths']
            extra = max(0., available-sum(widths))
            x = 12.
            for i, (label, value) in enumerate((('团队 DMG', formatted(battle.get('total_damage',0))),
                                                ('团队 DPS', formatted(battle.get('total_dps',0),1)))):
                width = widths[i]+extra/2
                text(painter,QRectF(x,4,width-12,data['header_label_height']),label,QColor('#bfb400'))
                painter.setFont(data['strong_font'])
                text(painter,QRectF(x,data['header_label_height']-2,width-12,data['header']-data['header_label_height']),value,QColor('#ffffff'))
                painter.setFont(data['font'])
                x += width
            painter.fillRect(QRectF(x+2,data['header']/2-3,5,5),QColor('#bfb400'))
            painter.setFont(data['clock_font'])
            text(painter,QRectF(x+14,0,widths[2]-14,data['header']),clock(battle.get('duration_ms',0)),QColor('#ffffff'))
            painter.setFont(data['font'])
        for i,(label,value) in enumerate([('总伤害',formatted(battle.get('total_damage',0))),
                ('DPS',formatted(battle.get('total_dps',0),1)),('战斗时间',clock(battle.get('duration_ms',0)))]):
            if industrial:
                break
            label_height = data['header_label_height']
            text(painter,QRectF(12+i*third,4,third,label_height),label,QColor('#feef00') if industrial else colors['muted'])
            painter.setFont(data['strong_font'])
            text(painter,QRectF(12+i*third,label_height+4,third-8,data['header']-label_height-8),value,QColor('#ffffff') if industrial else colors['foreground'])
            painter.setFont(data['font'])
        text(painter,QRectF(12,data['header'],data['name_width'],data['heading']),
             '角色 · '+('rDMG' if data['metric']=='total_rd' else 'DMG')+' 条',colors['foreground'] if industrial else colors['muted'])
        x = data['name_width']+12
        for size, (_,label,_) in zip(data['widths'],data['columns']):
            text(painter,QRectF(x,data['header'],size-8,data['heading']),label,colors['foreground'] if industrial else colors['muted'],Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); x += size
        maximum = max([0., *(number(r['player'].get(data['metric'])) or 0 for r in data['rows'])])
        for i,row in enumerate(data['rows']):
            p = row['player']; y = data['header']+data['heading']+i*data['row_height']
            if industrial:
                painter.fillRect(QRectF(8,y,rect.width()-16,data['row_height']-3),QColor(255,255,255,210))
                painter.setPen(QPen(QColor('#bba4ad'),.7))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(QRectF(8,y,rect.width()-16,data['row_height']-3))
            ratio = max(0., min(1., (number(p.get(data['metric'])) or 0)/maximum)) if maximum else 0
            fill = QColor(colors['accent']); fill.setAlpha(35 if data['metric']=='total_damage' else 55)
            painter.fillRect(QRectF(8,y, (rect.width()-16)*ratio,data['row_height']-3),fill)
            if industrial and ratio:
                painter.fillRect(QRectF(8+(rect.width()-16)*ratio-1,y,1,data['row_height']-3),colors['accent'])
            left = 12
            if data['avatar']:
                pixmap = avatar_pixmap(str(p.get('character_key') or ''),data['avatar'],dpr)
                painter.drawPixmap(QRectF(left,y+(data['row_height']-data['avatar'])/2,data['avatar'],data['avatar']),pixmap,pixmap.rect())
                left += data['avatar']+8
            text(painter,QRectF(left,y+3,data['name_width']-(left-12)-8,data['row_height']/2),row['name'],colors['foreground'])
            painter.setFont(data['secondary_font'])
            text(painter,QRectF(left,y+data['row_height']/2,data['name_width']-(left-12)-8,data['row_height']/2-3),row['crit'],colors['muted'])
            painter.setFont(data['stat_font'])
            x = data['name_width']+12
            for size,(display,_) in zip(data['widths'],row['cells']):
                text(painter,QRectF(x,y,size-8,data['row_height']),display,colors['foreground'],Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); x += size
            painter.setFont(data['font'])
        if not data['rows']:
            text(painter,QRectF(12,data['header']+data['heading'],rect.width()-24,data['row_height']),'等待战斗数据',colors['muted'])
        if industrial:
            painter.setFont(data['secondary_font'])
        text(painter,QRectF(12,rect.height()-data['footer'],rect.width()-24,data['footer']),data['status'],colors['foreground'] if industrial else colors['muted'],Qt.AlignmentFlag.AlignCenter if industrial else None)
