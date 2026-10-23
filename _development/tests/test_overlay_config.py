from dataclasses import replace
import json

from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFormLayout
from endfield_pcap.gui_widgets import IntegerStepEdit

from endfield_pcap import gui_main, overlay_host
from endfield_pcap.models import OverlayGeometry
from endfield_pcap.overlay_templates import template_for, template_values, with_template_value
from test_overlay_controls import entry, main_window
from test_qt_snapshot_bridge import EVIDENCE, page_value, wait_for_page, snapshot_message


def buff_message(sequence=1, count=17):
    rows = [dict(uid=str(9007199254740993 + i), buff_id=f"buff_fixture_{i + 1}", owner="chr_fixture",
                 source="chr_source", enabled=True, duration_ms=10000, remaining_ms=8100,
                 duration_source="trace_duration", status="timed") for i in range(count)]
    rows += [dict(uid="unknown", buff_id="buff_duration_unknown", owner="chr_fixture", source="chr_source",
                 enabled=None, duration_ms=None, remaining_ms=None, duration_source="unknown", status="unknown")]
    return dict(type="buff_snapshot", schema_version=1, stream_id="buff-test", sequence=sequence, snapshot=dict(buffs=rows))


def test_one_form_alignment_and_font_slider_for_every_builtin(main_window, app):
    window = main_window
    window.resize(1200, 1040)
    page = window.overlay_page
    builtins = {"damage": "伤害统计", "buff": "BUFF", "uid_mask": "UID 遮挡"}
    window.app_config.overlays = [entry(id=key, name=name, source_value=key) for key, name in builtins.items()]
    window._refresh_overlay_views()
    window.switchTo(page)
    for index, builtin in enumerate(builtins):
        page.overlay_list.setCurrentRow(index)
        current = window._selected_overlay()
        QTest.qWait(150)
        form = page.details_form
        labels, fields = [], []
        for row in range(form.rowCount()):
            if form.itemAt(row, QFormLayout.ItemRole.LabelRole) is None:
                continue
            labels.append(form.itemAt(row, QFormLayout.ItemRole.LabelRole).widget().x())
            fields.append(form.itemAt(row, QFormLayout.ItemRole.FieldRole).widget().x())
        assert len(set(labels)) == len(set(fields)) == 1, (builtin, labels, fields)
        assert form.rowCount() == 11 + len(template_for(current).settings)
        assert isinstance(page.font_size_edit, IntegerStepEdit)
        assert window.grab().save(str(EVIDENCE / f"gui-config-{builtin}.png"))
    # Integer input persists font size while geometry remains fixed.
    page.show_entry(window._selected_overlay())
    before = window._selected_overlay().geometry
    page.font_size_edit.setValue(175)
    assert window._selected_overlay().font_scale == 1.75
    assert window._selected_overlay().geometry == before
    assert page.font_size_value.text() == "%"


def test_buff_templates_replacement_filters_scroll_and_reopen(app):
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    current = entry(source_value="buff", enabled=True, geometry=OverlayGeometry(100, 100, 380, 360))
    try:
        manager.apply_buff_snapshot(buff_message())
        manager.apply_entry(current)
        window = manager._windows[current.id]
        wait_for_page(window, lambda: None)
        assert page_value(window, "document.querySelectorAll('.buff-row').length") == 18
        manager.apply_buff_snapshot(buff_message())
        assert page_value(window, "document.querySelectorAll('.buff-row').length") == 18
        assert "8.1s*" in page_value(window, "document.body.textContent")
        assert "时长未知" in page_value(window, "document.body.textContent")
        assert page_value(window, "document.querySelector('#buffRows').scrollHeight > document.querySelector('#buffRows').clientHeight")
        app.sendEvent(window, QWheelEvent(QPointF(30, 100), QPointF(130, 200), QPoint(), QPoint(0, -120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False))
        assert page_value(window, "document.querySelector('#buffRows').scrollTop") > 0
        page_value(window, "document.querySelector('#buffRows').scrollTop = 0")
        for theme in ("light", "dark", "transparent"):
            updated = with_template_value(current, "theme", theme)
            manager.apply_entry(updated)
            QTest.qWait(100)
            assert window.grab().save(str(EVIDENCE / f"buff-{theme}.png"))
        updated = with_template_value(current, "durations", "timed")
        manager.apply_entry(updated)
        assert page_value(window, "document.querySelectorAll('.buff-row').length") == 17
        manager.apply_entry(replace(current, enabled=False))
        manager.apply_entry(current)
        window = manager._windows[current.id]
        wait_for_page(window, lambda: None)
        assert page_value(window, "document.querySelectorAll('.buff-row').length") == 18
        clear = buff_message(2, 0)
        clear["snapshot"]["buffs"] = []
        manager.apply_buff_snapshot(clear)
        assert page_value(window, "document.querySelectorAll('.buff-row').length") == 0
        wait_for_page(window, window.webview.reload)
        assert page_value(window, "document.querySelectorAll('.buff-row').length") == 0
    finally:
        manager.close_all(); app.processEvents()


def test_uid_mask_defaults_black_cover_and_close_hover(app):
    current = entry(source_value="uid_mask", enabled=True)
    defaults = overlay_host._window_defaults(current)
    closed = []
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=current, ws_port=1, on_closed=closed.append, **defaults))
    try:
        wait_for_page(window, window.show)
        assert (window.width(), window.height()) == (220, 32)
        screen = window.screen().geometry()
        assert window.x() == screen.x() + 12 and window.y() > screen.center().y()
        assert page_value(window, "getComputedStyle(document.querySelector('#mask')).backgroundColor") == "rgb(0, 0, 0)"
        assert abs(page_value(window, "document.querySelector('#mask').getBoundingClientRect().width") - window.width()) < .1
        assert not template_for(current).subscriptions
        button = window.close_button
        assert button.x() == window.width() - button.width() - 8
        app.sendEvent(button, QEvent(QEvent.Type.Leave))
        QTest.qWait(50)
        normal = window.webview.grab().toImage()
        assert window.grab().save(str(EVIDENCE / "uid-mask.png"))
        # Exercise the real hover event path; pixel output must highlight.
        QTest.mouseMove(button, QPoint(11, 11))
        QTest.qWait(100)
        if not button._hovered:  # offscreen platform does not dispatch Enter
            from PySide6.QtGui import QEnterEvent
            app.sendEvent(button, QEnterEvent(QPoint(11, 11), QPoint(11, 11), button.mapToGlobal(QPoint(11, 11))))
        QTest.qWait(80)
        assert button._hovered and window.webview.grab().toImage() != normal
        assert window.grab().save(str(EVIDENCE / "uid-close-hover.png"))
        window.apply_entry(with_template_value(current, "shape", "rounded"))
        assert page_value(window, "getComputedStyle(document.querySelector('#mask')).borderRadius") == "6px"
        button.click()
        assert closed == [current.id]
    finally:
        if not closed: window.close()
        app.processEvents()


def test_damage_close_mark_normal_and_hover_in_all_themes(app):
    current = entry(enabled=True, geometry=OverlayGeometry(100, 100, 700, 350))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(entry=current, ws_port=1, use_in_process_snapshots=True))
    try:
        window.apply_analysis_snapshot(snapshot_message())
        wait_for_page(window, window.show)
        for theme in ("light", "dark", "transparent"):
            window.apply_entry(with_template_value(current, "theme", theme))
            app.sendEvent(window.close_button, QEvent(QEvent.Type.Leave))
            QTest.qWait(100)
            assert window.grab().save(str(EVIDENCE / f"close-{theme}.png"))
    finally:
        window.close(); app.processEvents()
