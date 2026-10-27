from __future__ import annotations

from dataclasses import replace
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget, QToolButton, QToolTip
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from endfield_pcap.overlays.templates import template_for
from endfield_pcap.overlays.presentation import table_snapshot
from endfield_pcap.overlays.config import OverlayWindowConfig
from endfield_pcap.overlays.native.canvas import OverlayCanvas


class OverlayCloseButton(QToolButton):
    """Native close hit target, independent of the content canvas."""
    hoverChanged = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")
        self._hovered = False

    def enterEvent(self, event):
        self._hovered = True
        self.hoverChanged.emit(True)
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.hoverChanged.emit(False)
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(205, 30, 50, 255))
            painter.drawRoundedRect(self.rect(), 4, 4)
        # Both light and dark strokes are needed over an arbitrary desktop in
        # background-free mode. A quiet normal mark must still remain visible.
        strokes = [(QColor(0, 0, 0, 175), 3.5), (QColor(255, 255, 255, 220), 1.7)]
        if self._hovered:
            strokes = [(QColor(255, 255, 255), 2.0)]
        for color, width in strokes:
            painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(7, 7), QPointF(19, 19))
            painter.drawLine(QPointF(19, 7), QPointF(7, 19))

class OverlayWindow(QWidget):
    def __init__(self, config: OverlayWindowConfig) -> None:
        super().__init__(None)
        self.config = config
        self.entry = config.entry
        self.desktop_visible = config.desktop_visible
        self._drag_origin: QPoint | None = None
        self._drag_size: QSize | None = None
        self._drag_size_timer = QTimer(self)
        self._drag_size_timer.setSingleShot(True)
        self._drag_size_timer.timeout.connect(self._restore_drag_size)
        self._resize_origin: QPoint | None = None
        self._resize_geometry: QRect | None = None
        self._active_edges = Qt.Edge(0)
        self._suppress_geometry_callback = False
        self._close_hovered = False
        self._close_pressed = False
        self._last_geometry_state = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setMinimumSize(config.min_width, config.min_height)
        self.setWindowTitle(self.entry.name)
        self._apply_window_flags()

        self.content_size = None
        self.canvas = OverlayCanvas(self.entry, self)
        self._client = None

        self.close_button = OverlayCloseButton(self)
        self.close_button.setObjectName("overlayCloseButton")
        self.close_button.setToolTip("隐藏此悬浮窗（分析继续运行）")
        self.close_button.setAccessibleName("隐藏此悬浮窗")
        self.close_button.clicked.connect(self.close)
        self.close_button.hoverChanged.connect(self._set_close_hover)
        self.close_button.setVisible(not self.entry.click_through)
        self._apply_initial_geometry()
        self.canvas.resize(self.size())
        self.setWindowOpacity(self.entry.opacity if self.desktop_visible else 0.0)
        if not self.canvas.uid_only:
            from endfield_pcap.overlays.content_size import ContentFitter
            self.content_size = ContentFitter(self)
            self.canvas.naturalSizeChanged.connect(self.content_size.fit)
            self.canvas.relayout()
        if not config.use_in_process_snapshots and template_for(self.entry).subscriptions:
            from endfield_pcap.overlays.client import SnapshotClient
            self._client = SnapshotClient(config.ws_port, config.ws_browser_token, self)
            self._client.snapshot.connect(self.canvas.receive)
            self._client.connectedChanged.connect(self.canvas.set_connected)
            self._client.start()

    def apply_entry(self, entry: OverlayEntry) -> None:
        previous = self.entry
        self.entry = entry
        self.setWindowTitle(entry.name)
        if self.content_size is not None and entry.geometry is None and previous.geometry is not None:
            self.content_size.scale = 1.
            self.content_size.bar_width = None
            self.content_size.reset_position = True
            self.content_size.default_anchor = True
            self.content_size.pending = None
            self.content_size.timer.stop()
        if entry.geometry != previous.geometry:
            if self.content_size is not None and entry.geometry is not None and not self.content_size.resizing:
                self.content_size.reset_position = False
                self.content_size.pending = None
                self.content_size.timer.stop()
            self._suppress_geometry_callback = True
            try:
                self._apply_initial_geometry()
            finally:
                self._suppress_geometry_callback = False
        if previous.click_through != entry.click_through:
            self._apply_window_flags()
        if previous.opacity != entry.opacity:
            self.setWindowOpacity(entry.opacity if self.desktop_visible else 0.0)
        self.close_button.setVisible(not entry.click_through)
        self.close_button.update()
        self.canvas.apply_entry(entry)
        if self.canvas.uid_only and self.content_size is not None:
            self.canvas.naturalSizeChanged.disconnect(self.content_size.fit)
            self.content_size.timer.stop()
            self.content_size.deleteLater()
            self.content_size = None
        elif not self.canvas.uid_only and self.content_size is None:
            from endfield_pcap.overlays.content_size import ContentFitter
            self.content_size = ContentFitter(self)
            self.canvas.naturalSizeChanged.connect(self.content_size.fit)
            self.canvas.relayout()
        if not self.isVisible():
            self.show()
        self._update_cursor(self._hit_test_edges(QPoint()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.canvas.resize(self.size())
        if self.content_size is not None:
            self.content_size.window_resized()
        self.close_button.move(
            max(0, self.width() - self.close_button.width() - 8),
            min(8, max(0, self.height() - self.close_button.height())),
        )
        self.close_button.raise_()
        if self._drag_size is not None and self.size() != self._drag_size:
            # Windows can deliver a transient logical size while Qt switches
            # screens/DPI. Repair outside resizeEvent, without feeding that
            # transient size into either the next move or persisted settings.
            self._drag_size_timer.start(0)
        self._emit_geometry_changed()
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        if self.content_size is not None:
            self.content_size.window_moved()
        self._emit_geometry_changed()
        super().moveEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._handle_mouse_release(QPoint())
        if self.config.on_closed is not None:
            if self.config.hide_on_close:
                event.ignore()
            self.config.on_closed(self.entry.id)
            if self.config.hide_on_close:
                return
        if self._client is not None:
            self._client.stop()
        super().closeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._over_close(event.position().toPoint()):
            self._close_pressed = True
            event.accept()
            return
        if self.entry.locked:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._handle_mouse_press(event.position().toPoint(), event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is not None or self._resize_origin is not None:
            self._handle_mouse_move(event.position().toPoint(), event.globalPosition().toPoint(), event.buttons())
            event.accept()
            return
        self._set_close_hover(self._over_close(event.position().toPoint()))
        if self._close_hovered:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
        tip = self.canvas.tooltip(event.position())
        if tip:
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()
        if self.entry.locked:
            self.unsetCursor()
            return
        self._handle_mouse_move(event.position().toPoint(), event.globalPosition().toPoint(), event.buttons())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._close_pressed:
            self._close_pressed = False
            if event.button() == Qt.MouseButton.LeftButton and self._over_close(event.position().toPoint()):
                self.close()
            event.accept()
            return
        self._handle_mouse_release(event.position().toPoint())
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._set_close_hover(False)
        if self._drag_origin is None and self._resize_origin is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def _over_close(self, position: QPoint) -> bool:
        return not self.entry.click_through and self.close_button.geometry().contains(position)

    def _set_close_hover(self, hovered: bool) -> None:
        hovered = bool(hovered and not self.entry.click_through)
        if self._close_hovered == hovered:
            return
        self._close_hovered = hovered
        self.close_button.update()

    def wheelEvent(self, event):
        event.ignore()

    def _apply_initial_geometry(self) -> None:
        if self.entry.geometry is not None:
            geometry = self.entry.geometry
            self.setGeometry(geometry.x, geometry.y, geometry.width, geometry.height)
            return
        width = max(self.minimumWidth(), self.config.default_width)
        height = max(self.minimumHeight(), self.config.default_height)
        self.resize(width, height)
        self._move_to_default_position()

    def _move_to_default_position(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        uid_mask = self.entry.source_type == OverlaySourceType.BUILTIN and self.entry.source_value == "uid_mask"
        geometry = screen.geometry() if uid_mask else screen.availableGeometry()
        x = geometry.x() + 12 if uid_mask else geometry.x() + geometry.width() - self.width() - self.config.margin_right
        y = geometry.bottom() - self.height() - 10 if uid_mask else geometry.y() + self.config.margin_top
        self.move(max(geometry.x(), x), max(geometry.y(), y))

    def _apply_window_flags(self) -> None:
        was_visible = self.isVisible()
        # OBS excludes WS_EX_TOOLWINDOW. Keep a normal top-level window even
        # when toggling click-through; showing an overlay must not take focus.
        flags = (Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                 | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        if self.entry.click_through or not self.desktop_visible:
            flags |= Qt.WindowType.WindowTransparentForInput
        self.setWindowFlags(flags)
        if was_visible:
            self.show()

    def set_desktop_visible(self, visible: bool) -> None:
        """Keep the native window and its backing surface alive for WGC capture.

        Zero desktop alpha affects composition on the monitor, while WGC keeps
        capturing the underlying surface. Never hide/minimize/move the HWND.
        """
        visible = bool(visible)
        if visible == self.desktop_visible:
            return
        self.desktop_visible = visible
        self.setWindowOpacity(self.entry.opacity if visible else 0.0)
        self._apply_window_flags()

    def apply_analysis_snapshot(self, message):
        if 'analysis_summary' in template_for(self.entry).subscriptions:
            self.canvas.receive(table_snapshot(self.entry, message))

    def apply_analysis_summary(self, message):
        self.apply_analysis_snapshot(message)

    def apply_combo_snapshot(self, message):
        if 'combo_snapshot' in template_for(self.entry).subscriptions:
            self.canvas.receive(message)

    def _emit_geometry_changed(self) -> None:
        if self._suppress_geometry_callback or self.config.on_geometry_changed is None:
            return
        if self._drag_size is not None and self.size() != self._drag_size:
            return
        geometry = self.geometry()
        geometry_value = OverlayGeometry(
                x=geometry.x(),
                y=geometry.y(),
                width=geometry.width(),
                height=geometry.height(),
            )
        self.entry = replace(self.entry, geometry=geometry_value)
        if self.content_size is not None and self.content_size.scale is not None:
            self.entry = replace(self.entry, template_settings={
                **self.entry.template_settings, self.content_size.scale_setting: self.content_size.scale})
        # Persisting and refreshing the settings page on every mouse move
        # blocks dragging. Publish the final geometry once on release.
        if self._drag_origin is not None or self._resize_origin is not None:
            return
        state = (geometry_value.x,geometry_value.y,geometry_value.width,geometry_value.height,
                 self.content_size.scale if self.content_size else None)
        if state == self._last_geometry_state:
            return
        self._last_geometry_state = state
        self.config.on_geometry_changed(self.entry.id, geometry_value)

    def _handle_mouse_press(self, local_pos: QPoint, global_pos: QPoint) -> None:
        QToolTip.hideText()
        self._set_close_hover(False)
        edges = self._hit_test_edges(local_pos)
        if edges != Qt.Edge(0):
            self._resize_origin = global_pos
            self._resize_geometry = self.geometry()
            self._active_edges = edges
            return
        self._drag_origin = global_pos - self.frameGeometry().topLeft()
        self._drag_size = self.size()

    def _restore_drag_size(self) -> None:
        if self._drag_size is not None and self.size() != self._drag_size:
            self.resize(self._drag_size)

    def _handle_mouse_move(self, local_pos: QPoint, global_pos: QPoint, buttons) -> None:
        edges = self._hit_test_edges(local_pos)
        if self._resize_origin is not None and self._resize_geometry is not None:
            self._resize_from_drag(global_pos)
            return
        if self._drag_origin is not None and buttons & Qt.MouseButton.LeftButton:
            # Supplying the original size explicitly prevents QWidget.move()
            # from repeatedly rescaling an intermediate cross-screen size.
            self.setGeometry(QRect(global_pos - self._drag_origin, self._drag_size))
            return
        self._update_cursor(edges)

    def _handle_mouse_release(self, local_pos: QPoint) -> None:
        self._drag_size_timer.stop()
        self._restore_drag_size()
        self._drag_origin = None
        self._drag_size = None
        self._resize_origin = None
        self._resize_geometry = None
        self._active_edges = Qt.Edge(0)
        self._emit_geometry_changed()
        self._update_cursor(self._hit_test_edges(local_pos))

    def _hit_test_edges(self, pos: QPoint):
        if self.entry.locked:
            return Qt.Edge(0)
        margin = self.config.resize_margin
        edges = Qt.Edge(0)
        if pos.x() <= margin:
            edges |= Qt.Edge.LeftEdge
        elif pos.x() >= self.width() - margin:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= margin:
            edges |= Qt.Edge.TopEdge
        elif pos.y() >= self.height() - margin:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _update_cursor(self, edges) -> None:
        if self.entry.locked:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return
        if edges == (Qt.Edge.LeftEdge | Qt.Edge.TopEdge) or edges == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges == (Qt.Edge.RightEdge | Qt.Edge.TopEdge) or edges == (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif edges in {Qt.Edge.LeftEdge, Qt.Edge.RightEdge}:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif edges in {Qt.Edge.TopEdge, Qt.Edge.BottomEdge}:
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def _resize_from_drag(self, global_pos: QPoint) -> None:
        assert self._resize_origin is not None
        assert self._resize_geometry is not None

        delta = global_pos - self._resize_origin
        geometry = QRect(self._resize_geometry)
        min_width = self.minimumWidth()
        min_height = self.minimumHeight()

        if self._active_edges & Qt.Edge.LeftEdge:
            new_left = geometry.left() + delta.x()
            max_left = geometry.right() - min_width + 1
            geometry.setLeft(min(new_left, max_left))
        if self._active_edges & Qt.Edge.RightEdge:
            geometry.setWidth(max(min_width, geometry.width() + delta.x()))
        if self._active_edges & Qt.Edge.TopEdge:
            new_top = geometry.top() + delta.y()
            max_top = geometry.bottom() - min_height + 1
            geometry.setTop(min(new_top, max_top))
        if self._active_edges & Qt.Edge.BottomEdge:
            geometry.setHeight(max(min_height, geometry.height() + delta.y()))

        self.setGeometry(geometry)
