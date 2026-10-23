"""Dragging must not persist transient Windows DPI resize events."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from endfield_pcap import overlay_host
from endfield_pcap.models import OverlayGeometry
from test_overlay_controls import entry


def test_move_preserves_starting_size_after_transient_resize_and_release(app):
    changes = []
    current = entry(enabled=True, hidden=True, geometry=OverlayGeometry(100, 100, 800, 380))
    manager = overlay_host.OverlayManager(
        1, on_entry_changed=changes.append, use_in_process_snapshots=True)
    try:
        manager.apply_entry(current)
        window = manager._windows[current.id]
        app.processEvents()
        changes.clear()
        local = QPoint(80, 80)
        origin = window.mapToGlobal(local)
        window._handle_mouse_press(local, origin)
        # A mixed-DPI transition may resize the native window before Qt has
        # finished switching screens. These intermediate sizes are not edits.
        window.resize(914, 434)
        window._handle_mouse_move(local, origin + QPoint(30, 20), Qt.MouseButton.LeftButton)
        app.processEvents()
        assert (window.width(), window.height()) == (800, 380)
        window.resize(700, 333)
        app.processEvents()
        assert (window.width(), window.height()) == (800, 380)
        window.resize(914, 434)
        window._handle_mouse_release(local)
        app.processEvents()
        assert (window.width(), window.height()) == (800, 380)
        assert changes and {(e.geometry.width, e.geometry.height) for e in changes} == {(800, 380)}
        assert manager._entries[current.id].geometry.width == 800
        # A real edge resize after release must still work; no pending repair
        # may restore the old move size over this deliberate edit.
        corner = QPoint(window.width()-1, window.height()-1)
        origin = window.mapToGlobal(corner)
        window._handle_mouse_press(corner, origin)
        window._handle_mouse_move(corner, origin + QPoint(60, 40), Qt.MouseButton.LeftButton)
        window._handle_mouse_release(corner)
        app.processEvents()
        assert (window.width(), window.height()) == (860, 420)
        assert manager._entries[current.id].geometry.width == 860
    finally:
        manager.close_all()
        app.processEvents()


def test_native_cross_screen_roundtrips_preserve_size_and_saved_geometry(app):
    if app.platformName() != 'windows':
        pytest.skip('native Windows mixed-DPI desktop required')
    primary = app.primaryScreen()
    others = [s for s in app.screens() if s != primary
              and abs(s.devicePixelRatio()-primary.devicePixelRatio()) > .01]
    if not others:
        pytest.skip('two monitors with different DPI required')
    # Snapshot the rectangles: Windows can replace QScreen objects while the
    # desktop topology changes. Never keep a deleted native object in a loop.
    destinations = [others[0].geometry(), primary.geometry()]
    changes = []
    current = entry(enabled=True, hidden=True, geometry=OverlayGeometry(
        primary.geometry().x()+100, primary.geometry().y()+100, 800, 380))
    manager = overlay_host.OverlayManager(
        1, on_entry_changed=changes.append, use_in_process_snapshots=True)
    try:
        manager.apply_entry(current)
        window = manager._windows[current.id]
        QTest.qWait(100)
        hwnd = int(window.winId())
        changes.clear()
        ratios = {window.devicePixelRatioF()}
        for _ in range(3):
            for bounds in destinations:
                local = QPoint(80, 80)
                origin = window.mapToGlobal(local)
                end = bounds.topLeft()+QPoint(70, 120)
                window._handle_mouse_press(local, origin)
                for step in range(1, 31):
                    position = origin+(end-origin)*step/30
                    window._handle_mouse_move(local, position, Qt.MouseButton.LeftButton)
                    QTest.qWait(10)
                    ratios.add(window.devicePixelRatioF())
                window._handle_mouse_release(local)
                QTest.qWait(100)
                assert (window.width(), window.height()) == (800, 380)
                assert int(window.winId()) == hwnd
                saved = manager._entries[current.id]
                assert (saved.geometry.width, saved.geometry.height) == (800, 380)
                manager.apply_entry(saved)
                QTest.qWait(30)
                assert (window.width(), window.height()) == (800, 380)
        assert len(ratios) >= 2, 'test must cross a real DPI boundary'
        assert changes and {(e.geometry.width, e.geometry.height) for e in changes} == {(800, 380)}
        assert window.webview.zoomFactor() == 1
    finally:
        manager.close_all()
        app.processEvents()
