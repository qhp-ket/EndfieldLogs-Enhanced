"""Qt receives canonical state on its own thread and replays it on page load."""
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from endfield_pcap import gui_main, overlay_host
from endfield_pcap import gui_config
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from parser_core.unified import parse_overlay_battle_snapshot_text
from test_combo_cooldowns import publisher, scene, trigger

EVIDENCE = Path(os.environ.get("ENDFIELD_UI_EVIDENCE_DIR",
    str(Path(__file__).resolve().parents[2] / "_development/implementations/implementation-ui-20261021")))




def snapshot_message(sequence=1, snapshot=None):
    if snapshot is None:
        root = Path(__file__).resolve().parents[2]
        text = (root / "_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log").read_text(encoding="utf-8")
        snapshot = parse_overlay_battle_snapshot_text(text)
    return {"type": "analysis_snapshot", "schema_version": 1,
            "stream_id": "qt-test", "sequence": sequence, "snapshot": snapshot}


def test_service_observer_passes_snapshot_through_existing_gui_queue(monkeypatch):
    message = snapshot_message()
    from parser_core.live_summary import summary_from_report
    message = {**message, 'type': 'analysis_summary', 'snapshot': summary_from_report(message['snapshot'])}
    class Service:
        def __init__(self, config, observer):
            self.observer = observer
        def set_full_analysis_required(self, required):
            pass
        async def run(self):
            self.observer.on_analysis_summary(message)
    monkeypatch.setattr("endfield_pcap.gui_service.DamageLogService", Service)
    controller = gui_main.ServiceController(SimpleNamespace())
    controller.start()
    controller.join()
    received = []
    window = SimpleNamespace(
        service_controller=controller,
        overlay_manager=SimpleNamespace(apply_analysis_summary=lambda payload, *, take_ownership: received.append(payload)),
        _update_service_status=lambda: None,
        _finish_service_stop=lambda: None,
    )
    gui_main.MainWindow._drain_queue(window)
    assert received == [message]
    assert controller.queue.empty()


def test_manager_keeps_latest_for_newly_enabled_overlay(monkeypatch):
    class Window:
        def __init__(self, config):
            self.config = config
            self.messages = []
        def apply_analysis_snapshot(self, message):
            self.messages.append(message)
        def show(self):
            pass
    monkeypatch.setattr(overlay_host, "OverlayWindow", Window)
    manager = overlay_host.OverlayManager(29325, use_in_process_snapshots=True)
    message = snapshot_message()
    manager.apply_analysis_snapshot(message)
    message["snapshot"]["battle"]["total_damage"] = -1
    entry = OverlayEntry(id="damage", name="damage", source_type=OverlaySourceType.BUILTIN,
                         source_value="damage", enabled=True, locked=False, click_through=False)
    manager.apply_entry(entry)
    window = manager._windows["damage"]
    assert window.config.use_in_process_snapshots is True
    assert window.messages[-1]["snapshot"]["battle"]["total_damage"] == 760
    cleared = {**message, "sequence": 2, "snapshot": None}
    manager.apply_analysis_snapshot(cleared)
    assert window.messages[-1]["snapshot"] is None


def wait_for_page(window, trigger):
    loop = QEventLoop()
    results = []
    def loaded(ok):
        results.append(ok)
        loop.quit()
    window.webview.loadFinished.connect(loaded)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(15_000)
    trigger()
    loop.exec()
    timer.stop()
    window.webview.loadFinished.disconnect(loaded)
    assert results == [True], "Qt WebEngine did not load the existing overlay page"


def read_dom(window):
    loop = QEventLoop()
    result = []
    def received(value):
        result.append(json.loads(value))
        loop.quit()
    window.webview.page().runJavaScript("JSON.stringify({damage: document.getElementById('totalDamage').textContent, dps: document.getElementById('totalDps').textContent, rows: document.getElementById('rows').children.length, quality: document.getElementById('footerText').textContent})", received)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5_000)
    loop.exec()
    timer.stop()
    assert result, "Qt WebEngine DOM callback timed out"
    return result[0]


def test_actual_qt_webengine_renders_replays_and_clears_canonical_snapshot(app):
    entry = OverlayEntry(id="qt-smoke", name="damage", source_type=OverlaySourceType.BUILTIN,
                         source_value="damage", enabled=True, locked=False, click_through=False)
    config = overlay_host.OverlayWindowConfig(entry=entry, ws_port=1, use_in_process_snapshots=True)
    window = overlay_host.OverlayWindow(config)
    try:
        message = snapshot_message()
        # Delivery before load completion must be replayed once JS has installed its observer.
        window.apply_analysis_snapshot(message)
        wait_for_page(window, window.show)
        assert "snapshotTransport=inprocess" in window.webview.url().toString()
        dom = read_dom(window)
        assert dom["damage"] == "760" and dom["dps"] == "380" and dom["rows"] == 2
        assert "暂定" in dom["quality"]
        paint_loop = QEventLoop()
        QTimer.singleShot(200, paint_loop.quit)
        paint_loop.exec()
        preview = EVIDENCE / "qt-overlay-preview.png"
        assert window.grab().save(str(preview))
        window.apply_analysis_snapshot(message)
        assert read_dom(window) == dom
        wait_for_page(window, window.webview.reload)
        assert read_dom(window) == dom
        window.apply_analysis_snapshot({**message, "sequence": 2, "snapshot": None})
        assert read_dom(window)["rows"] == 0
        assert read_dom(window)["damage"] == "0"
    finally:
        window.close()
        app.processEvents()


def page_value(window, expression):
    loop = QEventLoop()
    results = []
    def received(value):
        results.append(json.loads(value))
        loop.quit()
    window.webview.page().runJavaScript("JSON.stringify(" + expression + ")", received)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    loop.exec()
    timer.stop()
    assert results
    return results[0]


def test_actual_qt_combo_page_replays_four_slots_on_load_reload_and_reset(app):
    entry = OverlayEntry(id="combo-smoke", name="连携 CD", source_type=OverlaySourceType.BUILTIN,
                         source_value="combo_skill", enabled=True, locked=True, click_through=False)
    config = overlay_host.OverlayWindowConfig(entry=entry, ws_port=1, default_width=300,
                                             min_width=180, min_height=1, default_height=200,
                                             use_in_process_snapshots=True)
    window = overlay_host.OverlayWindow(config)
    try:
        p, clock = publisher()
        p.feed_event(scene())
        p.feed_event(trigger())
        message = p.current_message()
        window.apply_combo_snapshot(message)
        wait_for_page(window, window.show)
        assert window.webview.url().path().endswith("combo.html")
        expression = "Array.from(document.querySelectorAll('.combo-remaining'), node => node.textContent)"
        assert page_value(window, expression) == ["20.0s", "未知", "未知", "未知"]
        window.apply_combo_snapshot(message)
        wait_for_page(window, window.webview.reload)
        assert page_value(window, expression) == ["20.0s", "未知", "未知", "未知"]
        paint = QEventLoop()
        QTimer.singleShot(600, paint.quit)
        paint.exec()
        dimensions = page_value(window, "({shell: document.querySelector('.combo-overlay-shell').getBoundingClientRect().height, height: window.innerHeight})")
        # Native Windows WebEngine can report 200.000015 for a 200px box.
        # Allow subpixel arithmetic noise, while rejecting visible clipping.
        assert dimensions["shell"] <= dimensions["height"] + .01, json.dumps({**dimensions, "native": window.height(), "font": window.entry.font_scale})
        preview = EVIDENCE / "qt-combo-preview.png"
        assert window.grab().save(str(preview))
        for scale in [0.8, 1.25]:
            window.apply_entry(replace(entry, font_scale=scale, geometry=OverlayGeometry(0, 0, 300, 300)))
            paint = QEventLoop()
            QTimer.singleShot(350, paint.quit)
            paint.exec()
            assert page_value(window, "document.querySelector('.combo-overlay-shell').getBoundingClientRect().height <= window.innerHeight")
        p.clear_cooldowns()
        window.apply_combo_snapshot(p.current_message())
        assert page_value(window, expression) == ["未知"] * 4
    finally:
        window.close()
        app.processEvents()


def test_damage_four_columns_fit_default_and_minimum_width_and_show_four_members(app):
    entry = OverlayEntry(id="damage-layout", name="damage", source_type=OverlaySourceType.BUILTIN,
                         source_value="damage", enabled=True, locked=False, click_through=False,
                         geometry=OverlayGeometry(0, 0, 700, 350))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=entry, ws_port=1, **overlay_host._window_defaults(entry), use_in_process_snapshots=True))
    try:
        message = snapshot_message()
        for name in ["陈千语", "狼卫"]:
            message["snapshot"]["participants"].append({"character_name": name, "total_damage": 0,
                                                        "total_rd": 0, "crit_rate": None})
        window.apply_analysis_snapshot(message)
        wait_for_page(window, window.show)
        assert (window.minimumWidth(), window.minimumHeight()) == (320, 160)
        for width, height, font_scale in [(700, 350, 1), (600, 300, .85), (480, 240, .7), (320, 160, .5)]:
            window.apply_entry(replace(entry, font_scale=font_scale, geometry=OverlayGeometry(0, 0, width, height)))
            app.processEvents()
            painted = QEventLoop(); QTimer.singleShot(100, painted.quit); painted.exec()
            dimensions = page_value(window, """(() => {
              const body = document.querySelector('.table-body');
              const rows = Array.from(document.querySelectorAll('.row'));
              const cells = Array.from(rows[0].querySelectorAll('.row-stat'));
              const heading = Array.from(document.querySelectorAll('.table-label')).map(n => n.textContent);
              const centers = Array.from(document.querySelectorAll('.table-label')).slice(-4).map(n => {
                const rect = n.getBoundingClientRect(); return rect.x + rect.width / 2;
              });
              return {heading, cells: cells.length, width: window.innerWidth, height: window.innerHeight,
                centers, rowCenters: cells.map(n => {const rect = n.getBoundingClientRect(); return rect.x + rect.width / 2;}),
                right: cells.at(-1).getBoundingClientRect().right,
                bottom: rows.at(-1).getBoundingClientRect().bottom,
                bodyBottom: body.getBoundingClientRect().bottom,
                headerSize: parseFloat(getComputedStyle(document.getElementById('totalDamage')).fontSize)};
            })()""")
            assert dimensions["heading"][-4:] == ["DMG", "DMG rate", "rDMG", "rDMG rate"]
            assert dimensions["cells"] == 4 and abs(dimensions["headerSize"] - 36 * font_scale) < .1
            assert dimensions["right"] < dimensions["width"]
            assert dimensions["bottom"] <= dimensions["bodyBottom"]
            assert dimensions["bodyBottom"] < dimensions["height"]
            assert all(abs(head - cell) <= 2 for head, cell in zip(dimensions["centers"], dimensions["rowCenters"])), json.dumps(dimensions)
            assert window.grab().save(str(EVIDENCE / f"damage-{width}x{height}.png"))
        paint = QEventLoop()
        QTimer.singleShot(200, paint.quit)
        paint.exec()
        preview = EVIDENCE / "qt-four-member-preview.png"
        assert window.grab().save(str(preview))
    finally:
        window.close()
        app.processEvents()




def test_bar_mode_gui_control_persists_and_changes_only_chart_and_sort(app):
    page = gui_main.OverlayPage()
    entry = OverlayEntry("mode", "damage", OverlaySourceType.BUILTIN, "damage", True, False, False)
    replaced = []
    target = SimpleNamespace(overlay_page=page, _selected_overlay=lambda: entry,
                             _replace_overlay_entry=replaced.append)
    try:
        page.show_entry(entry)
        assert page.setting_widgets["bar_mode"].isEnabled() and page.setting_widgets["bar_mode"].currentIndex() == 0
        gui_main.MainWindow._apply_template_setting(target, "bar_mode", "rdps")
        assert replaced[-1].bar_mode == "rdps"
        encoded = gui_config._overlay_entry_to_dict(replaced[-1])
        assert gui_config._overlay_entry_from_dict(encoded).bar_mode == "rdps"
        encoded.pop("bar_mode")
        assert gui_config._overlay_entry_from_dict(encoded).bar_mode == "dps"
        page.show_entry(replace(entry, source_value="combo_skill"))
        assert "bar_mode" not in page.setting_widgets
    finally:
        page.close()
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=entry, ws_port=1, use_in_process_snapshots=True))
    try:
        window.apply_analysis_snapshot(snapshot_message())
        wait_for_page(window, window.show)
        before = read_dom(window)
        expression = "Array.from(document.querySelectorAll('.row-progress'), n => n.style.width)"
        assert page_value(window, expression) == ["100%", "0%"]
        window.apply_entry(replace(entry, bar_mode="rdps"))
        assert page_value(window, expression) == ["100%", "18.75%"]
        assert read_dom(window) == before
        wait_for_page(window, window.webview.reload)
        assert page_value(window, expression) == ["100%", "18.75%"]
    finally:
        window.close()
        app.processEvents()


@pytest.mark.parametrize("theme", ["light", "dark", "transparent"])
def test_readable_themes_and_all_column_combinations_render_and_reload(app, theme):
    entry = OverlayEntry("themes", "damage", OverlaySourceType.BUILTIN, "damage", True, False, False,
                         overlay_theme=theme, geometry=OverlayGeometry(0, 0, 600, 350))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=entry, ws_port=1, min_width=600, use_in_process_snapshots=True))
    message = snapshot_message()
    for name, damage, rdamage in [("弭弗", 2345678, 1234567), ("骏卫", 345678, 456789)]:
        message["snapshot"]["participants"].append({"character_name": name, "total_damage": damage,
                                                    "total_rd": rdamage, "crit_rate": .375})
    message["snapshot"]["battle"]["total_damage"] = 2692116
    try:
        window.apply_analysis_snapshot(message)
        wait_for_page(window, window.show)
        dimensions = page_value(window, """(() => {
            const cells = [...document.querySelectorAll('.row-stat')];
            const headers = [...document.querySelectorAll('.table-label')];
            return {theme: document.documentElement.dataset.theme,
              fonts: cells.map(n => getComputedStyle(n).fontSize),
              headers: headers.slice(1).map(n => parseFloat(getComputedStyle(n).fontSize)),
              transforms: headers.map(n => getComputedStyle(n).textTransform),
              avatars: document.querySelectorAll('.row-avatar').length,
              fits: cells.every(n => n.scrollWidth <= n.clientWidth) && headers.every(n => n.scrollWidth <= n.clientWidth),
              background: getComputedStyle(document.querySelector('.overlay-card')).backgroundColor,
              bar: getComputedStyle(document.querySelector('.row-progress')).backgroundColor};
        })()""")
        assert dimensions["theme"] == theme
        assert len(set(dimensions["fonts"])) == 1
        assert min(dimensions["headers"]) >= 19
        assert set(dimensions["transforms"]) == {"none"}
        assert dimensions["avatars"] == 0 and dimensions["fits"], dimensions
        assert dimensions["bar"].startswith("rgba(218, 35, 65") if theme == "light" else True
        if theme == "transparent": assert dimensions["background"] == "rgba(0, 0, 0, 0)"
        decoration = page_value(window, """({corner: getComputedStyle(document.querySelector('.corner')).display,
          stripe: getComputedStyle(document.querySelector('.overlay-footer')).backgroundImage,
          header: getComputedStyle(document.querySelector('.overlay-header')).backgroundColor,
          headerBorder: getComputedStyle(document.querySelector('.overlay-header')).borderBottomColor,
          row: getComputedStyle(document.querySelector('.row')).backgroundColor})""")
        if theme == "transparent":
            assert decoration["corner"] == "none" and decoration["stripe"] == "none"
            assert decoration["header"] == decoration["row"] == "rgba(0, 0, 0, 0)"
            assert decoration["headerBorder"] == "rgba(0, 0, 0, 0)"
        else:
            assert decoration["corner"] != "none" and "repeating-linear-gradient" in decoration["stripe"]
        loop = QEventLoop(); QTimer.singleShot(200, loop.quit); loop.exec()
        output = EVIDENCE
        assert window.grab().save(str(output / f"damage-{theme}.png"))
        keys = entry.visible_columns
        for mask in range(16):
            selected = tuple(key for i, key in enumerate(keys) if mask & (1 << i))
            window.apply_entry(replace(entry, visible_columns=selected))
            assert page_value(window, "document.querySelectorAll('.row')[0].querySelectorAll('.row-stat').length") == len(selected)
            assert page_value(window, "document.querySelectorAll('.table-label').length") == 1 + len(selected)
        selected = ("damage_rate", "rdamage_rate")
        window.apply_entry(replace(entry, visible_columns=selected))
        wait_for_page(window, window.webview.reload)
        assert page_value(window, "document.querySelectorAll('.row')[0].querySelectorAll('.row-stat').length") == 2
        loop = QEventLoop(); QTimer.singleShot(200, loop.quit); loop.exec()
        assert window.grab().save(str(output / f"damage-{theme}-rates.png"))
    finally:
        window.close(); app.processEvents()


@pytest.mark.parametrize("theme", ["light", "dark", "transparent"])
def test_combo_all_background_modes_with_mifu(app, theme):
    entry = OverlayEntry("combo-themes", "连携", OverlaySourceType.BUILTIN, "combo_skill", True, True, False,
                         overlay_theme=theme)
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=entry, ws_port=1, min_width=180, min_height=1, default_width=300, default_height=200,
        use_in_process_snapshots=True))
    try:
        p, clock = publisher()
        roster = scene(); roster["char_list"][0]["display_name"] = "弭弗"
        p.feed_event(roster); p.feed_event(trigger(2115)); clock.advance(4500)
        window.apply_combo_snapshot(p.current_message())
        wait_for_page(window, window.show)
        assert page_value(window, "document.documentElement.dataset.theme") == theme
        assert page_value(window, "document.querySelector('.combo-name').textContent") == "弭弗"
        loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
        output = EVIDENCE
        assert window.grab().save(str(output / f"combo-{theme}.png"))
    finally:
        window.close(); app.processEvents()


def test_gui_columns_theme_history_load_and_return_live_with_actual_widgets(app, monkeypatch, tmp_path):
    from test_history_overlay import raw_scene, raw_hit
    events = [raw_scene(), {"type": "SC_OBJECT_ENTER_VIEW", "timestamp_ms": 1_000_100,
        "objects": [{"battle_inst_id": 99, "templateid": "eny_0051_rodin"}]},
        {"type": "BattleOpModifyBattleState", "timestamp_ms": 1_001_000, "is_in_battle": True},
        raw_hit(1_002_000, 100), raw_hit(1_003_000, 200),
        {"type": "BattleOpModifyBattleState", "timestamp_ms": 1_004_000, "is_in_battle": False}]
    for event in events:
        event["timestamp_ms"] += 1_792_000_000_000
    (tmp_path / "session_gui.ndjson").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    cfg = gui_config.AppConfig(service=gui_config.default_service_config(),
        overlays=[replace(entry, enabled=False) for entry in gui_config.default_overlay_entries()])
    cfg.service.log_dir = tmp_path
    cfg.theme_mode = "dark"
    monkeypatch.setattr(gui_main.MainWindow, "_ensure_game_directory_ready", lambda self: True)
    monkeypatch.setattr(gui_main.MainWindow, "_update_overlay_shortcut", lambda self: None)
    # Match run_gui(): establish Fluent's theme before constructing widgets.
    gui_main.setTheme(gui_main._theme_from_mode(cfg.theme_mode))
    window = gui_main.MainWindow(cfg, tmp_path / "settings.json")
    # QWidget.grab cannot capture the compositor's Mica backing consistently.
    # Disable it in this isolated preview only; production GUI settings stay as-is.
    window.setMicaEffectEnabled(False)
    output = EVIDENCE
    def paint():
        loop = QEventLoop(); QTimer.singleShot(250, loop.quit); loop.exec()
    try:
        window.show(); window.switchTo(window.overlay_page); paint()
        page = window.overlay_page
        page.setting_widgets["columns"]["damage"].click()
        page.setting_widgets["theme"].setCurrentIndex(1)
        entry = window._selected_overlay()
        assert "damage" not in entry.visible_columns and entry.overlay_theme == "dark"
        encoded = gui_config._overlay_entry_to_dict(entry)
        assert gui_config._overlay_entry_from_dict(encoded) == entry
        assert window.grab().save(str(output / "gui-overlay-settings.png"))
        window.switchTo(window.records_page); paint()
        assert window.records_page.load_overlay_btn.isEnabled()
        window.overlay_manager.apply_analysis_snapshot(snapshot_message())
        window.records_page.load_overlay_btn.click()
        loop = QEventLoop()
        poll = QTimer(); poll.setInterval(50)
        poll.timeout.connect(lambda: loop.quit() if window.overlay_manager._history_mode else None)
        poll.start(); QTimer.singleShot(15000, loop.quit); loop.exec(); poll.stop()
        assert window.overlay_manager._history_mode
        assert window.overlay_manager._analysis_snapshot["snapshot"]["battle"]["total_damage"] == 300
        paint()
        assert window.grab().save(str(output / "gui-history-loaded.png"))
        window.records_page.return_live_btn.click()
        assert not window.overlay_manager._history_mode
        assert window.overlay_manager._analysis_snapshot["snapshot"]["battle"]["total_damage"] == 760
        paint()
        assert window.grab().save(str(output / "gui-history-live.png"))
        assert not hasattr(window.records_page, 'export_upload_btn')
    finally:
        window.close(); app.processEvents()
