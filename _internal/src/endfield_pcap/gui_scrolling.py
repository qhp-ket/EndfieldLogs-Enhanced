"""Immediate wheel steps for native and Fluent scroll viewports."""
from PySide6.QtCore import QObject, QEvent, Qt
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QWidget


class ImmediateWheelScroll(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        area = watched.parentWidget()
        if not isinstance(area, QAbstractScrollArea) or watched is not area.viewport():
            return False
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return False
        if event.phase() == Qt.ScrollPhase.ScrollMomentum:
            event.accept()
            return True
        horizontal = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier) or (
            abs(event.angleDelta().x()) > abs(event.angleDelta().y()))
        bar = area.horizontalScrollBar() if horizontal else area.verticalScrollBar()
        pixels = event.pixelDelta()
        delta = (pixels.x() or pixels.y()) if horizontal else pixels.y()
        if not delta:
            angle = (event.angleDelta().x() or event.angleDelta().y()) if horizontal else event.angleDelta().y()
            delta = angle/120 * bar.singleStep() * QApplication.wheelScrollLines()
        previous = bar.value()
        bar.setValue(previous-round(delta))
        if bar.value() == previous and delta:
            # Chain at the edge without dispatching back into Fluent's
            # smoothing delegate (which would leave a queued animation).
            parent = area.parentWidget()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    outer = parent.horizontalScrollBar() if horizontal else parent.verticalScrollBar()
                    before = outer.value()
                    outer.setValue(before-round(delta))
                    if outer.value() != before:
                        break
                parent = parent.parentWidget()
        event.accept()
        return True


def install_immediate_scrolling():
    app = QApplication.instance()
    if app is not None and not hasattr(app, '_immediate_wheel_scroll'):
        app._immediate_wheel_scroll = ImmediateWheelScroll(app)
        app.installEventFilter(app._immediate_wheel_scroll)
