"""Static industrial skin ornaments, drawn only with the overlay's normal paint."""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPen


INK = QColor('#101111')
YELLOW = QColor('#feef00')


def striped_band(painter, rect):
    painter.save()
    painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    painter.fillRect(rect, YELLOW)
    painter.setPen(QPen(QColor('#d4c700'), 4))
    start = int(rect.left()-rect.height())
    for x in range(start, int(rect.right()+rect.height())+8, 8):
        painter.drawLine(QPointF(x, rect.bottom()), QPointF(x+rect.height(), rect.top()))
    painter.restore()


def industrial_panel(painter, rect, header_height, footer_height=0):
    """Use existing header/footer space; retain all measured content positions."""
    painter.save()
    painter.setClipRect(rect, Qt.ClipOperation.IntersectClip)
    painter.fillRect(QRectF(rect.left(), rect.top(), rect.width(), header_height), INK)
    painter.save()
    painter.setClipRect(QRectF(rect.left(), rect.top(), rect.width(), 4), Qt.ClipOperation.IntersectClip)
    painter.setPen(QPen(QColor(254,239,0,45),1))
    for x in range(int(rect.left()), int(rect.right())+16, 12):
        painter.drawLine(QPointF(x, rect.top()), QPointF(x+4, rect.top()+4))
    painter.restore()
    # Quiet bottom-right hatch, behind the rows and their labels.
    corner = QRectF(max(rect.left(), rect.right()-100), max(rect.top()+header_height, rect.bottom()-100-footer_height),
                    min(100., rect.width()), min(100., max(0., rect.height()-header_height-footer_height)))
    painter.save()
    painter.setClipRect(corner, Qt.ClipOperation.IntersectClip)
    painter.setPen(QPen(QColor(26, 28, 28, 12), .8))
    for offset in range(-100, 210, 10):
        painter.drawLine(QPointF(corner.left()+offset, corner.bottom()),
                         QPointF(corner.left()+offset+corner.height(), corner.top()))
    painter.restore()
    if footer_height:
        striped_band(painter, QRectF(rect.left(), rect.bottom()-footer_height, rect.width(), footer_height))
        painter.fillRect(QRectF(rect.left(), rect.bottom()-footer_height, rect.width(), 2), INK)
    painter.setPen(QPen(INK, 2))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRect(rect.adjusted(1, 1, -1, -1))
    painter.setPen(QPen(QColor('#bfb400'), .8))
    for x, direction in ((rect.left()+1, 1), (rect.right()-1, -1)):
        painter.drawLine(QPointF(x, rect.top()+16), QPointF(x, rect.top()+1))
        painter.drawLine(QPointF(x, rect.top()+1), QPointF(x+16*direction, rect.top()+1))
    painter.restore()
