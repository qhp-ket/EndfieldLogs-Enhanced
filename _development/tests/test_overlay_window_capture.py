"""Capture eligibility must survive click-through and presentation edits."""
import ctypes
from ctypes import wintypes
from dataclasses import replace
import sys

import pytest
from PySide6.QtCore import QPoint, Qt

from endfield_pcap import overlay_host
from endfield_pcap.models import OverlayGeometry
from test_overlay_controls import entry


def test_overlay_is_normal_nonactivating_window_after_clickthrough_changes(app):
    current = entry(enabled=True, geometry=OverlayGeometry(100, 100, 600, 300))
    closed = []
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=current, ws_port=1, on_closed=closed.append,
        use_in_process_snapshots=True, **overlay_host._window_defaults(current)))
    try:
        window.show()
        for click_through in (False, True, False):
            window.apply_entry(replace(current, click_through=click_through))
            assert window.windowType() == Qt.WindowType.Window
            assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            assert bool(window.windowFlags() & Qt.WindowType.WindowTransparentForInput) == click_through
            assert window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            assert window.isVisible()
            assert (window.width(), window.height()) == (600, 300)
        # Exercise drag and resize after native window flags have changed twice.
        local = QPoint(80, 80)
        origin = window.mapToGlobal(local)
        initial = window.pos()
        window._handle_mouse_press(local, origin)
        window._handle_mouse_move(local, origin + QPoint(40, 30), Qt.MouseButton.LeftButton)
        window._handle_mouse_release(local)
        assert window.pos() == initial + QPoint(40, 30)
        local = QPoint(window.width()-1, window.height()-1)
        origin = window.mapToGlobal(local)
        window._handle_mouse_press(local, origin)
        window._handle_mouse_move(local, origin + QPoint(40, 20), Qt.MouseButton.LeftButton)
        window._handle_mouse_release(local)
        assert (window.width(), window.height()) == (640, 320)
        window.close_button.click()
        assert closed == [current.id]
    finally:
        if not closed:
            window.close()
        app.processEvents()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows capture enumeration')
def test_native_overlay_passes_obs_window_enumeration_filters(app):
    if app.platformName() != 'windows':
        pytest.skip('run with ENDFIELD_UI_TEST_PLATFORM=windows for native HWND checks')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.GetForegroundWindow.restype = wintypes.HWND
    dwm = ctypes.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    current = entry(enabled=True, name='Endfield Overlay Capture Test', geometry=OverlayGeometry(100, 100, 600, 300))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=current, ws_port=1, use_in_process_snapshots=True, **overlay_host._window_defaults(current)))
    try:
        before_show = user32.GetForegroundWindow()
        window.show()
        app.processEvents()
        # Test only our HWND: do not change another application's focus or settings.
        assert user32.GetForegroundWindow() != int(window.winId()) or before_show == int(window.winId())
        for click_through in (False, True, False):
            window.apply_entry(replace(current, click_through=click_through))
            app.processEvents()
            hwnd = int(window.winId())
            enumerated = []
            callback = callback_type(lambda handle, _: enumerated.append(handle) or True)
            assert user32.EnumWindows(callback, 0)
            assert hwnd in enumerated
            assert user32.IsWindowVisible(hwnd)
            styles = user32.GetWindowLongPtrW(hwnd, -16)
            extended = user32.GetWindowLongPtrW(hwnd, -20)
            assert not extended & 0x00000080, 'WS_EX_TOOLWINDOW is excluded by OBS'
            assert not styles & 0x40000000, 'WS_CHILD is excluded by OBS'
            rect = wintypes.RECT()
            assert user32.GetClientRect(hwnd, ctypes.byref(rect))
            assert rect.right > 0 and rect.bottom > 0
            cloaked = wintypes.DWORD()
            assert dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
            assert cloaked.value == 0
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            assert title.value == current.name
            assert bool(extended & 0x00000020) == click_through  # WS_EX_TRANSPARENT
    finally:
        window.close()
        app.processEvents()
