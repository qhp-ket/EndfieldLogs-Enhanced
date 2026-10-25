from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, QTimer, QUrl, QUrlQuery, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QToolButton
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from endfield_pcap.overlays.templates import ASSETS, template_for, template_values
from endfield_pcap.overlays.presentation import overlay_config, table_snapshot
from endfield_pcap.runtime.paths import bundle_root
from endfield_pcap.overlays.config import OverlayWindowConfig, _builtin_overlay_index


class OverlayCloseButton(QToolButton):
    """Native hit target, with a paint fallback until the web mark is ready."""
    hoverChanged = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")
        self._hovered = False
        self.renderer_ready = False

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
        if self.renderer_ready:
            return
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
        self._analysis_snapshot: dict[str, object] | None = None
        self._combo_snapshot: dict[str, object] | None = None
        self._buff_snapshot: dict[str, object] | None = None
        self._input_snapshot = None
        self._close_hovered = False
        self._close_pressed = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMouseTracking(True)
        self.setMinimumSize(config.min_width, config.min_height)
        self.setWindowTitle(self.entry.name)
        self._apply_window_flags()

        self.webview = QWebEngineView(self)
        self.webview.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.webview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.webview.page().setBackgroundColor(QColor(0, 0, 0, 0))
        self.webview.setStyleSheet("background: transparent; border: 0;")
        self.webview.setMouseTracking(True)
        self.webview.loadStarted.connect(self._handle_load_started)
        self.webview.loadFinished.connect(self._handle_load_finished)

        self.content_size = None

        script = QWebEngineScript()
        script.setName("endfield-host-bridge")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode((ASSETS / "shared/host_bridge.js").read_text(encoding="utf-8"))
        self.webview.page().scripts().insert(script)
        self.close_button = OverlayCloseButton(self)
        self.close_button.setObjectName("overlayCloseButton")
        self.close_button.setToolTip("隐藏此悬浮窗（分析继续运行）")
        self.close_button.setAccessibleName("隐藏此悬浮窗")
        self.close_button.clicked.connect(self.close)
        self.close_button.hoverChanged.connect(self._set_close_hover)
        self.close_button.setVisible(not self.entry.click_through)
        self._apply_initial_geometry()
        self.webview.resize(self.size())
        self.setWindowOpacity(self.entry.opacity if self.desktop_visible else 0.0)
        self.webview.setZoomFactor(1.0)
        self._load_overlay()

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
        self._push_overlay_state()
        if (
            previous.source_type != entry.source_type
            or previous.source_value != entry.source_value
        ):
            self._load_overlay()
        if not self.isVisible():
            self.show()
        self._update_cursor(self._hit_test_edges(QPoint()))

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.webview.resize(self.size())
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
        if self.config.on_closed is not None:
            if self.config.hide_on_close:
                event.ignore()
            self.config.on_closed(self.entry.id)
            if self.config.hide_on_close:
                return
        super().closeEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # WebEngine can cover native sibling widgets on Windows. The same hit
        # target works at the host too, including when position is locked.
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
        self._set_close_hover(self._over_close(event.position().toPoint()))
        if self._close_hovered:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            return
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
        self.webview.page().runJavaScript(
            "window.endfieldOverlay?.setCloseHover?.(" + ("true" if hovered else "false") + ");")

    def wheelEvent(self, event) -> None:  # noqa: N802
        # Web content is mouse-transparent to support native window dragging.
        # Forward the wheel to a template's explicitly declared scroll region.
        delta = -event.angleDelta().y()
        self.webview.page().runJavaScript(
            f"document.querySelector('[data-overlay-scroll]')?.scrollBy(0, {delta});"
        )
        event.accept()

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
        """Keep the native window and Chromium surface alive for WGC capture.

        Zero desktop alpha affects composition on the monitor, while WGC keeps
        capturing the underlying surface. Never hide/minimize/move the HWND.
        """
        visible = bool(visible)
        if visible == self.desktop_visible:
            return
        self.desktop_visible = visible
        self.setWindowOpacity(self.entry.opacity if visible else 0.0)
        self._apply_window_flags()

    def _load_overlay(self) -> None:
        if (self.content_size is None and self.entry.source_type == OverlaySourceType.BUILTIN
                and self.entry.source_value in ('damage', 'combo_skill')):
            from endfield_pcap.overlays.content_size import ContentSizeBridge
            self.content_size = ContentSizeBridge(self)
        template = template_for(self.entry)
        if template.entry is not None:
            url = QUrl.fromLocalFile(str(template.entry))
        elif self.entry.source_type == OverlaySourceType.BUILTIN:
            url = QUrl.fromLocalFile(str(_builtin_overlay_index(self.entry.source_value).resolve()))
        elif self.entry.source_type == OverlaySourceType.FILE:
            url = QUrl.fromLocalFile(str(Path(self.entry.source_value).resolve()))
        else:
            url = QUrl.fromUserInput(self.entry.source_value)
        if not url.isLocalFile():
            self.webview.setUrl(url)
            return
        query = QUrlQuery(url)
        query.addQueryItem("wsPort", str(self.config.ws_port))
        # Never disclose the capability to an arbitrary remote template URL.
        if url.isLocalFile() and not self.config.use_in_process_snapshots and self.config.ws_browser_token:
            query.addQueryItem('wsToken', self.config.ws_browser_token)
        query.addQueryItem("builtin", self.entry.source_value or "damage")
        values = template_values(self.entry, template)
        query.addQueryItem("barMode", str(values.get("bar_mode", self.entry.bar_mode)))
        query.addQueryItem("columns", ",".join(values.get("columns", self.entry.visible_columns)))
        query.addQueryItem("theme", str(values.get("theme", self.entry.overlay_theme)))
        query.addQueryItem("fontScale", str(self.entry.font_scale))
        query.addQueryItem("locked", "1" if self.entry.locked else "0")
        query.addQueryItem("assetRoot", str(bundle_root()))
        if self.config.use_in_process_snapshots and bool(template.subscriptions):
            query.addQueryItem("snapshotTransport", "inprocess")
        url.setQuery(query)
        self.webview.setUrl(url)

    def _handle_load_started(self) -> None:
        self.close_button.renderer_ready = False
        self.close_button.update()

    def _handle_load_finished(self, ok: bool) -> None:
        if ok:
            self.close_button.renderer_ready = True
            self.close_button.update()
            self.close_button.raise_()
            self._push_overlay_state()
            self._push_analysis_snapshot()
            self._push_combo_snapshot()
            self._push_buff_snapshot()
            self._push_snapshot('endfield-input-snapshot',self._input_snapshot)

    def apply_analysis_snapshot(self, message: dict[str, object]) -> None:
        if not {'analysis_snapshot', 'analysis_summary'}.intersection(template_for(self.entry).subscriptions):
            return
        message = table_snapshot(self.entry, message)
        self._analysis_snapshot = copy.deepcopy(message)
        self._push_analysis_snapshot()

    def apply_analysis_summary(self, message):
        if 'analysis_summary' not in template_for(self.entry).subscriptions:
            return
        self._analysis_snapshot = copy.deepcopy(message)
        self._push_analysis_snapshot()

    def _push_analysis_snapshot(self) -> None:
        self._push_snapshot("endfield-analysis-snapshot", self._analysis_snapshot)

    def apply_combo_snapshot(self, message: dict[str, object]) -> None:
        if "combo_snapshot" not in template_for(self.entry).subscriptions:
            return
        self._combo_snapshot = copy.deepcopy(message)
        self._push_combo_snapshot()

    def _push_combo_snapshot(self) -> None:
        self._push_snapshot("endfield-combo-snapshot", self._combo_snapshot)

    def apply_buff_snapshot(self, message: dict[str, object]) -> None:
        if "buff_snapshot" not in template_for(self.entry).subscriptions:
            return
        self._buff_snapshot = copy.deepcopy(message)
        self._push_buff_snapshot()

    def _push_buff_snapshot(self) -> None:
        self._push_snapshot("endfield-buff-snapshot", self._buff_snapshot)

    def apply_input_snapshot(self,message):
        if 'input_snapshot' not in template_for(self.entry).subscriptions:
            return
        self._input_snapshot = copy.deepcopy(message)
        self._push_snapshot('endfield-input-snapshot',self._input_snapshot)

    def _push_snapshot(self, event_name: str, message: dict[str, object] | None) -> None:
        if (
            not self.config.use_in_process_snapshots
            or not ({event_name.replace("endfield-", "").replace("-snapshot", "_snapshot")}
                    | ({'analysis_summary'} if event_name == 'endfield-analysis-snapshot' else set())).intersection(template_for(self.entry).subscriptions)
            or message is None
        ):
            return
        payload = json.dumps(message, ensure_ascii=True, allow_nan=False)
        self.webview.page().runJavaScript(
            "window.dispatchEvent(new CustomEvent('" + event_name + "', {detail: "
            + payload + "}));"
        )

    def _push_overlay_state(self) -> None:
        config = overlay_config(self.entry)
        defaults = template_for(self.entry).window
        config['referenceSize'] = dict(width=defaults.get('default_width', self.config.default_width),
                                       height=defaults.get('default_height', self.config.default_height))
        if self.entry.source_type == OverlaySourceType.BUILTIN and self.entry.source_value == 'combo_skill':
            from endfield_pcap.data.avatars import avatar_catalog
            config['characterAvatars'] = avatar_catalog()
            config['fitReset'] = self.content_size.reset_position
        if self.entry.source_type == OverlaySourceType.BUILTIN and self.entry.source_value == 'damage':
            from endfield_pcap.data.avatars import avatar_catalog
            config['characterAvatars'] = avatar_catalog()
            config['waitForSnapshot'] = self._analysis_snapshot is not None
            config['fitReset'] = self.content_size.reset_position
        config['closeHovered'] = self._close_hovered and not self.entry.click_through
        payload = json.dumps(
            config,
            ensure_ascii=False,
        )
        script = (
            "window.dispatchEvent(new CustomEvent("
            "'endfield-overlay-config', { detail: " + payload + " }));"
        )
        self.webview.page().runJavaScript(script)

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
        self.config.on_geometry_changed(self.entry.id, geometry_value)

    def _handle_mouse_press(self, local_pos: QPoint, global_pos: QPoint) -> None:
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
