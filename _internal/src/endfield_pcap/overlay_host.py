from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import queue
import socket
import sys
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable
from uuid import uuid4

os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-gpu-compositing --disable-software-rasterizer "
    "--disable-features=VizDisplayCompositor --no-sandbox",
)
os.environ.setdefault("QT_OPENGL", "software")
# A desktop-transparent overlay must keep producing fresh capture frames.
for _capture_flag in ('--disable-backgrounding-occluded-windows',
                      '--disable-renderer-backgrounding', '--disable-background-timer-throttling'):
    if _capture_flag not in os.environ['QTWEBENGINE_CHROMIUM_FLAGS'].split():
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] += ' ' + _capture_flag

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, QTimer, QUrl, QUrlQuery, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWebEngineCore import QWebEngineScript
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QWidget, QToolButton

from .models import OverlayEntry, OverlayGeometry, OverlaySourceType, ServiceObserver
from .overlay_templates import ASSETS, template_for, template_values
from .overlay_presentation import overlay_config, table_snapshot
from .runtime_paths import bundle_root
from .service import DamageLogService, ServiceConfig

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OverlayWindowConfig:
    entry: OverlayEntry
    ws_port: int
    min_width: int = 640
    min_height: int = 320
    default_width: int = 980
    default_height: int = 492
    margin_top: int = 56
    margin_right: int = 56
    resize_margin: int = 10
    on_geometry_changed: Callable[[str, OverlayGeometry], None] | None = None
    on_closed: Callable[[str], None] | None = None
    use_in_process_snapshots: bool = False
    desktop_visible: bool = True
    hide_on_close: bool = False


def _window_defaults(entry: OverlayEntry) -> dict[str, int]:
    template = template_for(entry)
    if template.window:
        return {"min_width": 100, "min_height": 40, "default_width": 700, "default_height": 350, **template.window}
    builtin_key = (entry.source_value or "damage").strip().lower()
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key == "uid_mask":
        return {
            "min_width": 100,
            "min_height": 20,
            "default_width": 100,
            "default_height": 20,
        }
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key in {"combo_skill", "buff"}:
        return {
            "min_width": 180,
            "min_height": 1,
            "default_width": 300,
            "default_height": 200,
        }
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key == "damage":
        return {
            "min_width": 320,
            "min_height": 160,
            "default_width": 800,
            "default_height": 380,
        }
    return {
        "min_width": 100,
        "min_height": 40,
        "default_width": 700,
        "default_height": 350,
    }


def _builtin_overlay_index(source_value: str) -> Path:
    package_asset_dir = Path(__file__).resolve().parent / "overlay_assets"
    repo_root = bundle_root()
    builtin_key = (source_value or "damage").strip().lower()
    if builtin_key == "damage":
        # This renderer consumes the versioned canonical snapshot contract.
        return package_asset_dir / "index.html"
    if builtin_key == "combo_skill":
        return package_asset_dir / "combo.html"
    builtin_paths = {
        "damage": repo_root / "overlay" / "dist" / "index.html",
        "combo_skill": repo_root / "overlay_comboskill" / "dist" / "index.html",
        "buff": repo_root / "overlay_buff" / "dist" / "index.html",
        "uid_mask": repo_root / "overlay_uid" / "dist" / "index.html",
    }
    target = builtin_paths.get(builtin_key)
    if target is not None and target.exists():
        return target
    return package_asset_dir / "index.html"


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

        script = QWebEngineScript()
        script.setName("endfield-host-bridge")
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setSourceCode((ASSETS / "host_bridge.js").read_text(encoding="utf-8"))
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
        if entry.geometry is not None or previous.geometry is not None:
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
        template = template_for(self.entry)
        if template.entry is not None:
            url = QUrl.fromLocalFile(str(template.entry))
        elif self.entry.source_type == OverlaySourceType.BUILTIN:
            url = QUrl.fromLocalFile(str(_builtin_overlay_index(self.entry.source_value).resolve()))
        elif self.entry.source_type == OverlaySourceType.FILE:
            url = QUrl.fromLocalFile(str(Path(self.entry.source_value).resolve()))
        else:
            url = QUrl.fromUserInput(self.entry.source_value)
        query = QUrlQuery(url)
        query.addQueryItem("wsPort", str(self.config.ws_port))
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


class OverlayManager:
    def __init__(
        self, ws_port: int, on_entry_changed: Callable[[OverlayEntry], None] | None = None,
        *, use_in_process_snapshots: bool = False, on_full_requirement=None,
        on_analysis_requirement=None, visible=True,
    ) -> None:
        self.ws_port = ws_port
        self.on_full_requirement = on_full_requirement
        self.on_analysis_requirement = on_analysis_requirement
        self.visible = bool(visible)
        self.on_entry_changed = on_entry_changed
        self._entries: dict[str, OverlayEntry] = {}
        self._windows: dict[str, OverlayWindow] = {}
        self._use_in_process_snapshots = use_in_process_snapshots
        self._analysis_snapshot: dict[str, object] | None = None
        self._combo_snapshot: dict[str, object] | None = None
        self._buff_snapshot: dict[str, object] | None = None
        self._live_snapshot: dict[str, object] | None = None
        self._history_mode = False
        self._presentation_stream = str(uuid4())
        self._presentation_sequence = 0
        self._retired_live_streams: set[str] = set()
        self._live_summary = None
        self._summary_presentation = None
        self._retired_summary_streams = set()

    def apply_analysis_summary(self, message, *, take_ownership=False):
        if not isinstance(message, dict) or message.get('type') != 'analysis_summary':
            return
        stream = message.get('stream_id')
        previous = self._live_summary
        if stream in self._retired_summary_streams:
            return
        if previous and stream == previous.get('stream_id') and message.get('sequence', -1) <= previous.get('sequence', -1):
            return
        if previous and stream != previous.get('stream_id'):
            self._retired_summary_streams.add(previous['stream_id'])
        self._live_summary = message if take_ownership else copy.deepcopy(message)
        if not self._history_mode:
            self._present_summary()

    def _present_summary(self):
        if self._live_summary is None:
            return
        self._presentation_sequence += 1
        self._summary_presentation = {**self._live_summary,
            'stream_id': self._presentation_stream, 'sequence': self._presentation_sequence,
            'source': {'mode': 'live'}}
        for window in self._windows.values():
            window.apply_analysis_summary(self._summary_presentation)

    def apply_analysis_snapshot(self, message: object, *, take_ownership: bool = False) -> None:
        """Accept canonical state on Qt's thread.

        The service has already isolated its observer payload. Its single-use
        queue can transfer that copy; public callers still receive isolation.
        """
        if not isinstance(message, dict) or message.get("type") != "analysis_snapshot":
            return
        previous = self._live_snapshot
        stream = message.get("stream_id")
        if stream in self._retired_live_streams:
            return
        if previous and stream == previous.get("stream_id") and message.get("sequence", -1) <= previous.get("sequence", -1):
            return
        if previous and stream != previous.get("stream_id"):
            self._retired_live_streams.add(previous["stream_id"])
        self._live_snapshot = message if take_ownership else copy.deepcopy(message)
        if not self._history_mode:
            self._present(self._live_snapshot.get("snapshot"), {"mode": "live"}, error=self._live_snapshot.get("error"), origin=self._live_snapshot)

    def _present(self, snapshot, source: dict, *, error=None, origin=None) -> None:
        self._presentation_sequence += 1
        self._analysis_snapshot = {"type": "analysis_snapshot", "schema_version": 1,
            "stream_id": self._presentation_stream, "sequence": self._presentation_sequence,
            "snapshot": snapshot, "source": source}
        if origin:
            self._analysis_snapshot.update({key: origin[key] for key in ('source_generation', 'source_revision') if key in origin})
        if error:
            self._analysis_snapshot["error"] = copy.deepcopy(error)
        for window in self._windows.values():
            if not self._history_mode and self._live_summary is not None and 'analysis_summary' in template_for(window.entry).subscriptions:
                continue
            window.apply_analysis_snapshot(self._analysis_snapshot)

    def show_history(self, snapshot: dict, label: str) -> None:
        self._history_mode = True
        self._present(copy.deepcopy(snapshot), {"mode": "history", "label": label})

    def return_live(self) -> None:
        self._history_mode = False
        message = self._live_snapshot or {}
        self._present(message.get("snapshot"), {"mode": "live"}, error=message.get("error"), origin=message)
        self._present_summary()

    def sync_entries(self, entries: list[OverlayEntry]) -> None:
        current_ids = {entry.id for entry in entries}
        for entry in entries:
            self.apply_entry(entry)
        for entry_id in list(self._entries):
            if entry_id not in current_ids:
                self.remove_entry(entry_id)

    def apply_combo_snapshot(self, message: object) -> None:
        if not isinstance(message, dict) or message.get("type") != "combo_snapshot":
            return
        self._combo_snapshot = copy.deepcopy(message)
        for window in self._windows.values():
            window.apply_combo_snapshot(self._combo_snapshot)

    def apply_buff_snapshot(self, message: object) -> None:
        if not isinstance(message, dict) or message.get("type") != "buff_snapshot":
            return
        self._buff_snapshot = copy.deepcopy(message)
        for window in self._windows.values():
            window.apply_buff_snapshot(self._buff_snapshot)

    def apply_entry(self, entry: OverlayEntry) -> None:
        if entry.source_value == 'combo_skill' or 'combo_snapshot' in template_for(entry).subscriptions:
            self.remove_entry(entry.id)
            return
        self._entries[entry.id] = replace(entry)
        self._notify_full_requirement()
        if entry.enabled:
            window = self._windows.get(entry.id)
            if window is None:
                window = OverlayWindow(
                    OverlayWindowConfig(
                        entry=replace(entry),
                        ws_port=self.ws_port,
                        **_window_defaults(entry),
                        on_geometry_changed=self._handle_geometry_changed,
                        on_closed=self._handle_window_closed,
                        use_in_process_snapshots=self._use_in_process_snapshots,
                        desktop_visible=self.visible and not entry.hidden,
                        hide_on_close=True,
                    )
                )
                self._windows[entry.id] = window
                if self._analysis_snapshot is not None:
                    window.apply_analysis_snapshot(self._analysis_snapshot)
                if not self._history_mode and self._summary_presentation is not None:
                    window.apply_analysis_summary(self._summary_presentation)
                if self._combo_snapshot is not None:
                    window.apply_combo_snapshot(self._combo_snapshot)
                if self._buff_snapshot is not None:
                    window.apply_buff_snapshot(self._buff_snapshot)
                window.show()
            else:
                window.apply_entry(replace(entry))
                window.set_desktop_visible(self.visible and not entry.hidden)
                window.show()

        else:
            self._close_window(entry.id)

    def remove_entry(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)
        self._notify_full_requirement()
        self._close_window(entry_id)

    def _notify_full_requirement(self):
        subscriptions = {key for row in self._entries.values() if row.enabled
                         for key in template_for(row).subscriptions}
        if self.on_analysis_requirement is not None:
            self.on_analysis_requirement(frozenset(subscriptions))
        if self.on_full_requirement is not None:
            self.on_full_requirement('analysis_snapshot' in subscriptions)

    def set_visible(self, visible):
        self.visible = bool(visible)
        for entry in self._entries.values():
            window = self._windows.get(entry.id)
            if window is not None:
                window.set_desktop_visible(self.visible and not entry.hidden)

    def close_all(self) -> None:
        for entry_id in list(self._windows):
            self._close_window(entry_id)

    def opened_window_count(self) -> int:
        return len(self._windows)

    def visible_window_count(self) -> int:
        return sum(window.desktop_visible for window in self._windows.values())

    def _close_window(self, entry_id: str) -> None:
        window = self._windows.pop(entry_id, None)
        if window is None:
            return
        window.config.on_closed = None
        window.close()

    def _handle_geometry_changed(self, entry_id: str, geometry: OverlayGeometry) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        updated = replace(entry, geometry=geometry)
        self._entries[entry_id] = updated
        if self.on_entry_changed is not None:
            self.on_entry_changed(replace(updated))

    def _handle_window_closed(self, entry_id: str) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        updated = replace(entry, hidden=True)
        self.apply_entry(updated)
        if self.on_entry_changed is not None:
            self.on_entry_changed(replace(updated))


def run_with_overlay(service_config: ServiceConfig) -> int:
    service: DamageLogService | None = None
    service_thread: threading.Thread | None = None
    service_error: list[BaseException] = []
    snapshots: queue.Queue[dict[str, object]] = queue.Queue()

    def port_is_available(port: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def service_main() -> None:
        try:
            assert service is not None
            asyncio.run(service.run())
        except BaseException as exc:  # noqa: BLE001
            LOGGER.error("service thread failed", exc_info=(type(exc), exc, exc.__traceback__))
            service_error.append(exc)

    attach_only = not port_is_available(service_config.ws_port)
    if attach_only:
        LOGGER.warning(
            "ws port %d is already in use; the overlay will attach to the existing service instead of starting a new one",
            service_config.ws_port,
        )
    else:
        service = DamageLogService(
            service_config, observer=ServiceObserver(on_analysis_summary=snapshots.put, on_buff_snapshot=snapshots.put),
        )
        service_thread = threading.Thread(target=service_main, name="damage-service", daemon=True)
        service_thread.start()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    manager = OverlayManager(service_config.ws_port, use_in_process_snapshots=not attach_only)
    manager.sync_entries(
        [
            OverlayEntry(
                id="builtin-overlay",
                name="伤害统计",
                source_type=OverlaySourceType.BUILTIN,
                source_value="damage",
                enabled=True,
                locked=False,
                click_through=False,
                opacity=1.0,
            )
        ]
    )

    def poll_state() -> None:
        while True:
            try:
                message = snapshots.get_nowait()
                if message.get("type") == "buff_snapshot":
                    manager.apply_buff_snapshot(message)
                elif message.get("type") == "analysis_summary":
                    manager.apply_analysis_summary(message)
                else:
                    manager.apply_analysis_snapshot(message)
            except queue.Empty:
                break
        if service_error:
            LOGGER.error("overlay is closing because the service thread exited with an error")
            app.quit()
            return
        if service_thread is not None and not service_thread.is_alive():
            app.quit()

    app.aboutToQuit.connect(manager.close_all)
    if service is not None:
        app.aboutToQuit.connect(service.request_stop)

    poll_timer = QTimer()
    poll_timer.setInterval(33)
    poll_timer.timeout.connect(poll_state)
    poll_timer.start()

    exit_code = app.exec()

    if service is not None:
        service.request_stop()
    if service_thread is not None:
        service_thread.join(timeout=5)
    if service_error:
        raise service_error[0]
    return exit_code

