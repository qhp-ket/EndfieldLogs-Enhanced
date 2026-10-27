"""Small immutable presentation values; no capture or combat calculation."""
from dataclasses import dataclass, field
import math
from PySide6.QtCore import QRectF, QSizeF
from PySide6.QtGui import QColor, QFont, QFontMetricsF


def number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def formatted(value, digits=0, compact=False):
    value = number(value)
    if value is None:
        return '—'
    return f'{value/1e6:,.2f}M' if compact and abs(value) >= 1e6 else f'{value:,.{digits}f}'


def clock(value):
    value = number(value)
    if value is None:
        return '—'
    seconds = max(0, int(value/1000))
    return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'


class SnapshotGate:
    def __init__(self):
        self.stream = None
        self.sequence = -1
        self.retired = set()

    def accept(self, message, kind, version):
        if (not isinstance(message, dict) or message.get('type') not in kind
                or message.get('schema_version') != version
                or not isinstance(message.get('stream_id'), str) or not message['stream_id']
                or type(message.get('sequence')) is not int or message['sequence'] < 0
                or message.get('snapshot') is not None and not isinstance(message['snapshot'], dict)):
            return False
        stream, seq = message['stream_id'], message['sequence']
        if stream in self.retired or stream == self.stream and seq <= self.sequence:
            return False
        if self.stream and stream != self.stream:
            self.retired.add(self.stream)
        self.stream, self.sequence = stream, seq
        return True


@dataclass
class Layout:
    size: QSizeF
    hits: list = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def tooltip(self, point):
        return '\n'.join(dict.fromkeys(text for rect, text in self.hits if rect.contains(point) and text))


def font(settings, theme, size=13):
    result = QFont(theme.get('font_family', 'Microsoft YaHei UI'))
    result.setPixelSize(max(8, round(size*settings.get('_font_scale', 1.))))
    return result


def palette(settings, overrides):
    dark = settings.get('theme') in {'dark', 'transparent'}
    colors = dict(background='#20252d' if dark else '#f3f6fa',
        foreground='#f0f3f7' if dark else '#28313c', muted='#a9b3c2' if dark else '#667587',
        accent='#168c9e', ready='#6ede99' if dark else '#23884c', border='#485261' if dark else '#c7d0dc')
    if settings.get('theme') == 'transparent':
        colors['background'] = 'transparent'
    elif settings.get('theme') == 'endfield':
        colors.update(background='#f0f0ec', foreground='#1a1c1c', muted='#6a685b',
                      accent='#c4193c', ready='#23884c', border='#1a1c1c')
    colors.update({k:v for k,v in overrides.items() if k in colors})
    return {key: QColor(value) for key,value in colors.items()}


def text(painter, rect, value, color, align=None):
    from PySide6.QtCore import Qt
    painter.setPen(color)
    align = align or (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    fm = QFontMetricsF(painter.font())
    value = fm.elidedText(str(value), Qt.TextElideMode.ElideRight, max(1, int(rect.width())))
    painter.drawText(rect, align, value)
