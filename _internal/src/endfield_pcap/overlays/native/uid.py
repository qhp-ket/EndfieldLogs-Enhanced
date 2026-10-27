from PySide6.QtCore import QSizeF, Qt
from PySide6.QtGui import QColor
from .model import Layout


class UidMaskModule:
    def apply_config(self,settings,theme):
        self.settings=settings

    def receive(self,message):
        return False

    def measure(self,width=None):
        return Layout(QSizeF(width or 220,32))

    def paint(self,painter,rect,layout,dpr):
        painter.setPen(Qt.PenStyle.NoPen);painter.setBrush(QColor('black'))
        radius=6 if self.settings.get('shape')=='rounded' else 0
        painter.drawRoundedRect(rect,radius,radius)
