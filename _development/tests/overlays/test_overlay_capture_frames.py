"""Opt-in WGC pixel verification; uses only synthetic windows and data.

Requires a native Windows test session and ENDFIELD_WGC_TEST_DLL pointing to
the local verification capture helper. No OBS sources/settings are modified.
"""
import concurrent.futures
import ctypes
from ctypes import wintypes
from dataclasses import replace
import os
from pathlib import Path
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
import endfield_pcap.overlays.manager as overlay_host
from endfield_pcap.models import OverlayGeometry
from app_test_support.ui.window import entry
from app_test_support.ui.qt import EVIDENCE, page_value, wait_for_page


def test_wgc_receives_fresh_frames_while_desktop_overlay_is_invisible(app):
    helper = os.environ.get('ENDFIELD_WGC_TEST_DLL')
    if app.platformName() != 'windows' or not helper:
        pytest.skip('opt-in native WGC test: ENDFIELD_WGC_TEST_DLL and Windows desktop required')
    library = ctypes.CDLL(str(Path(helper).resolve()))
    library.capture_test_window.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    library.capture_test_window.restype = ctypes.c_int
    pool = concurrent.futures.ThreadPoolExecutor(1)
    back = QWidget(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
    back.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    back.setGeometry(100, 100, 800, 380)
    back.setStyleSheet('background:rgb(10,10,240)')
    back.show()
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    current = entry(enabled=True, geometry=OverlayGeometry(100, 100, 800, 380))
    manager.apply_entry(current)
    native = manager._windows[current.id]

    def capture(label):
        path = EVIDENCE / f'wgc-hidden-{label}.bmp'
        result = pool.submit(library.capture_test_window, int(native.winId()), str(path))
        while not result.done():
            QTest.qWait(20)
        assert result.result() == 0
        image = QImage(str(path))
        assert not image.isNull()
        ratio = image.width() / native.width()
        return image.pixelColor(round(20*ratio), round(180*ratio)).getRgb()[:3]

    def color(value):
        page_value(native, f'document.querySelector("#wgc-probe").style.background="rgb({value})"')
        QTest.qWait(300)

    try:
        wait_for_page(native, lambda: None)
        page_value(native, '''(() => {const probe=document.createElement('div');probe.id='wgc-probe';
            probe.style.cssText='position:fixed;left:8px;top:150px;width:80px;height:80px;z-index:2147483647;background:rgb(240,10,10)';
            document.body.appendChild(probe);return true;})()''')
        QTest.qWait(300)
        # The damage page measures its content after loading. Visibility
        # edits must reuse that saved geometry, as the GUI does.
        current = manager._entries[current.id]
        hwnd, geometry = int(native.winId()), native.geometry()
        assert capture('visible-red') == (240, 10, 10)
        manager.apply_entry(replace(current, hidden=True))
        assert native.isVisible() and native.windowOpacity() == 0
        assert int(native.winId()) == hwnd and native.geometry() == geometry
        color('10,240,10')
        assert capture('invisible-green') == (10, 240, 10)
        desktop = app.primaryScreen().grabWindow(0, 100, 100, 800, 380)
        desktop.save(str(EVIDENCE / 'wgc-hidden-desktop.png'))
        image, ratio = desktop.toImage(), desktop.devicePixelRatio()
        assert image.pixelColor(round(20*ratio), round(180*ratio)).getRgb()[:3] == (10, 10, 240)
        color('240,10,240')
        assert capture('invisible-purple') == (240, 10, 240)
        manager.apply_entry(current)
        QTest.qWait(200)
        assert native.desktop_visible and int(native.winId()) == hwnd and native.geometry() == geometry
        assert capture('restored-purple') == (240, 10, 240)
    finally:
        manager.close_all()
        back.close()
        pool.shutdown()
        app.processEvents()
