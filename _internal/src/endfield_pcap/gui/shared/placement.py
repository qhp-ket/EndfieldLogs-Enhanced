"""Initial top-level placement in Qt logical coordinates, including the frame."""
from PySide6.QtCore import QRect, QSize, QTimer
from PySide6.QtGui import QCursor, QGuiApplication


def centered_frame(available: QRect, requested: QSize, margin: int = 12) -> QRect:
    """Works with negative monitor origins and very small work areas."""
    inset = min(margin, max(0, (min(available.width(), available.height()) - 1) // 2))
    bounds = available.adjusted(inset, inset, -inset, -inset)
    size = QSize(max(1, min(requested.width(), bounds.width())),
                 max(1, min(requested.height(), bounds.height())))
    result = QRect(bounds.topLeft(), size)
    result.moveCenter(bounds.center())
    return result


def place_initial_window(window, parent=None, *, screen=None):
    """Call once after show/layout. Never recenter a user's subsequent moves."""
    screen = screen or (parent.screen() if parent is not None else
                        QGuiApplication.screenAt(QCursor.pos())) or QGuiApplication.primaryScreen()
    if screen is None or window.isMaximized() or window.isFullScreen():
        return
    available = screen.availableGeometry()
    frame = window.frameGeometry()
    extra = frame.size() - window.size()
    target = centered_frame(available, frame.size())
    client = target.size() - extra
    # Explicit minima must not make a window taller/wider than this monitor.
    window.setMinimumSize(min(window.minimumWidth(), max(1, client.width())),
                          min(window.minimumHeight(), max(1, client.height())))
    window.resize(max(1, client.width()), max(1, client.height()))
    # Native frame margins can change on the first cross-monitor/DPI move.
    target = centered_frame(available, window.frameGeometry().size())
    window.move(target.topLeft() + window.pos() - window.frameGeometry().topLeft())


def schedule_initial_placement(window, parent=None):
    if getattr(window, '_initial_placement_scheduled', False):
        return
    window._initial_placement_scheduled = True
    screen = (parent.screen() if parent is not None else QGuiApplication.screenAt(QCursor.pos())) or QGuiApplication.primaryScreen()
    # The context-bound timer is cancelled if the window is destroyed.
    QTimer.singleShot(0, window, lambda: place_initial_window(window, parent, screen=screen))
    QTimer.singleShot(80, window, lambda: place_initial_window(window, parent, screen=screen))
