"""User controls share persisted state; templates consume canonical snapshots."""
from app_test_support.ui.window import entry, main_window
import json
from dataclasses import replace
from pathlib import Path
import pytest
from qfluentwidgets import CaptionLabel
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
import endfield_pcap.gui.config as gui_config
import endfield_pcap.gui.main as gui_main
import endfield_pcap.overlays.manager as overlay_host
from endfield_pcap.models import OverlayGeometry
from endfield_pcap.models import OverlaySourceType
from endfield_pcap.overlays.templates import read_template
from endfield_pcap.overlays.templates import template_for
from endfield_pcap.overlays.templates import template_values
from endfield_pcap.overlays.templates import with_template_value
from app_test_support.ui.qt import page_value, snapshot_message, wait_for_page, EVIDENCE


def test_buff_overlay_is_removed_from_defaults_saved_config_and_template_import(main_window, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    assert 'buff' not in {e.source_value for e in gui_config.default_overlay_entries()}
    saved = gui_config.AppConfig(service=gui_config.default_service_config(),
        overlays=[entry(source_value='buff', enabled=True)])
    path = tmp_path/'old-buff-settings.json'
    gui_config.save_app_config(saved, path)
    assert 'buff' not in {e.source_value for e in gui_config.load_app_config(path).overlays}
    from endfield_pcap.overlays.templates import ASSETS
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *args: (str(ASSETS/'buff/template.json'), ''))
    notices = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *args: notices.append(args))
    previous = list(main_window.app_config.overlays)
    main_window._add_file_overlay()
    assert notices and main_window.app_config.overlays == previous

def local_template(tmp_path):
    html = tmp_path / "custom.html"
    html.write_text('''<!doctype html><style>html{font-size:calc(16px * var(--overlay-font-scale,1))}body{margin:0}#value{font-size:2rem}</style>
    <div id="value">waiting</div><div id="mode">waiting</div>
    <script>
    window.addEventListener('endfield-analysis-snapshot', e => {
      document.querySelector('#value').textContent = e.detail.snapshot?.battle.total_damage ?? 'cleared';
    });
    window.addEventListener('endfield-overlay-config', e => {
      document.querySelector('#mode').textContent = e.detail.settings.accent;
    });
    </script>''', encoding="utf-8")
    data = dict(schema_version=1, name="Custom", entry="custom.html", font_mode="css",
        subscriptions=["analysis_snapshot"],
        window=dict(min_width=120, min_height=60, default_width=400, default_height=200),
        settings=[dict(key="accent", label="Accent", type="select", default="red",
                       options=[dict(value="red", label="Red"), dict(value="blue", label="Blue")])])
    path = tmp_path / "template.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return entry(source_type=OverlaySourceType.FILE, source_value=str(path)), data

def test_old_configuration_migrates_font_and_template_settings_without_changing_geometry():
    original = gui_config._overlay_entry_to_dict(entry(scale=1.4, bar_mode="rdps", overlay_theme="dark",
        visible_columns=("damage_rate",), geometry=OverlayGeometry(10, 20, 500, 250)))
    original.pop("font_scale")
    original.pop("template_settings")
    restored = gui_config._overlay_entry_from_dict(original)
    assert restored.font_scale == 1.4 and restored.geometry == OverlayGeometry(10, 20, 500, 250)
    assert template_values(restored) == dict(bar_mode="rdps", columns=["damage_rate"], theme="dark", show_character_avatars='on', avatar_size_percent=100)
    updated = with_template_value(restored, "columns", ["damage", "invalid"])
    assert updated.visible_columns == ("damage",)
    assert gui_config._overlay_entry_from_dict(gui_config._overlay_entry_to_dict(updated)) == updated

def test_manifest_is_local_explicit_and_validated(tmp_path):
    custom, data = local_template(tmp_path)
    template = template_for(custom)
    assert template.entry == tmp_path / "custom.html"
    assert template.subscriptions == ("analysis_snapshot",)
    assert template_for(replace(custom, source_value=str(template.entry))).path == template.path
    assert template_for(entry(source_type=OverlaySourceType.URL, source_value="https://example.invalid")).subscriptions == ()
    for changes in [dict(schema_version=2), dict(subscriptions=["event_batch"]),
                    dict(entry="missing.html"), dict(settings=[*data["settings"], *data["settings"]]),
                    dict(window=dict(min_width=0))]:
        Path(custom.source_value).write_text(json.dumps({**data, **changes}), encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            read_template(Path(custom.source_value))
        assert template_for(custom).error


def test_template_percentage_slider_validates_and_normalizes_saved_values(tmp_path):
    custom, data = local_template(tmp_path)
    data['settings'] = [dict(key='size', type='slider', min=50, max=300, default=100)]
    path = Path(custom.source_value)
    path.write_text(json.dumps(data), encoding='utf8')
    assert template_values(custom) == {'size': 100}
    for value, expected in [(175, 175), (0, 50), (999, 300), ('125', 100), (True, 100), (None, 100)]:
        assert template_values(with_template_value(custom, 'size', value)) == {'size': expected}
    for changes in [dict(min=101), dict(max=99), dict(default=True), dict(max=300.5), dict(legacy_field='bar_mode')]:
        data['settings'][0] = dict(key='size', type='slider', min=50, max=300, default=100)
        data['settings'][0].update(changes)
        path.write_text(json.dumps(data), encoding='utf8')
        assert template_for(custom).error

def test_master_visibility_is_independent_of_entry_analysis_and_close(main_window, app):
    window = main_window
    page = window.overlay_page
    button = page.status_card.visibility_button
    assert button.text() == '显示全部'
    assert not any(e.enabled for e in window.app_config.overlays)
    page.enabled_switch.setChecked(True)
    assert [e.enabled for e in window.app_config.overlays] == [True, False]
    assert button.text() == '隐藏已显示'
    assert "1 / 2" in window.overlay_page.status_card.enabled_count.text()
    streams = window.service_controller._analysis_streams
    button.click()
    assert button.text() == '恢复显示'
    assert window.app_config.overlay_restore_ids == ['controls']
    assert not page.visible_switch.isChecked()
    assert [e.enabled for e in window.app_config.overlays] == [True, False]
    assert window.service_controller._analysis_streams == streams
    assert window.overlay_manager.visible_window_count() == 0
    assert window.overlay_manager.opened_window_count() == 1
    # Shortcut restores the remembered subset, without enabling other analyses.
    window._toggle_overlay_visibility()
    assert not window.app_config.overlay_restore_ids
    assert window.overlay_manager.opened_window_count() == 1
    native = window.overlay_manager._windows["controls"]
    native.close_button.click()
    app.processEvents()
    assert window.app_config.overlays[0].enabled and page.enabled_switch.isChecked()
    assert not page.visible_switch.isChecked()
    assert window.overlay_manager._windows['controls'] is native
    assert native.isVisible() and native.windowOpacity() == 0
    assert button.text() == '显示全部'
    assert window.service_controller._analysis_streams == streams
    # No remembered set: show all eligible windows, never enable an analysis.
    button.click()
    assert window.overlay_manager.opened_window_count() == 1
    page.visible_switch.setChecked(False)
    restored = gui_config.load_app_config(window.config_path)
    current = next(e for e in restored.overlays if e.id == 'controls')
    assert current.enabled and current.hidden

def test_visibility_remembers_subset_and_manual_changes_replace_memory(main_window):
    window, page = main_window, main_window.overlay_page
    window._enable_all_overlays()
    page.visible_switch.setChecked(False)  # hide damage only; BUFF remains visible
    streams = window.service_controller._analysis_streams
    window._toggle_overlay_visibility()
    assert window.app_config.overlay_restore_ids == ['buff']
    assert window.overlay_manager.visible_window_count() == 0
    restored = gui_config.load_app_config(window.config_path)
    assert restored.overlay_restore_ids == ['buff']
    assert all(e.hidden for e in restored.overlays if e.id in {'controls', 'buff'})
    window._toggle_overlay_visibility()
    assert {key for key, native in window.overlay_manager._windows.items() if native.desktop_visible} == {'buff'}
    assert window.app_config.overlays[0].hidden
    assert not window.app_config.overlay_restore_ids
    window._toggle_overlay_visibility()  # remembers BUFF again
    page.visible_switch.setChecked(True)  # show damage independently
    window._toggle_overlay_visibility()  # current showing set takes precedence
    assert window.app_config.overlay_restore_ids == ['controls']
    window._toggle_overlay_visibility()
    assert {key for key, native in window.overlay_manager._windows.items() if native.desktop_visible} == {'controls'}
    assert window.service_controller._analysis_streams == streams
    # With neither windows nor memory, show all analyses that are enabled.
    page.visible_switch.setChecked(False)
    window._toggle_overlay_visibility()
    assert set(window.overlay_manager._windows) == {'controls', 'buff'}

def test_restore_does_not_enable_disabled_analysis_or_recreate_deleted_entry(main_window):
    window = main_window
    window._enable_all_overlays()
    window._toggle_overlay_visibility()
    window._disable_all_overlays()
    window.app_config.overlay_restore_ids.append('deleted')
    window._toggle_overlay_visibility()
    assert not window.app_config.overlay_restore_ids
    assert not any(e.enabled or e.hidden for e in window.app_config.overlays)
    assert not window.overlay_manager.opened_window_count()
    assert window.service_controller._analysis_streams == frozenset()
    # Enabled state is independent: a previously hidden entry stays hidden.
    window._replace_overlay_entry(replace(window._selected_overlay(), hidden=True))
    window._enable_all_overlays()
    assert {key for key, native in window.overlay_manager._windows.items() if native.desktop_visible} == {'buff'}

def test_controls_order_keeps_template_options_with_entry(main_window):
    page = main_window.overlay_page
    form = page.details_form
    state_row = page.enabled_switch.parentWidget()
    assert state_row.isAncestorOf(page.visible_switch)
    assert form.getWidgetPosition(state_row)[0] == 0
    assert form.getWidgetPosition(page.name_edit)[0] == 1
    assert page._template_start_row == 2
    assert page.locked_switch.parentWidget().isAncestorOf(page.click_switch)
    assert form.getWidgetPosition(page.font_size_slider.parentWidget())[0] < form.getWidgetPosition(page.geometry_label.parentWidget())[0]
    assert page.geometry_label.parentWidget() is page.reset_layout_btn.parentWidget()
    assert page.content_layout.indexOf(page.add_actions) == 0
    assert page.content_layout.indexOf(page.status_card) == 1
    assert page.status_card.headerLabel.text() == '一键配置'
    assert page.status_card.isAncestorOf(page.enable_all_btn)
    assert page.status_card.isAncestorOf(page.disable_all_btn)
    # Changing template and returning must replace its rows at the same anchor.
    for index in (1, 0, 1, 0):
        page.overlay_list.setCurrentRow(index)
        expected = template_for(main_window._selected_overlay()).settings
        assert set(page.setting_widgets) == {row['key'] for row in expected}
        assert form.getWidgetPosition(page.width_edit.parentWidget())[0] == 2 + len(expected)

def test_shared_subscription_is_required_until_last_entry_is_disabled(app):
    demand = []
    manager = overlay_host.OverlayManager(1, visible=False, on_analysis_requirement=demand.append)
    manager.apply_entry(entry(id='one', enabled=True))
    manager.apply_entry(entry(id='two', enabled=True))
    manager.apply_entry(entry(id='one', enabled=False))
    assert demand[-1] == frozenset({'analysis_summary'})
    manager.apply_entry(entry(id='two', enabled=False))
    assert demand[-1] == frozenset()
    assert not manager.opened_window_count()

def test_display_switch_is_disabled_with_analysis_and_preserves_choice(main_window):
    window, page = main_window, main_window.overlay_page
    assert not page.visible_switch.isEnabled()
    assert page.visible_switch.isChecked()
    # Disabled controls cannot mutate config, including programmatic signals.
    page.visible_switch.setChecked(False)
    assert not window._selected_overlay().hidden
    page.enabled_switch.setChecked(True)
    assert page.visible_switch.isEnabled() and page.visible_switch.isChecked()
    page.visible_switch.setChecked(False)
    assert window._selected_overlay().hidden
    page.enabled_switch.setChecked(False)
    assert not page.visible_switch.isEnabled() and not page.visible_switch.isChecked()
    page.enabled_switch.setChecked(True)
    assert page.visible_switch.isEnabled() and not page.visible_switch.isChecked()

def test_pair_spacing_keeps_controls_closer_to_their_own_labels(main_window, app):
    window, page = main_window, main_window.overlay_page
    window.switchTo(page)
    app.processEvents()
    for first, second in ((page.enabled_switch, page.visible_switch), (page.locked_switch, page.click_switch)):
        row = first.parentWidget()
        label = page.details_form.labelForField(row)
        next_label = row.findChild(CaptionLabel, 'secondControlLabel')
        first_x = first.mapTo(page, QPoint()).x()
        next_label_x = next_label.mapTo(page, QPoint()).x()
        own_gap = first_x - (label.mapTo(page, QPoint()).x() + label.width())
        next_gap = second.mapTo(page, QPoint()).x() - (next_label_x + next_label.width())
        group_gap = next_label_x - (first_x + first.width())
        assert first_x == page.name_edit.mapTo(page, QPoint()).x()
        assert label.mapTo(page, QPoint()).x() == page.details_form.labelForField(page.name_edit).mapTo(page, QPoint()).x()
        assert group_gap >= 112 and group_gap > own_gap and group_gap > next_gap

def test_hidden_window_keeps_rendering_and_restores_same_geometry(main_window, app):
    window, page = main_window, main_window.overlay_page
    page.enabled_switch.setChecked(True)
    native = window.overlay_manager._windows['controls']
    wait_for_page(native, lambda: None)
    window.overlay_manager.show_history({'battle': {'total_damage': 0}}, 'hidden history')
    QTest.qWait(250)
    hwnd = int(native.winId())
    page.width_edit.setValue(640)
    page.height_edit.setValue(320)
    page.opacity_slider.setValue(60)
    before = native.geometry()
    page.visible_switch.setChecked(False)
    assert native.isVisible() and not native.desktop_visible
    assert native.windowOpacity() == 0
    assert native.windowFlags() & Qt.WindowType.WindowTransparentForInput
    window.overlay_manager.show_history({'battle': {'total_damage': 123}}, 'hidden history')
    assert page_value(native, 'document.querySelector("#totalDamage").textContent') == '123'
    assert native.geometry() == before and int(native.winId()) == hwnd
    page.visible_switch.setChecked(True)
    assert native.desktop_visible and native.windowOpacity() == pytest.approx(.6, abs=.005)
    assert native.geometry() == before and int(native.winId()) == hwnd
    assert not native.windowFlags() & Qt.WindowType.WindowTransparentForInput
    page.enabled_switch.setChecked(False)
    assert not page.visible_switch.isEnabled()
    assert not window.overlay_manager.opened_window_count()

def test_legacy_obs_port_is_ignored_and_mirror_controls_are_absent(main_window, tmp_path):
    window = main_window
    path = tmp_path / 'legacy-obs.json'
    gui_config.save_app_config(window.app_config, path)
    payload = json.loads(path.read_text(encoding='utf8'))
    payload['obs_port'] = 'retired-invalid-value'
    path.write_text(json.dumps(payload), encoding='utf8')
    restored = gui_config.load_app_config(path)
    gui_config.save_app_config(restored, path)
    assert 'obs_port' not in json.loads(path.read_text(encoding='utf8'))
    assert not hasattr(window, 'obs_mirror')
    assert not hasattr(window.overlay_page, 'obs_url_edit')

def test_older_config_defaults_visibility_without_changing_entries(tmp_path):
    path = tmp_path / 'old.json'
    config = gui_config.AppConfig(service=gui_config.default_service_config(), overlays=[entry(enabled=True)])
    gui_config.save_app_config(config, path)
    payload = json.loads(path.read_text(encoding='utf8'))
    payload.pop('overlay_restore_ids')
    for current in payload['overlays']:
        current.pop('hidden')
    path.write_text(json.dumps(payload), encoding='utf8')
    restored = gui_config.load_app_config(path)
    assert not restored.overlay_restore_ids
    assert not any(row.hidden for row in restored.overlays)
    assert next(row for row in restored.overlays if row.id == 'controls').enabled

def test_legacy_global_hide_migrates_once_and_roundtrips_restore_memory(tmp_path):
    path = tmp_path / 'old-hidden.json'
    config = gui_config.AppConfig(service=gui_config.default_service_config(), overlays=[entry(enabled=True)])
    gui_config.save_app_config(config, path)
    payload = json.loads(path.read_text(encoding='utf8'))
    payload.pop('overlay_restore_ids')
    payload['overlays_visible'] = False
    path.write_text(json.dumps(payload), encoding='utf8')
    restored = gui_config.load_app_config(path)
    assert all(row.hidden for row in restored.overlays)
    assert set(restored.overlay_restore_ids) == {row.id for row in restored.overlays}
    gui_config.save_app_config(restored, path)
    assert 'overlays_visible' not in json.loads(path.read_text(encoding='utf8'))
    assert gui_config.load_app_config(path) == restored

def test_numeric_dimensions_drag_font_and_lock_are_independent(main_window, app):
    window = main_window
    page = window.overlay_page
    page.enabled_switch.setChecked(True)
    native = window.overlay_manager._windows["controls"]
    page.width_edit.setValue(620)
    page.height_edit.setValue(340)
    assert (native.width(), native.height()) == (620, 340)
    native.move(100, 100)
    # Exercise the same press/move/release path used by native edge dragging.
    origin = native.mapToGlobal(QPoint(619, 339))
    native._handle_mouse_press(QPoint(619, 339), origin)
    native._handle_mouse_move(QPoint(659, 359), origin + QPoint(40, 20), Qt.MouseButton.LeftButton)
    native._handle_mouse_release(QPoint(659, 359))
    app.processEvents()
    assert (page.width_edit.value(), page.height_edit.value()) == (660, 360)
    before = window._selected_overlay().geometry
    page.font_size_slider.setValue(150)
    assert window._selected_overlay().geometry == before
    QTest.qWait(250)
    assert native.webview.zoomFactor() == 1
    page.locked_switch.setChecked(True)
    assert native._hit_test_edges(QPoint()) == Qt.Edge(0)
    page.width_edit.setValue(680)  # lock prevents dragging, never numeric editing
    assert native.width() == 680
    page.click_switch.setChecked(True)
    assert native.close_button.isHidden()
    page.click_switch.setChecked(False)
    assert not native.close_button.isHidden()
    saved = gui_config.load_app_config(window.config_path).overlays[0]
    assert saved.font_scale == 1.5 and saved.geometry.width == 680
    window.switchTo(page)
    QTest.qWait(250)
    # Content fitting can finish asynchronously after a font change. Editors
    # must reflect the resulting native geometry, including its minimum width.
    for field, expected in ((page.width_edit, str(native.width())), (page.height_edit, str(native.height()))):
        assert field.isVisible() and field.width() >= 80 and field.text() == expected
    assert page.font_size_slider.value() == 150 and page.font_size_value.text() == "150%"
    page.width_edit.selectAll()
    QTest.keyClicks(page.width_edit, "720")
    QTest.keyClick(page.width_edit, Qt.Key.Key_Return)
    assert native.width() == 720
    assert window.grab().save(str(EVIDENCE / "gui-controls.png"))
    window._apply_gui_theme('light')
    QTest.qWait(100)
    assert window.grab().save(str(EVIDENCE / 'gui-controls-light.png'))

def test_reset_current_overlay_layout_is_persisted_and_preserves_options(main_window, app):
    window, page = main_window, main_window.overlay_page
    window._replace_overlay_entry(replace(window._selected_overlay(), name='我的统计'))
    page.enabled_switch.setChecked(True)
    native = window.overlay_manager._windows['controls']
    wait_for_page(native, lambda: None)
    page.width_edit.setValue(620)
    page.height_edit.setValue(340)
    native.move(100, 100)
    page.font_size_slider.setValue(150)
    page.opacity_slider.setValue(70)
    page.locked_switch.setChecked(True)
    before = window._selected_overlay()
    page.reset_layout_btn.click()
    QTest.qWait(250)
    after = window._selected_overlay()
    fitted_scale = native.content_size.scale
    assert after == replace(before, geometry=after.geometry, font_scale=1, scale=1,
                            template_settings={**before.template_settings, '_damage_window_scale': fitted_scale})
    assert window.overlay_manager._windows['controls'] is native
    reference = page_value(native, 'window.endfieldOverlay.contentReference')
    assert abs(native.width()-max(320, reference['width']*fitted_scale)) < 1
    assert abs(native.height()-max(160, reference['height']*fitted_scale)) < 1
    screen = app.primaryScreen().availableGeometry()
    assert (native.x(), native.y()) == (max(screen.x(), screen.x()+screen.width()-native.width()-native.config.margin_right), screen.top()+native.config.margin_top)
    assert page.font_size_slider.value() == 100
    QTest.qWait(150)  # Chromium applies the native resize on its next frame.
    assert page_value(native, 'getComputedStyle(document.documentElement).getPropertyValue("--overlay-user-font-scale").trim()') == '1'
    persisted = json.loads(window.config_path.read_text(encoding='utf8'))['overlays']
    assert next(e for e in persisted if e['id'] == after.id) == gui_config._overlay_entry_to_dict(after)
    window.switchTo(page)
    QTest.qWait(700)
    assert page.reset_layout_btn.isVisible()
    page.ensureWidgetVisible(page.reset_layout_btn)
    window.repaint()
    if app.platformName() == 'offscreen':
        window.resize(1200, 1040)
        app.processEvents()
    assert window.grab().save(str(EVIDENCE / 'gui-overlay-reset.png'))
    if app.platformName() == 'windows':
        assert window.screen().grabWindow(int(window.winId())).save(str(EVIDENCE / 'gui-overlay-reset-native.png'))
    # Resetting a closed entry changes only its saved presentation.
    page.enabled_switch.setChecked(False)
    window._replace_overlay_entry(replace(window._selected_overlay(), geometry=OverlayGeometry(1, 2, 600, 300), font_scale=1.5))
    page.reset_layout_btn.click()
    assert not window._selected_overlay().enabled
    assert window.overlay_manager.opened_window_count() == 0
    assert window._selected_overlay().geometry is None

@pytest.mark.parametrize('uid', [False, True])
def test_reset_uses_template_default_geometry(app, tmp_path, uid):
    original, _ = local_template(tmp_path)
    if uid:
        original = entry(source_value='uid_mask')
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    try:
        original = replace(original, enabled=True, font_scale=1.5, geometry=OverlayGeometry(100, 100, 640, 300))
        manager.apply_entry(original)
        native = manager._windows[original.id]
        manager.apply_entry(replace(original, geometry=None, font_scale=1))
        defaults = overlay_host._window_defaults(original)
        assert (native.width(), native.height()) == (defaults['default_width'], defaults['default_height'])
        if uid:
            screen = app.primaryScreen().geometry()
            assert native.x() == screen.x()+12
            assert native.y() == screen.bottom()-native.height()-10
    finally:
        manager.close_all();app.processEvents()

def test_damage_resize_and_font_multiplier_scale_once_and_restore(app):
    original = entry(enabled=True, geometry=OverlayGeometry(0, 0, 700, 350))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=original, ws_port=1, use_in_process_snapshots=True))
    try:
        window.apply_analysis_snapshot(snapshot_message())
        wait_for_page(window, window.show)
        QTest.qWait(250)
        expression = "[...document.querySelectorAll('body *')].filter(n => [...n.childNodes].some(c => c.nodeType === 3 && c.textContent.trim())).map(n => parseFloat(getComputedStyle(n).fontSize))"
        before = page_value(window, expression)
        scale_expression = "Number(getComputedStyle(document.documentElement).getPropertyValue('--overlay-window-scale'))"
        baseline_scale = page_value(window, scale_expression)
        window.apply_entry(replace(original, font_scale=1.5))
        QTest.qWait(250)
        after = page_value(window, expression)
        assert len(before) == len(after) and len(before) >= 10
        multiplier = 1.5 * page_value(window, scale_expression) / baseline_scale
        assert all(abs(a * multiplier - b) < .1 for a, b in zip(before, after)), (before, after, multiplier)
        fitted_size = window.size()
        reference = page_value(window, 'window.endfieldOverlay.contentReference')
        before_resize_scale = min(window.width()/reference['width'], window.height()/reference['height'])
        resize_width = min(900, window.screen().availableGeometry().width())
        window.resize(resize_width, 500)
        QTest.qWait(150)
        resized = page_value(window, expression)
        resize_ratio = min(resize_width/reference['width'], 500/reference['height'])/before_resize_scale
        assert all(abs(a * resize_ratio - b) < .1 for a, b in zip(after, resized))
        window.apply_analysis_snapshot(snapshot_message(2))
        assert page_value(window, expression) == resized
        wait_for_page(window, window.webview.reload)
        QTest.qWait(250)
        assert all(abs(a-b)<.1 for a,b in zip(page_value(window, expression), resized))
        window.resize(fitted_size)
        QTest.qWait(150)
        assert page_value(window, expression) == after
        assert window.grab().save(str(EVIDENCE / "damage-font-150.png"))
    finally:
        window.close(); app.processEvents()

def test_custom_template_controls_history_replay_and_return_live(app, tmp_path):
    custom, _ = local_template(tmp_path)
    changes = []
    page = gui_main.OverlayPage()
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    try:
        page.show_entry(custom)
        assert set(page.setting_widgets) == {"accent"}
        page.setting_changed.connect(lambda key, value: changes.append(with_template_value(custom, key, value)))
        page.setting_widgets["accent"].setCurrentIndex(1)
        assert changes[-1].template_settings == {"accent": "blue"}
        custom = replace(changes[-1], enabled=True)
        manager.apply_analysis_snapshot(snapshot_message())
        manager.apply_entry(custom)
        window = manager._windows[custom.id]
        # The manager has scheduled the initial load; wait before reloading.
        wait_for_page(window, lambda: None)
        assert "snapshotTransport=inprocess" in window.webview.url().toString()
        assert page_value(window, "document.querySelector('#value').textContent") == "760"
        assert page_value(window, "document.querySelector('#mode').textContent") == "blue"
        manager.show_history({"battle": {"total_damage": 123}}, "history")
        assert page_value(window, "document.querySelector('#value').textContent") == "123"
        manager.apply_analysis_snapshot(snapshot_message(2, {"battle": {"total_damage": 999}}))
        assert page_value(window, "document.querySelector('#value').textContent") == "123"
        wait_for_page(window, window.webview.reload)
        assert page_value(window, "document.querySelector('#value').textContent") == "123"
        assert page_value(window, "Object.keys(window.endfieldOverlay.snapshots)") == ["analysis_snapshot"]
        manager.return_live()
        assert page_value(window, "document.querySelector('#value').textContent") == "999"
        manager.apply_entry(replace(custom, enabled=False))
        manager.apply_entry(custom)
        window = manager._windows[custom.id]
        wait_for_page(window, lambda: None)
        assert page_value(window, "document.querySelector('#value').textContent") == "999"
        manager.apply_analysis_snapshot({**snapshot_message(3), "snapshot": None})
        assert page_value(window, "document.querySelector('#value').textContent") == "cleared"
        assert window.grab().save(str(EVIDENCE / "custom-template.png"))
    finally:
        page.close(); manager.close_all(); app.processEvents()

def test_plain_html_font_scaling_including_dynamic_nodes_does_not_compound(app, tmp_path):
    path = tmp_path / "plain.html"
    path.write_text('<html><body style="font-size:20px"><div id="label">label<span style="font-size:12px">small</span></div></body></html>', encoding="utf-8")
    custom = entry(enabled=True, source_type=OverlaySourceType.FILE, source_value=str(path))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(entry=custom, ws_port=1))
    try:
        wait_for_page(window, window.show)
        expression = "[...document.querySelectorAll('#label, #label *')].map(n => parseFloat(getComputedStyle(n).fontSize))"
        assert page_value(window, expression) == [20, 12]
        window.apply_entry(replace(custom, font_scale=1.5))
        assert page_value(window, expression) == [30, 18]
        page_value(window, "document.querySelector('#label').appendChild(document.createElement('b')).textContent = 'new'")
        QTest.qWait(100)
        assert page_value(window, expression) == [30, 18, 30]
        window.apply_entry(replace(custom, font_scale=1.5))
        assert page_value(window, expression) == [30, 18, 30]
        window.apply_entry(custom)
        assert page_value(window, expression) == [20, 12, 20]
        assert page_value(window, "Object.keys(window.endfieldOverlay.snapshots)") == []
    finally:
        window.close(); app.processEvents()
