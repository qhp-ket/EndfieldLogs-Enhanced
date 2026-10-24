"""Scale existing Fluent fonts without replacing the theme or overlay assets."""
from __future__ import annotations
from PySide6.QtCore import QObject, QEvent, QTimer, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget,
    QApplication,
    QAbstractButton,
    QLineEdit,
    QTableView,
    QListView,
    QKeySequenceEdit,
)
from qfluentwidgets.components.widgets.table_view import TableItemDelegate
from qfluentwidgets.components.widgets.list_view import ListItemDelegate
from qfluentwidgets.components.widgets.switch_button import Indicator, SwitchButton


class _ScaledTableDelegate(TableItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.font = index.data(Qt.ItemDataRole.FontRole) or self.parent().font()
        option.fontMetrics = QFontMetrics(option.font)


class _ScaledListDelegate(ListItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.font = index.data(Qt.ItemDataRole.FontRole) or self.parent().font()
        option.fontMetrics = QFontMetrics(option.font)


def apply_fonts(root: QWidget, scale: float):
    """Capture all unscaled fonts before changing inheritance, then apply once."""
    widgets = [root, *root.findChildren(QWidget)]
    for widget in widgets:
        if widget.property('_gui_base_font') is None:
            parent = widget.parentWidget()
            inherited = parent.property('_gui_base_font') if parent else None
            font = (inherited if inherited is not None and not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont)
                    else widget.font())
            widget.setProperty('_gui_base_font', QFont(font))
        if isinstance(widget, (QAbstractButton, QLineEdit, QKeySequenceEdit)) and not isinstance(widget, Indicator):
            if widget.property('_gui_base_min_height') is None:
                widget.setProperty('_gui_base_min_height', widget.minimumHeight())
                widget.setProperty('_gui_base_max_height', widget.maximumHeight())
    for widget in widgets:
        base = QFont(widget.property('_gui_base_font'))
        if base.pixelSize() > 0:
            base.setPixelSize(max(9, round(base.pixelSize()*scale)))
        else:
            base.setPointSizeF(max(7., base.pointSizeF()*scale))
        if widget.font() != base:
            widget.setFont(base)
        if widget.property('_gui_base_min_height') is not None:
            minimum = max(round(widget.property('_gui_base_min_height')*scale), QFontMetrics(base).height()+10)
            maximum = widget.property('_gui_base_max_height')
            widget.setMinimumHeight(minimum)
            if maximum < 16777215:
                widget.setMaximumHeight(max(minimum, round(maximum*scale)))
        if isinstance(widget, SwitchButton):
            widget.setFixedHeight(max(22, QFontMetrics(base).height()+4))
        if isinstance(widget, (QTableView, QListView)):
            delegate = widget.itemDelegate()
            if isinstance(delegate, TableItemDelegate) and not isinstance(delegate, (_ScaledTableDelegate, _ScaledListDelegate)):
                replacement = (_ScaledListDelegate if isinstance(delegate, ListItemDelegate) else _ScaledTableDelegate)(widget)
                for key in ('hoverRow', 'pressedRow', 'selectedRows', 'lightCheckedColor', 'darkCheckedColor'):
                    setattr(replacement, key, getattr(delegate, key))
                widget.setItemDelegate(replacement)
                widget.delegate = replacement
                delegate.deleteLater()
            if isinstance(widget, QTableView):
                header = widget.verticalHeader()
                if header.property('_gui_base_row_height') is None:
                    header.setProperty('_gui_base_row_height', header.defaultSectionSize())
                header.setDefaultSectionSize(max(QFontMetrics(base).height()+8, round(header.property('_gui_base_row_height')*scale)))
                top = widget.horizontalHeader()
                if top.minimumHeight() == top.maximumHeight() or top.property('_gui_base_fixed_height') is not None:
                    if top.property('_gui_base_fixed_height') is None:
                        top.setProperty('_gui_base_fixed_height', top.height())
                    top.setFixedHeight(max(QFontMetrics(base).height()+12, round(top.property('_gui_base_fixed_height')*scale)))
        callback = getattr(widget, 'set_gui_font_scale', None)
        if callable(callback):
            callback(scale)
        widget.updateGeometry()
    root.setProperty('gui_font_scale', scale)


class GuiTypography(QObject):
    def __init__(self, root: QWidget, scale=1.15):
        super().__init__(root)
        self.root, self.scale = root, scale
        self._applying = self._pending = False
        QApplication.instance().installEventFilter(self)
        self.apply()

    def set_scale(self, scale):
        self.scale = max(.8, min(1.8, float(scale)))
        self.apply()

    def apply(self):
        self._pending = False
        if self._applying:
            return
        self._applying = True
        try:
            apply_fonts(self.root, self.scale)
        finally:
            self._applying = False

    def eventFilter(self, watched, event):
        if (not self._applying and not self._pending and isinstance(watched, QWidget)
                and event.type() in (QEvent.Type.ChildPolished, QEvent.Type.FontChange, QEvent.Type.Show)):
            parent = watched
            while parent is not None and parent is not self.root:
                parent = parent.parentWidget()
            if parent is self.root:
                self._pending = True
                QTimer.singleShot(0, self, self.apply)
        return False
