"""Check actual glyph bounds and composed close marks, not just cell widths."""
from dataclasses import replace

import pytest
from PySide6.QtCore import QPointF, QEvent
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest

from endfield_pcap import overlay_host
from endfield_pcap.models import OverlayGeometry
from endfield_pcap.overlay_templates import with_template_value
from test_overlay_controls import entry
from test_qt_snapshot_bridge import EVIDENCE, snapshot_message, wait_for_page, page_value


def large_frame():
    frame = snapshot_message()
    frame['snapshot']['battle'].update(total_damage=1290356720, total_dps=1234567.8, duration_ms=104000)
    frame['snapshot']['participants'] = [dict(character_name=name, total_damage=damage, total_rd=damage,
        crit_rate=.375) for name, damage in [('管理员·重装型', 823456789), ('庄方宜', 323456789), ('骏卫', 100000000), ('佩丽卡', 43443142)]]
    return frame


@pytest.mark.parametrize('theme', ['light', 'dark', 'transparent'])
def test_default_damage_size_shows_full_glyphs_and_four_rows_with_large_metrics(app, theme):
    current = with_template_value(entry(enabled=True), 'theme', theme)
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    try:
        manager.apply_analysis_snapshot(large_frame())
        manager.apply_entry(current)
        window = manager._windows[current.id]
        wait_for_page(window, lambda: None)
        assert (window.width(), window.height()) == (800, 380)
        for width, height in ((800, 380), (600, 400)):
            manager.apply_entry(replace(current, geometry=OverlayGeometry(100, 100, width, height)))
            QTest.qWait(150)
            result = page_value(window, """(() => {
                const bounds = el => { const r = el.getBoundingClientRect(); return {left:r.left, right:r.right, top:r.top, bottom:r.bottom}; };
                const selectors = '#totalDamage, #totalDps, #combatTime, .table-label, .row-stat';
                return {width:innerWidth, height:innerHeight,
                    cells:[...document.querySelectorAll(selectors)].map(el => {
                        const range = document.createRange(); range.selectNodeContents(el);
                        return {text:el.textContent, cell:bounds(el), textBounds:bounds(range)};
                    }),
                    rows:[...document.querySelectorAll('.row')].map(bounds),
                    body:bounds(document.querySelector('.table-body'))};
            })()""")
            assert len(result['rows']) == 4
            assert result['rows'][-1]['bottom'] <= result['body']['bottom']
            for cell in result['cells']:
                text, box = cell['textBounds'], cell['cell']
                assert text['right'] <= min(box['right'], width) + 1, cell
                assert text['left'] >= max(box['left'], 0) - 1, cell
                assert text['top'] >= 0 and text['bottom'] <= height, cell
            assert window.grab().save(str(EVIDENCE / f'damage-default-{theme}-{width}.png'))
    finally:
        manager.close_all(); app.processEvents()


@pytest.mark.parametrize('source', ['damage', 'combo_skill', 'buff', 'uid_mask'])
@pytest.mark.parametrize('theme', ['light', 'dark', 'transparent'])
def test_close_is_legible_without_hover_and_clear_on_hover_in_composed_window(app, source, theme):
    current = with_template_value(entry(enabled=True, source_value=source), 'theme', theme)
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(entry=current, ws_port=1,
        use_in_process_snapshots=True, **overlay_host._window_defaults(current)))
    try:
        if source == 'damage': window.apply_analysis_snapshot(large_frame())
        wait_for_page(window, window.show)
        if source != 'uid_mask':
            assert page_value(window, 'document.documentElement.dataset.theme') == theme
        if source == 'damage':
            assert page_value(window, 'document.querySelectorAll(".row").length') == 4
        button = window.close_button
        assert button.isVisible()
        assert window.childAt(button.geometry().center()) is button
        if source in {'buff', 'combo_skill'}:
            status = page_value(window, 'document.querySelector("#buffStatus, #comboStatus").getBoundingClientRect().right')
            assert status < button.x()
        # Inspect the Chromium framebuffer independently of the native sibling.
        # QWidget.grab used to pass even when Windows composited it underneath
        # WebEngine, which is precisely the user's reported failure.
        assert page_value(window, 'document.querySelector("#endfield-host-close").shadowRoot.querySelector(".mark") !== null')
        page_value(window, '(() => { document.querySelector("#endfield-host-close").style.setProperty("visibility", "hidden", "important"); return true; })()')
        QTest.qWait(250)  # Chromium presents asynchronously after JS completes.
        absent = window.webview.grab()
        page_value(window, '(() => { document.querySelector("#endfield-host-close").style.removeProperty("visibility"); return true; })()')
        app.sendEvent(button, QEvent(QEvent.Type.Leave))
        QTest.qWait(250)
        normal = window.webview.grab()
        assert normal.save(str(EVIDENCE / f'close-{source}-{theme}-normal.png'))
        # Grab the whole composed widget, then inspect the icon's actual region.
        ratio = normal.devicePixelRatio()
        region = normal.copy(int(button.x()*ratio), int(button.y()*ratio), int(button.width()*ratio), int(button.height()*ratio)).toImage()
        base = absent.copy(int(button.x()*ratio), int(button.y()*ratio), int(button.width()*ratio), int(button.height()*ratio)).toImage()
        changed = sum(region.pixelColor(x,y).rgba() != base.pixelColor(x,y).rgba()
                      for x in range(region.width()) for y in range(region.height()))
        assert changed >= 24, (source, theme, changed)
        bright = sum(region.pixelColor(x,y).alpha() > 100 and min(region.pixelColor(x,y).getRgb()[:3]) > 150
                     for x in range(region.width()) for y in range(region.height()))
        assert bright >= 12, (source, theme, bright)
        app.sendEvent(button, QEnterEvent(QPointF(13,13), QPointF(13,13), button.mapToGlobal(button.rect().center())))
        QTest.qWait(80)
        hovered = window.webview.grab()
        assert hovered.save(str(EVIDENCE / f'close-{source}-{theme}-hover.png'))
        region = hovered.copy(int(button.x()*ratio), int(button.y()*ratio), int(button.width()*ratio), int(button.height()*ratio)).toImage()
        red = sum((c := region.pixelColor(x,y)).red() > 150 and c.red() > 2*c.green() and c.alpha() > 200
                  for x in range(region.width()) for y in range(region.height()))
        assert red > 100, (source, theme, red)
    finally:
        window.close(); app.processEvents()


@pytest.mark.parametrize('locked', [False, True])
def test_host_close_hit_target_works_if_native_button_is_occluded(app, locked):
    from PySide6.QtCore import Qt
    current = entry(enabled=True, locked=locked)
    closed = []
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(entry=current,
        ws_port=1, on_closed=closed.append, use_in_process_snapshots=True))
    try:
        wait_for_page(window, window.show)
        center = window.close_button.geometry().center()
        window.close_button.hide()  # Simulate Windows covering the sibling.
        # Deliver to the host directly: moving the OS cursor is unreliable
        # while a full-screen game owns/captures it, and is unnecessary here.
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=center)
        assert closed == [current.id]
    finally:
        if not closed: window.close()
        app.processEvents()


def test_close_mark_respects_clickthrough_resize_and_reload(app):
    current = entry(source_value='uid_mask', enabled=True)
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(entry=current,
        ws_port=1, **overlay_host._window_defaults(current)))
    try:
        wait_for_page(window, window.show)
        window.resize(240, 30)
        QTest.qWait(100)
        bounds = page_value(window, '(() => {const r=document.querySelector("#endfield-host-close").getBoundingClientRect();return [r.x,r.y,r.width,r.height]})()')
        # At fractional Windows DPI, Chromium's viewport can differ by one
        # physical pixel from the integer-DIP native hit target.
        assert bounds == pytest.approx([206, 4, 26, 26], abs=1)
        window.apply_entry(replace(current, click_through=True))
        assert page_value(window, 'getComputedStyle(document.querySelector("#endfield-host-close")).display') == 'none'
        window.apply_entry(current)
        wait_for_page(window, window.webview.reload)
        assert page_value(window, 'getComputedStyle(document.querySelector("#endfield-host-close")).display') == 'block'
    finally:
        window.close(); app.processEvents()
