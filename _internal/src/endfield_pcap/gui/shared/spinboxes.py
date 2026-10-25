"""Keep Fluent numeric editors usable with Qt's NoButtons style geometry."""
from PySide6.QtCore import QEvent
from PySide6.QtGui import QFontMetrics
from qfluentwidgets import SpinBox, DoubleSpinBox


class _ReadableEditor:
    def _layout_editor(self):
        if not hasattr(self, 'hBoxLayout'):
            return
        # Qt 6.12 can return a one-pixel editor for NoButtons + a stylesheet.
        # Fluent draws its own buttons; reserve their actual layout width.
        reserved = self.hBoxLayout.minimumSize().width()
        self.lineEdit().setGeometry(11, 1, max(1, self.width()-reserved-15), self.height()-2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_editor()

    def showEvent(self, event):
        super().showEvent(event)
        self.set_gui_font_scale(1)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self._layout_editor()

    def set_gui_font_scale(self, _scale):
        metrics = QFontMetrics(self.font())
        text = self.prefix()+self.textFromValue(self.maximum())+self.suffix()
        self.setMinimumWidth(metrics.horizontalAdvance(text)+self.hBoxLayout.minimumSize().width()+28)
        self.setFixedHeight(max(33, metrics.height()+12))
        self._layout_editor()


class ReadableSpinBox(_ReadableEditor, SpinBox):
    pass


class ReadableDoubleSpinBox(_ReadableEditor, DoubleSpinBox):
    pass
