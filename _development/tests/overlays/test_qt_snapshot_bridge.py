"""Qt receives canonical state on its own thread and replays it on page load."""
from app_test_support.ui.qt import EVIDENCE, page_value, read_dom, snapshot_message, wait_for_page
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QEventLoop, QTimer
import endfield_pcap.gui.main as gui_main
import endfield_pcap.overlays.manager as overlay_host
import endfield_pcap.gui.config as gui_config
from endfield_pcap.models import OverlayEntry
from endfield_pcap.models import OverlayGeometry
from endfield_pcap.models import OverlaySourceType
from app_test_support.scenarios.combo import publisher, scene, trigger
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.overlays.templates import with_template_value


def visual_message(sequence=1, valid=True):
    return dict(type='combo_snapshot', schema_version=2, stream_id='visual-test', sequence=sequence,
                snapshot=dict(frame_valid=valid,status='识别中',slots=[
                    dict(slot=0,status='cooldown',progress=.5,estimated_remaining_ms=10000,
                         character_key='chr_0016_laevat',display_name='弭弗'),
                    dict(slot=1,status='ready',progress=1),
                    dict(slot=2,status='unknown',progress=None),
                    dict(slot=3,status='unknown',progress=None)]))


@pytest.mark.parametrize('theme', ['light', 'dark', 'transparent'])
def test_portraits_scale_toggle_reuse_nodes_and_change_team_without_stale_images(app, theme):
    current = OverlayEntry('avatars', 'damage', OverlaySourceType.BUILTIN, 'damage', True, False, False,
        overlay_theme=theme, geometry=OverlayGeometry(0, 0, 600, 400))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=current, ws_port=1, min_width=600, use_in_process_snapshots=True))
    frame = snapshot_message()
    try:
        window.apply_analysis_snapshot(frame)
        wait_for_page(window, window.show)
        from PySide6.QtTest import QTest
        QTest.qWait(250)
        wait_for(lambda: page_value(window, '''[...document.querySelectorAll('.character-avatar')].every(i=>i.complete && i.naturalWidth===128)'''), app)
        assert page_value(window, "document.querySelectorAll('.character-avatar:not([hidden])').length") == 2
        baseline = page_value(window, "getComputedStyle(document.querySelector('.character-avatar')).width")
        reference = page_value(window, 'window.endfieldOverlay.contentReference')
        assert float(baseline[:-2]) == pytest.approx(32*min(window.width()/reference['width'], window.height()/reference['height']), abs=.1)
        window.apply_entry(replace(current, font_scale=1.5))
        QTest.qWait(250)
        def normalized_avatar_size():
            return page_value(window, "parseFloat(getComputedStyle(document.querySelector('.character-avatar')).width) / Number(getComputedStyle(document.documentElement).getPropertyValue('--overlay-window-scale'))")
        assert normalized_avatar_size() == pytest.approx(32, abs=.1)
        current = with_template_value(replace(current, font_scale=1.5), 'avatar_size_percent', 150)
        window.apply_entry(current)
        QTest.qWait(250)
        assert normalized_avatar_size() == pytest.approx(48, abs=.1)
        assert page_value(window, "document.querySelector('.row').clientHeight >= document.querySelector('.character-avatar').clientHeight")
        window.resize(800, 500)
        from PySide6.QtTest import QTest
        QTest.qWait(150)
        reference = page_value(window, 'window.endfieldOverlay.contentReference')
        assert float(page_value(window, "getComputedStyle(document.querySelector('.character-avatar')).width")[:-2]) == pytest.approx(48*min(800/reference['width'], 500/reference['height']), abs=.1)
        window.resize(round(reference['width']*window.content_size.scale), round(reference['height']*window.content_size.scale))
        QTest.qWait(150)
        current_scale = min(window.width()/reference['width'], window.height()/reference['height'])
        assert float(page_value(window, "getComputedStyle(document.querySelector('.character-avatar')).width")[:-2]) == pytest.approx(48*current_scale, abs=.1)
        from PySide6.QtTest import QTest
        QTest.qWait(200)  # Wait for Chromium's compositor, not only image decoding.
        window.grab().save(str(EVIDENCE/f'avatars-overlay-{theme}-150.png'))
        page_value(window, "(()=>{window.avatarNode=document.querySelector('.character-avatar');window.avatarRequests=performance.getEntriesByType('resource').filter(r=>r.initiatorType==='img').length;return true;})()")
        stats = {}
        for enabled in ('on', 'off'):
            window.apply_entry(with_template_value(current, 'show_character_avatars', enabled))
            stats[enabled] = page_value(window, '''(()=>{
                const frame='''+json.dumps(dict(frame, sequence=1 if enabled == 'on' else 201))+''';const start=performance.now();
                for(let i=0;i<200;i++){frame.sequence+=1;window.dispatchEvent(new CustomEvent('endfield-analysis-snapshot',{detail:frame}));}
                return {updates:200,total_ms:performance.now()-start,
                    same_node:window.avatarNode===document.querySelector('.character-avatar'),
                    extra_requests:performance.getEntriesByType('resource').filter(r=>r.initiatorType==='img').length-window.avatarRequests};})()''')
            assert stats[enabled]['same_node'] and stats[enabled]['extra_requests'] == 0
        (EVIDENCE/f'avatar-render-{theme}.json').write_text(json.dumps(stats, indent=2), encoding='utf8')
        assert page_value(window, "document.querySelector('.character-avatar').hidden")
        window.apply_entry(current)
        changed = snapshot_message(500)
        changed['snapshot']['participants'] = [dict(character_key='chr_0003_endminf', character_name='管理员', total_damage=1)]
        window.apply_analysis_snapshot(changed)
        assert 'chr_0003_endminf.png' in page_value(window, "document.querySelector('.character-avatar').src")
        assert page_value(window, "document.querySelectorAll('.row').length") == 1
        window.apply_analysis_snapshot(dict(changed, sequence=501, snapshot=None))
        assert page_value(window, "document.querySelectorAll('.character-avatar').length") == 0
    finally:
        window.close(); app.processEvents()

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
    monkeypatch.setattr("endfield_pcap.gui.service.DamageLogService", Service)
    controller = gui_main.ServiceController(SimpleNamespace())
    controller.start()
    controller.join()
    received = []
    window = SimpleNamespace(
        service_controller=controller,
        overlay_manager=SimpleNamespace(apply_analysis_summary=lambda payload, *, take_ownership: received.append(payload)),
        _update_service_status=lambda: None,
        _finish_service_stop=lambda: None,
        _drain_independent_services=lambda: None,
        input_controller=SimpleNamespace(set_trace=lambda path: None),
        vision_controller=SimpleNamespace(set_identity=lambda members, session: None),
    )
    gui_main.MainWindow._drain_queue(window)
    assert received == [message]
    assert controller.queue.empty()


def test_damage_window_scale_survives_saved_config_and_reopen(app):
    from PySide6.QtTest import QTest
    current = OverlayEntry('fit-reopen', 'damage', OverlaySourceType.BUILTIN, 'damage', True, False, False,
        font_scale=1.5)
    current = with_template_value(current, 'avatar_size_percent', 180)
    manager = overlay_host.OverlayManager(1, use_in_process_snapshots=True)
    manager.apply_analysis_snapshot(snapshot_message())
    try:
        sizes = []
        for _ in range(3):
            manager.apply_entry(current)
            window = manager._windows[current.id]
            wait_for_page(window, lambda: None)
            QTest.qWait(250)
            sizes.append((window.width(), window.height()))
            stored = gui_config._overlay_entry_to_dict(manager._entries[current.id])
            current = gui_config._overlay_entry_from_dict(stored)
            assert current.template_settings['_damage_window_scale'] > 0
            manager.apply_entry(replace(current, enabled=False))
            app.processEvents()
        assert sizes[0] == sizes[1] == sizes[2]
    finally:
        manager.close_all(); app.processEvents()

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

def test_actual_qt_combo_page_replays_four_slots_on_load_reload_and_reset(app):
    entry = OverlayEntry(id="combo-smoke", name="连携 CD", source_type=OverlaySourceType.BUILTIN,
                         source_value="combo_skill", enabled=True, locked=True, click_through=False)
    config = overlay_host.OverlayWindowConfig(entry=entry, ws_port=1, default_width=300,
                                             min_width=180, min_height=1, default_height=200,
                                             use_in_process_snapshots=True)
    window = overlay_host.OverlayWindow(config)
    try:
        message = visual_message()
        window.apply_combo_snapshot(message)
        wait_for_page(window, window.show)
        assert window.webview.url().path().endswith("combo/index.html")
        expression = "Array.from(document.querySelectorAll('.slot .value'), node => node.textContent)"
        assert page_value(window, expression) == ['50% · ≈10.0s', 'CD 就绪', '—', '—']
        window.apply_combo_snapshot(message)
        wait_for_page(window, window.webview.reload)
        assert page_value(window, expression) == ['50% · ≈10.0s', 'CD 就绪', '—', '—']
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
        held=visual_message(2)
        held['snapshot']['frame_valid']=False
        held['snapshot']['slots'][1].update(held=True,stale=True)
        window.apply_combo_snapshot(held)
        assert page_value(window, "document.querySelectorAll('.slot')[1].dataset.status")=='ready'
        color=page_value(window, "getComputedStyle(document.querySelectorAll('.slot')[1]).backgroundColor")
        assert color.startswith('rgba(21, 150, 83, ') and float(color.rsplit(', ',1)[1].rstrip(')'))>.8
        window.apply_combo_snapshot(visual_message(3, valid=False))
        assert page_value(window, expression)[:2] == ['50% · ≈10.0s', 'CD 就绪']
        reset=visual_message(0,valid=False)
        reset['stream_id']='new-target'
        reset['snapshot']['slots']=[]
        window.apply_combo_snapshot(reset)
        assert page_value(window, expression) == ['—'] * 4
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
            reference = page_value(window, 'window.endfieldOverlay.contentReference')
            window_scale = min(dimensions['width']/reference['width'], dimensions['height']/reference['height'])
            assert dimensions["cells"] == 4 and abs(dimensions["headerSize"] - 36 * font_scale * window_scale) < .1
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

def test_damage_column_fit_tracks_content_and_footer_has_no_empty_body(app):
    from PySide6.QtTest import QTest
    current = OverlayEntry('content-fit', 'damage', OverlaySourceType.BUILTIN, 'damage', True, False, False,
        overlay_theme='dark', geometry=OverlayGeometry(0, 0, 800, 380))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=current, ws_port=1, **overlay_host._window_defaults(current), use_in_process_snapshots=True))
    message = snapshot_message()
    message['snapshot']['participants'] *= 2
    for i, participant in enumerate(message['snapshot']['participants']):
        message['snapshot']['participants'][i] = dict(participant, character_key=f'chr_fixture_{i}')
    try:
        window.apply_analysis_snapshot(message)
        wait_for_page(window, window.show)
        from PySide6.QtTest import QTest
        QTest.qWait(250)
        evidence = []
        for count in [4, 3, 2, 1, 0, 4]:
            selected = list(current.visible_columns)[:count]
            window.apply_entry(with_template_value(current, 'columns', selected))
            QTest.qWait(250)
            state = page_value(window, '''(()=>{
                const body=document.querySelector('.table-body'),row=document.querySelector('.row:last-child');
                const footer=document.querySelector('.overlay-footer'),card=document.querySelector('.overlay-card');
                return {reference:window.endfieldOverlay.contentReference, viewport:[innerWidth,innerHeight],
                    scale:Number(getComputedStyle(document.documentElement).getPropertyValue('--overlay-window-scale')),
                    gap:footer.getBoundingClientRect().top-row.getBoundingClientRect().bottom,
                    padding:parseFloat(getComputedStyle(body).paddingBottom),
                    borderGap:card.getBoundingClientRect().bottom-footer.getBoundingClientRect().bottom,
                    border:parseFloat(getComputedStyle(card).borderBottomWidth),
                    cardBottom:card.getBoundingClientRect().bottom,
                    tracks:getComputedStyle(document.querySelector('.row')).gridTemplateColumns.split(' ').map(parseFloat),
                    fits:[...document.querySelectorAll('.row-stat:not([hidden]), .table-label')].every(node=>node.scrollWidth<=node.clientWidth+1),
                    font:parseFloat(getComputedStyle(document.querySelector('.metric-value')).fontSize)};
            })()''')
            assert state['reference']['width'] >= 320
            assert state['scale'] == pytest.approx(min(state['viewport'][0]/state['reference']['width'], state['viewport'][1]/state['reference']['height'])), dict(count=count, native=[window.width(),window.height()], **state)
            assert -.1 <= state['gap'] <= state['padding']+.1, state
            assert state['borderGap'] == pytest.approx(state['border'], abs=.1)
            assert state['font'] == pytest.approx(36*state['scale'], abs=.1)
            assert state['fits'], state
            # Fixed content tracks must not absorb spare viewport space.
            base_tracks = page_value(window, "document.documentElement.style.getPropertyValue('--table-columns')")
            assert 'fr' not in base_tracks
            assert state['tracks'][0]/state['scale'] < 200, state
            evidence.append(dict(columns=count, native_width=window.width(), **state))
            if count in (4, 2):
                window.grab().save(str(EVIDENCE/f'damage-content-fit-{count}-columns.png'))
        assert evidence[0]['reference'] == evidence[-1]['reference']
        assert evidence[0]['reference']['width'] > evidence[-2]['reference']['width']
        assert evidence[0]['native_width'] > evidence[2]['native_width'] > evidence[-2]['native_width']
        assert evidence[0]['native_width'] == evidence[-1]['native_width']
        assert evidence[0]['cardBottom'] <= window.height()+.1
        base_width = window.width()
        base_columns = evidence[-1]['tracks']
        for participant in message['snapshot']['participants']:
            participant.update(character_name='角色名称', total_damage=100000000, total_rd=100000000)
        message['snapshot']['battle']['total_damage'] = 400000000
        message['sequence'] += 1
        window.apply_analysis_snapshot(message)
        QTest.qWait(250)
        assert window.width() == base_width  # Four characters and 100.00M fit the default floor.
        message['snapshot']['participants'][0].update(character_name='角色名称加长验证', total_damage=1000000000000000)
        message['sequence'] += 1
        window.apply_analysis_snapshot(message)
        QTest.qWait(250)
        assert window.width() > base_width
        expanded = page_value(window, "getComputedStyle(document.querySelector('.row')).gridTemplateColumns.split(' ').map(parseFloat)")
        assert expanded[0] > base_columns[0] and expanded[1] > base_columns[1]
        width_after_expansion = window.width()
        message['sequence'] += 1
        window.apply_analysis_snapshot(message)
        QTest.qWait(100)
        assert window.width() == width_after_expansion  # Repeated snapshots cannot compound window size.
        original_height = evidence[0]['reference']['height']
        message['snapshot']['participants'] = message['snapshot']['participants'][:1]
        message['sequence'] += 1
        window.apply_analysis_snapshot(message)
        assert page_value(window, 'window.endfieldOverlay.contentReference.height') < original_height
        (EVIDENCE/'damage-content-fit.json').write_text(json.dumps(evidence, indent=2), encoding='utf8')
    finally:
        window.close(); app.processEvents()


def test_damage_empty_table_fits_waiting_text_and_resizes_back_from_rows(app):
    from PySide6.QtTest import QTest
    current = OverlayEntry('empty-fit', 'damage', OverlaySourceType.BUILTIN, 'damage', True, False, False,
        overlay_theme='dark', geometry=OverlayGeometry(0, 0, 800, 380))
    window = overlay_host.OverlayWindow(overlay_host.OverlayWindowConfig(
        entry=current, ws_port=1, **overlay_host._window_defaults(current), use_in_process_snapshots=True))
    frame=snapshot_message()
    try:
        wait_for_page(window,window.show)
        evidence=[]
        for participants in ([],frame['snapshot']['participants'],[]):
            frame['sequence']+=1
            frame['snapshot']['participants']=participants
            window.apply_analysis_snapshot(frame)
            QTest.qWait(200)
            state=page_value(window,'''(()=>{
                const rect=node=>{const r=node.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,width:r.width}};
                return {reference:window.endfieldOverlay.contentReference,viewport:[innerWidth,innerHeight],
                    card:rect(document.querySelector('.overlay-card')),footer:rect(document.querySelector('.overlay-footer')),
                    body:rect(document.querySelector('.table-body')),empty:rect(document.getElementById('emptyState')),
                    emptyHidden:document.getElementById('emptyState').classList.contains('hidden'),
                    shellPadding:parseFloat(getComputedStyle(document.querySelector('.overlay-shell')).paddingBottom)};
            })()''')
            if not participants:
                assert not state['emptyHidden']
                assert state['empty']['bottom']<=state['footer']['top']+.1,state
                assert state['empty']['height']>15,state
                assert abs(state['card']['bottom']+state['shellPadding']-state['viewport'][1])<2,state
            evidence.append(state)
        (EVIDENCE/'damage-empty-fit.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
        assert evidence[0]['reference']==evidence[-1]['reference']
        assert evidence[0]['reference']['width']==evidence[1]['reference']['width']
        assert evidence[1]['reference']['height']>evidence[0]['reference']['height']
        window.grab().save(str(EVIDENCE/'damage-empty-state.png'))
    finally:
        window.close();app.processEvents()


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
        reference = page_value(window, 'window.endfieldOverlay.contentReference')
        assert min(dimensions["headers"]) == pytest.approx(19*min(window.width()/reference['width'], window.height()/reference['height']), abs=.1)
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
            assert page_value(window, "document.querySelectorAll('.row')[0].querySelectorAll('.row-stat:not([hidden])').length") == len(selected)
            assert page_value(window, "document.querySelectorAll('.table-label').length") == 1 + len(selected)
        selected = ("damage_rate", "rdamage_rate")
        window.apply_entry(replace(entry, visible_columns=selected))
        wait_for_page(window, window.webview.reload)
        assert page_value(window, "document.querySelectorAll('.row')[0].querySelectorAll('.row-stat:not([hidden])').length") == 2
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
        window.apply_combo_snapshot(visual_message())
        wait_for_page(window, window.show)
        assert page_value(window, "document.documentElement.dataset.theme") == theme
        assert page_value(window, "document.querySelector('.slot .name').textContent") == "弭弗"
        loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
        output = EVIDENCE
        assert window.grab().save(str(output / f"combo-{theme}.png"))
    finally:
        window.close(); app.processEvents()

def test_gui_columns_theme_history_load_and_return_live_with_actual_widgets(app, monkeypatch, tmp_path):
    from app_test_support.scenarios.raw import raw_scene, raw_hit
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
