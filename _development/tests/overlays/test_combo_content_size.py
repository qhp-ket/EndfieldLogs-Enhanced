"""Actual WebEngine layout, native window fit and GUI style selection."""
from dataclasses import replace
import json
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from app_test_support.ui.window import main_window
from app_test_support.ui.qt import page_value, wait_for_page, EVIDENCE
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.models import OverlayEntry, OverlaySourceType
from endfield_pcap.overlays.window import OverlayWindow,OverlayWindowConfig
from endfield_pcap.overlays.config import _window_defaults
from endfield_pcap.overlays.templates import with_template_value
from endfield_pcap.gui.config import load_app_config


def fitted(window):
    reference=page_value(window,'window.endfieldOverlay?.contentReference || null')
    if not reference:return False
    if (reference['style'] != window.entry.template_settings.get('display_style','circles')
            or reference['font'] != window.entry.font_scale
            or reference['avatar'] != window.entry.template_settings.get('avatar_size_percent',100)):
        return False
    scale=window.content_size.scale
    if scale is None or window.content_size.reference != (reference['width'],reference['height']):return False
    data=dimensions(window)
    target_width = window.content_size.bar_width if reference['style']=='bars' and window.content_size.bar_width else max(window.minimumWidth(),reference['width']*scale)
    return (data['width']==window.width() and data['height']==window.height()
        and abs(window.width()-target_width)<2
        and abs(window.height()-max(window.minimumHeight(),reference['height']*scale))<2
        and abs(data['bottom']-data['height'])<2)


def dimensions(window):
    return page_value(window,"""(() => {
      const shell=document.querySelector('.combo-overlay-shell').getBoundingClientRect();
      const rows=document.getElementById('comboRows').getBoundingClientRect();
      return {style:document.body.dataset.style, width:innerWidth,height:innerHeight,
        bottom:shell.bottom,rowsBottom:rows.bottom,reference:window.endfieldOverlay.contentReference,
        font:parseFloat(getComputedStyle(document.documentElement).fontSize),
        avatar:document.querySelector('.portrait').getBoundingClientRect().width,
        cellsFit:[...document.querySelectorAll('.name,.value')].every(n=>n.scrollWidth<=n.clientWidth+1)};
    })()""")


@pytest.mark.parametrize('theme',['light','dark','transparent'])
def test_combo_style_roundtrip_changes_both_dimensions_without_blank_space(app,theme):
    entry=OverlayEntry('combo-fit','连携',OverlaySourceType.BUILTIN,'combo_skill',True,False,False,overlay_theme=theme)
    window=OverlayWindow(OverlayWindowConfig(entry=entry,ws_port=1,**_window_defaults(entry),use_in_process_snapshots=True))
    try:
        wait_for_page(window,window.show)
        wait_for(lambda:fitted(window),app)
        circles=dimensions(window)
        window.apply_entry(with_template_value(window.entry,'display_style','bars'))
        wait_for(lambda:fitted(window) and dimensions(window)['style']=='bars',app)
        bars=dimensions(window)
        assert bars['width']<circles['width'] and bars['height']>circles['height'],(circles,bars)
        assert bars['width']/bars['height']<circles['width']/circles['height']
        for data in (circles,bars):
            assert abs(data['bottom']-data['height'])<2,data
            assert 0<data['height']-data['rowsBottom']<15,data
            assert data['cellsFit'],data
        window.apply_entry(with_template_value(window.entry,'display_style','circles'))
        wait_for(lambda:fitted(window) and dimensions(window)['style']=='circles',app)
        assert window.width()==circles['width'] and window.height()==circles['height'],(circles,dimensions(window),window.content_size.scale)
        for percent in (150,75):
            window.apply_entry(replace(window.entry,font_scale=percent/100))
            window.apply_entry(with_template_value(window.entry,'avatar_size_percent',percent))
            wait_for(lambda:fitted(window),app)
            data=dimensions(window)
            assert data['cellsFit'] and abs(data['bottom']-data['height'])<2,data
        before=window.size()
        wait_for_page(window,window.webview.reload)
        wait_for(lambda:fitted(window),app)
        assert window.size()==before
        QTest.qWait(150)  # Let Chromium's already verified DOM reach the compositor before screenshot.
        window.grab().save(str(EVIDENCE/f'combo-auto-fit-{theme}.png'))
    finally:window.close();app.processEvents()


def test_real_gui_style_control_fits_window_and_persists_reopen(main_window,app):
    window=main_window
    combo=OverlayEntry('combo-gui-fit','连携',OverlaySourceType.BUILTIN,'combo_skill',True,False,False)
    # Avoid starting screen capture; this test exercises rendering and real settings controls.
    window.vision_controller.set_enabled=lambda _:None
    window.app_config.overlays.append(combo)
    window.overlay_manager.apply_entry(combo)
    window._refresh_overlay_views()
    page=window.overlay_page
    page.overlay_list.setCurrentRow(len(window.app_config.overlays)-1)
    window.switchTo(page)
    overlay=window.overlay_manager._windows[combo.id]
    wait_for(lambda:fitted(overlay),app)
    circles=overlay.size()
    page.setting_widgets['display_style'].setCurrentIndex(1)
    wait_for(lambda:fitted(overlay) and dimensions(overlay)['style']=='bars',app)
    bars=overlay.size()
    assert bars.width()<circles.width() and bars.height()>circles.height()
    original_scale=overlay.content_size.scale
    original_font=dimensions(overlay)['font']
    page.width_edit.setValue(bars.width()+160)
    wait_for(lambda:fitted(overlay),app)
    bars=overlay.size()
    assert overlay.content_size.scale==pytest.approx(original_scale)
    assert dimensions(overlay)['font']==pytest.approx(original_font,abs=.1)
    saved=next(e for e in load_app_config(window.config_path).overlays if e.id==combo.id)
    assert saved.template_settings['display_style']=='bars'
    assert saved.template_settings['_combo_window_scale']==pytest.approx(overlay.content_size.scale)
    reopened=OverlayWindow(OverlayWindowConfig(entry=saved,ws_port=1,**_window_defaults(saved),use_in_process_snapshots=True))
    try:
        wait_for_page(reopened,reopened.show)
        wait_for(lambda:fitted(reopened),app)
        assert reopened.size()==bars
    finally:reopened.close();app.processEvents()


def test_bar_width_is_independent_and_only_height_scales_content(app):
    entry=OverlayEntry('combo-width','连携',OverlaySourceType.BUILTIN,'combo_skill',True,False,False,
                       template_settings={'display_style':'bars'})
    window=OverlayWindow(OverlayWindowConfig(entry=entry,ws_port=1,**_window_defaults(entry),use_in_process_snapshots=True))
    try:
        wait_for_page(window,window.show)
        wait_for(lambda:fitted(window),app)
        baseline=dimensions(window)
        for width in (window.width()+200, window.width()-50):
            window.resize(width,window.height())
            wait_for(lambda:fitted(window),app)
            data=dimensions(window)
            assert data['font']==pytest.approx(baseline['font'],abs=.1)
            assert data['avatar']==pytest.approx(baseline['avatar'],abs=.1)
        width=window.width()
        window.resize(width,round(window.height()*1.5))
        wait_for(lambda:fitted(window),app)
        data=dimensions(window)
        assert data['width']==width
        assert data['font']==pytest.approx(baseline['font']*1.5,abs=.15)
        assert data['avatar']==pytest.approx(baseline['avatar']*1.5,abs=.2)
        window.apply_entry(with_template_value(window.entry,'avatar_size_percent',150))
        wait_for(lambda:fitted(window),app)
        assert window.width()==width
        QTest.qWait(150)
        window.grab().save(str(EVIDENCE/'combo-bars-independent-width.png'))
    finally:window.close();app.processEvents()
