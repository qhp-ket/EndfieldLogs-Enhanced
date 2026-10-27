"""Shared quiet colors and stable logical stroke widths for native plots."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPen

ROLE_COLORS = ('#328cb5', '#bd8542', '#9272c2', '#339c85', '#c26c83', '#818b9b')
CATEGORY_COLORS = {'重击': '#687f97', '战技': '#398c80', '大招': '#a58042',
                   '连携': '#8972ae', '其他': '#747e8b', 'BUFF': '#a9687c'}


def stroke(color, width=1., style=Qt.PenStyle.SolidLine):
    pen = QPen(QColor(color), width, style)
    pen.setCosmetic(True)
    return pen


def compact_number(value):
    return f'{value/1e6:.1f}M' if abs(value) >= 1e6 else f'{value/1000:.1f}k' if abs(value) >= 1000 else f'{value:g}'
