"""Four observed slots; drawing never infers a cooldown or character identity."""
from PySide6.QtCore import Qt, QRectF, QSizeF
from PySide6.QtGui import QFontMetricsF, QPen, QColor, QPainterPath
from endfield_pcap.gui.shared.avatars import avatar_pixmap
from .model import Layout, SnapshotGate, number, font, palette, text


class ComboModule:
    def __init__(self):
        self.gate = SnapshotGate()
        self.settings, self.theme, self.snapshot = {}, {}, {}
        self.connected = True

    def apply_config(self, settings, theme):
        self.settings, self.theme = settings, theme

    def receive(self, message):
        snapshot = message.get('snapshot') if isinstance(message,dict) else None
        if not isinstance(snapshot,dict) or not isinstance(snapshot.get('slots'),list): return False
        if not self.gate.accept(message, {'combo_snapshot'}, 2): return False
        changed = self.snapshot != snapshot
        self.snapshot = snapshot
        return changed

    def measure(self, width=None):
        bars = self.settings.get('display_style') == 'bars'
        normal = font(self.settings,self.theme)
        fm = QFontMetricsF(normal)
        scale = max(.5,min(3.,(number(self.settings.get('avatar_size_percent')) or 100)/100))
        avatar = (32 if bars else 60)*scale
        slots = []
        for i in range(4):
            item = next((s for s in self.snapshot.get('slots',[]) if isinstance(s,dict) and s.get('slot')==i),{})
            status = item.get('status','unknown')
            p = number(item.get('progress'))
            progress = max(0., min(1.,p)) if p is not None else None
            remaining = number(item.get('estimated_remaining_ms'))
            label = {'ready':'CD 就绪','unknown':'—','dead':'阵亡','empty':'空位'}.get(status,
                (f'{progress*100:.0f}%' if progress is not None else '—')+' · '+(f'≈{remaining/1000:.1f}s' if remaining is not None else '—'))
            name = str(item.get('display_name') or f'位置 {i+1}')
            tip = name+'\n'+label+'\n'+('沿用上次识别，秒数按已有速度估算' if item.get('held') else '图像观测')+'；CD 就绪不等于满足连携触发条件'
            slots.append(dict(item=item, name=name, status=status, progress=progress, label=label, tip=tip))
        held = any(s['item'].get('held') and s['status']!='unknown' for s in slots)
        status = '沿用上次状态' if held else str(self.snapshot.get('status') or '等待图像识别')
        if not self.connected: status += ' / 连接断开'
        top = fm.height()+18
        if bars:
            row = max(avatar+10,fm.height()*2+12)
            natural_width = max(420., avatar+max(fm.horizontalAdvance(s['name']) for s in slots)+200)
            size = QSizeF(width or natural_width,top+row*4+8)
        else:
            cell = max(90.,avatar+20,min(180.,max(fm.horizontalAdvance(s['name'])+12 for s in slots)))
            row = avatar+fm.height()*2+24
            size = QSizeF(cell*4+24,top+row+8)
        result = Layout(size, data=dict(font=normal,slots=slots,bars=bars,avatar=avatar,top=top,row=row,status=status,label_height=fm.height()+6))
        for i,s in enumerate(slots):
            rect = QRectF(8,top+i*row,size.width()-16,row) if bars else QRectF(12+i*(size.width()-24)/4,top,(size.width()-24)/4,row)
            result.hits.append((rect,s['tip']))
        result.hits.append((QRectF(0,0,size.width(),top),str(self.snapshot.get('status') or '等待图像识别')))
        return result

    def paint(self,painter,rect,layout,dpr):
        data=layout.data; colors=palette(self.settings,self.theme)
        painter.setFont(data['font'])
        industrial = self.settings.get('theme') == 'endfield'
        if industrial:
            from .decoration import industrial_panel
            industrial_panel(painter, rect, data['top'])
        text(painter,QRectF(12,4,rect.width()-48,data['top']-4),data['status'],QColor('#feef00') if industrial else colors['muted'])
        for i,(slot,(area,_)) in enumerate(zip(data['slots'],layout.hits)):
            color = colors['ready'] if slot['status']=='ready' else colors['accent']
            if slot['status'] in {'unknown','dead','empty'}: color=colors['muted']
            if slot['status']=='ready':
                background = QColor(color)
                background.setAlpha(115)
                painter.setPen(QPen(color, 1.2))
                painter.setBrush(background)
                painter.drawRoundedRect(area.adjusted(2, 2, -2, -2), 4, 4)
            avatar=data['avatar']; bars=data['bars']
            icon=QRectF(area.left()+4 if bars else area.center().x()-avatar/2,area.top()+4,avatar,avatar)
            painter.setPen(QPen(color,2.5 if slot['status']=='ready' else 1.2))
            painter.setBrush(QColor(70,80,94,70)); painter.drawEllipse(icon)
            key=slot['item'].get('character_key')
            if key and self.settings.get('show_character_avatars')!='off':
                painter.save(); path=QPainterPath(); path.addEllipse(icon.adjusted(2,2,-2,-2));painter.setClipPath(path)
                pixmap=avatar_pixmap(str(key),avatar,dpr)
                painter.drawPixmap(icon,pixmap,pixmap.rect());painter.restore()
            else:
                text(painter,icon,str(i+1),color,Qt.AlignmentFlag.AlignCenter)
            p=slot['progress']
            if not bars and p is not None:
                painter.setPen(QPen(color,4));painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawArc(icon,90*16,-round(p*360*16))
            if bars:
                left=icon.right()+10; width=max(1.,area.right()-left-8)
                label_width=min(width*.65,QFontMetricsF(data['font']).horizontalAdvance(slot['label'])+8)
                text(painter,QRectF(left,area.top(),max(0.,width-label_width-6),data['row']/2),slot['name'],colors['foreground'])
                track=QRectF(left,area.top()+data['row']/2+3,width,8)
                painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor(110,125,145,65));painter.drawRoundedRect(track,3,3)
                painter.setBrush(color);painter.drawRoundedRect(QRectF(track.left(),track.top(),track.width()*(p or 0),track.height()),3,3)
                text(painter,QRectF(left+width-label_width,area.top(),label_width,data['row']/2),slot['label'],color,Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter)
            else:
                label_height=data['label_height']
                text(painter,QRectF(area.left()+3,icon.bottom()+5,area.width()-6,label_height),slot['name'],colors['foreground'],Qt.AlignmentFlag.AlignCenter)
                text(painter,QRectF(area.left()+3,icon.bottom()+5+label_height,area.width()-6,label_height),slot['label'],color,Qt.AlignmentFlag.AlignCenter)
