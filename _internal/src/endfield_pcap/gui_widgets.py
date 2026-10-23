"""Shared Fluent page primitives; no application/service orchestration."""
from PySide6.QtCore import Signal, Qt, QRectF
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QKeySequenceEdit, QSizePolicy
from qfluentwidgets import ScrollArea, LineEdit, PushButton, SwitchButton as _SwitchButton
from qfluentwidgets.components.widgets.switch_button import Indicator
from .gui_scrolling import install_immediate_scrolling


class _StableIndicator(Indicator):
    def _toggleSlider(self):
        # Programmatic refresh and blocked signals must never leave an on
        # switch looking off. Position is derived from actual checked state.
        self.slideAni.stop()
        self.setSliderX(25 if self.isChecked() else 5)

    def _drawCircle(self, painter):
        inset = 5.
        diameter = self.height()-2*inset
        x = self.width()-inset-diameter if self.isChecked() else inset
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._sliderColor())
        painter.drawEllipse(QRectF(x, inset, diameter, diameter))


class FluentSwitchButton(_SwitchButton):
    """Keep Fluent colors/layout, render the knob from checked state."""
    def __init__(self, parent=None):
        super().__init__(parent)
        original = self.indicator
        self.indicator = _StableIndicator(self)
        self.hBox.replaceWidget(original, self.indicator)
        original.hide()
        original.deleteLater()
        self.indicator.toggled.connect(self._updateText)
        self.indicator.toggled.connect(self.checkedChanged)


class IntegerStepEdit(QWidget):
    """Discrete integer setting with an editable value and explicit − / +."""
    valueChanged = Signal(int)

    def __init__(self, minimum=80, maximum=180, value=100, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self.decrease_button = PushButton('−', self)
        self.increase_button = PushButton('+', self)
        self.edit = OverlayNumberEdit(self)
        self.edit.setRange(minimum, maximum)
        self.edit.setValue(value)
        self.edit.setMinimumWidth(72)
        self.edit.setMaximumWidth(130)
        for button in (self.decrease_button, self.increase_button):
            button.setFixedWidth(36)
        self.decrease_button.setAccessibleName('减小字号')
        self.increase_button.setAccessibleName('增大字号')
        self.decrease_button.clicked.connect(lambda: self.setValue(self.value()-1))
        self.increase_button.clicked.connect(lambda: self.setValue(self.value()+1))
        self.edit.valueChanged.connect(self._changed)
        for widget in (self.decrease_button, self.edit, self.increase_button):
            layout.addWidget(widget)
        self._changed(value)

    def _changed(self, value):
        self.decrease_button.setEnabled(value > self.edit._minimum)
        self.increase_button.setEnabled(value < self.edit._maximum)
        self.valueChanged.emit(value)

    def value(self):
        return self.edit.value()

    def setValue(self, value):
        self.edit.setValue(value)

class SingleHotkeyEdit(QKeySequenceEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._replace_pending = False

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        self._replace_pending = True
        super().focusInEvent(event)

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        self._replace_pending = False
        super().focusOutEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if self._replace_pending:
            self.clear()
            self._replace_pending = False
        super().keyPressEvent(event)


class InterfacePage(ScrollArea):
    def __init__(self, object_name: str, title: str, subtitle: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        install_immediate_scrolling()
        self.setObjectName(object_name)
        self.setWidgetResizable(True)
        container = QWidget(self)
        self.container = container
        self.setWidget(container)

        self.content_layout = QVBoxLayout(container)
        self.content_layout.setContentsMargins(32, 28, 32, 28)
        self.content_layout.setSpacing(20)


class OverlayNumberEdit(LineEdit):
    """Use the existing Fluent text field for bounded integer input."""
    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._minimum, self._maximum, self._value = 0, 16384, 0
        self._validator = QIntValidator(0, self._maximum, self)
        self.setValidator(self._validator)
        self.setText("0")
        self.editingFinished.connect(self._commit)

    def value(self) -> int:
        return self._value

    def setRange(self, minimum: int, maximum: int) -> None:
        self._minimum, self._maximum = minimum, maximum
        self._validator.setRange(minimum, maximum)
        self.setValue(self._value)

    def setMinimum(self, minimum: int) -> None:
        self.setRange(minimum, self._maximum)

    def setValue(self, value: int) -> None:
        bounded = max(self._minimum, min(self._maximum, value))
        changed = bounded != self._value
        self._value = bounded
        self.setText(str(bounded))
        if changed:
            self.valueChanged.emit(bounded)

    def _commit(self) -> None:
        self.setValue(int(self.text()) if self.text().isdigit() else self._value)

    def focusOutEvent(self, event) -> None:  # noqa: N802
        self._commit()
        super().focusOutEvent(event)


def _format_duration(duration_ms: int) -> str:
    return f"{duration_ms / 1000.0:.2f} 秒"


