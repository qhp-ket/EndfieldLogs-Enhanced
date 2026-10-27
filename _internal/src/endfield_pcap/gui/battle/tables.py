"""Consistent evidence tables with numeric sorting and portable column widths."""
import math
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QTableWidgetItem, QHeaderView, QApplication
from qfluentwidgets import isDarkTheme
from qfluentwidgets.components.widgets.table_view import TableItemDelegate


class EvidenceItem(QTableWidgetItem):
    def __init__(self, text, value=None):
        super().__init__(str(text))
        self.setToolTip(str(text))
        if value is None:
            try:
                value = float(str(text).replace(',', '').removesuffix('%'))
            except ValueError:
                pass
        self.numeric = value if isinstance(value, (int, float)) and math.isfinite(value) else None
        if self.numeric is not None:
            self.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def __lt__(self, other):
        if isinstance(other, EvidenceItem) and (self.numeric is not None or other.numeric is not None):
            return (self.numeric is not None, self.numeric or 0.) < (other.numeric is not None, other.numeric or 0.)
        return super().__lt__(other)


class _RowDelegate(TableItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        painter.setPen(QPen(QColor('#34383f' if isDarkTheme() else '#e7eaee'), .7))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()


def style_table(view):
    view.setShowGrid(False)
    view.setAlternatingRowColors(True)
    view.setWordWrap(False)
    view.setTextElideMode(Qt.TextElideMode.ElideRight)
    view.setItemDelegate(_RowDelegate(view))
    view.horizontalHeader().setMinimumSectionSize(40)


def remember_columns(dialog, view, key):
    """Save only user drags; automatic font/avatar measurements stay automatic."""
    header = view.horizontalHeader()
    view.resizeColumnsToContents()
    header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    header.setStretchLastSection(True)
    owner = dialog.parentWidget()
    while owner is not None and not hasattr(owner, 'app_config'):
        owner = owner.parentWidget()
    config = getattr(owner, 'app_config', None)
    widths = getattr(config, 'battle_table_widths', {}).get(key, [])
    for column, width in enumerate(widths[:view.columnCount()]):
        view.setColumnWidth(column, width)
    timer = QTimer(view)
    timer.setSingleShot(True)
    timer.setInterval(350)

    def save():
        if config is not None and hasattr(owner, 'config_path'):
            from endfield_pcap.gui.config import save_app_config
            config.battle_table_widths[key] = [view.columnWidth(i) for i in range(view.columnCount())]
            save_app_config(config, owner.config_path)

    def changed(*_):
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            timer.start()

    header.sectionResized.connect(changed)
    timer.timeout.connect(save)
    # Flush pending user changes before the dialog destroys the timer.
    dialog.finished.connect(lambda *_: save() if timer.isActive() else None)
    return timer
