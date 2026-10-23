"""Parity and real WebEngine interactions for the optional local analysis UI."""
from copy import deepcopy
import json
import time

import pytest
from PySide6.QtTest import QTest
from qfluentwidgets import Theme, setTheme

from endfield_pcap.battle_detail import timeline_blocks, skill_rows
from endfield_pcap.battle_web_data import WebBattleModel
from endfield_pcap.gui_battle_detail import BattleDetailDialog
from endfield_pcap.gui_config import AppConfig, default_service_config, load_app_config, save_app_config
from test_battle_analysis_compact import sample
from test_team_energy_and_type_lanes import resource_snapshot
from test_qt_snapshot_bridge import EVIDENCE


def evidence_snapshot():
    snapshot = sample()
    snapshot['atb_events'] = resource_snapshot()['atb_events']
    snapshot['timeline_events'][0].update(rdps_basis_value=100,
        rdps_contributions=[dict(character_key='chr_0005_chen', value=25),
                            dict(character_key='chr_0004_pelica', value=75)])
    return snapshot


def wait(app, condition, seconds=15):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return
        QTest.qWait(20)
    raise AssertionError('Web analysis condition timed out')


def js(app, view, source):
    result = []
    view.page.runJavaScript(source, lambda value: result.append(value))
    wait(app, lambda: bool(result))
    return result[0]


def open_web(app, snapshot, label='本地战斗分析'):
    dialog = BattleDetailDialog(snapshot, label)
    dialog.show()
    dialog.view_mode_combo.setCurrentIndex(1)
    view = dialog.web_analysis
    wait(app, lambda: view.bridge.ready or bool(view.page.console_errors))
    assert not view.page.console_errors
    assert js(app, view, 'document.body.dataset.ready') == 'true'
    return dialog, view


def paint_frame(app, view):
    js(app, view, 'window.__testPainted=false;requestAnimationFrame(()=>requestAnimationFrame(()=>window.__testPainted=true))')
    wait(app, lambda: js(app, view, 'window.__testPainted') is True)
    QTest.qWait(100)


@pytest.mark.parametrize('snapshot', [evidence_snapshot(), {}])
def test_web_projection_preserves_native_blocks_evidence_and_quality(snapshot):
    before = deepcopy(snapshot)
    model = WebBattleModel(snapshot, '日志标题')
    data = json.loads(model.json())
    native = timeline_blocks(snapshot)
    assert len(data['blocks']) == len(native)
    assert data['skills'] == skill_rows(snapshot)
    assert data['quality'] == snapshot.get('snapshot_quality', {})
    for block, original in zip(data['blocks'], native):
        assert block['start'] == original.start_ms and block['end'] == original.end_ms
        assert 'events' not in block and 'description' not in block
        detail = json.loads(model.block_details(block['id']))
        assert detail['events'] == original.events
        assert detail['summary'] == original.contribution_summary()
        assert block['states'] == original.buff_states
        for unit in ('seconds', 'frames'):
            assert detail['description'][unit] == original.description(unit)
        assert model.block_details(block['id']) == model.block_details(block['id'])
    assert model.block_details(-1) == model.block_details(len(native)) == '{}'
    assert snapshot == before


def test_web_interactions_units_evidence_hover_and_native_roundtrip(app):
    snapshot = evidence_snapshot()
    before = deepcopy(snapshot)
    dialog, view = open_web(app, snapshot)
    try:
        assert js(app, view, 'document.getElementById("fallback").checked') is False
        assert js(app, view, 'document.getElementById("inspector").open') is False
        js(app, view, 'document.getElementById("toggle-details").click()')
        assert js(app, view, 'document.querySelectorAll(".hit").length') == 2
        assert js(app, view, 'document.querySelectorAll("[data-detail]").length') == 4
        assert '全队技力' in js(app, view, 'document.getElementById("timeline-grid").textContent')
        # All four native inspector pages retain their evidence and original raw rows.
        js(app, view, 'Analysis.inspectBlock(Analysis.data.blocks.find(b=>b.lane==="skill").id); Analysis.detailTab="allocation"; Analysis.renderInspector()')
        wait(app, lambda: '75' in js(app, view, 'document.getElementById("inspector-body").textContent'))
        js(app, view, 'Analysis.detailTab="hits"; Analysis.renderInspector()')
        wait(app, lambda: '本击抗性' in js(app, view, 'document.getElementById("inspector-body").textContent'))
        js(app, view, 'document.querySelector("[data-hit]").click()')
        wait(app, lambda: 'rdps_contributions' in js(app, view, 'document.getElementById("inspector-body").textContent'))
        # Hover requests go over QWebChannel to the same Python evidence model.
        js(app, view, '''(()=>{const chart=document.querySelectorAll('.plot-row.chart')[1],rect=chart.getBoundingClientRect();
            chart.dispatchEvent(new MouseEvent('mousemove',{clientX:rect.left+Analysis.x(525),clientY:rect.top+50,bubbles:true}));})()''')
        wait(app, lambda: '最近观测' in js(app, view, 'document.getElementById("tooltip").textContent'))
        assert '90' in js(app, view, 'document.getElementById("tooltip").textContent')
        stamp = js(app, view, 'document.getElementById("hover-time").textContent')
        assert stamp.startswith('时间 ') and stamp.endswith('s')
        assert abs(float(stamp[3:-1])-.525) < .01  # MouseEvent rounds to screen pixels.
        js(app, view, 'document.getElementById("maximize-details").click()')
        assert js(app, view, 'document.getElementById("inspector").classList.contains("maximized")')
        paint_frame(app, view)
        assert dialog.grab().save(str(EVIDENCE/'battle-analysis-web-details-maximized.png'))
        js(app, view, 'document.getElementById("maximize-details").click()')
        assert not js(app, view, 'document.getElementById("inspector").classList.contains("maximized")')
        js(app, view, '''(()=>{const chart=document.querySelector('.plot-row.chart'),dot=chart.querySelector('circle[data-stamp="1000"]'),rect=dot.getBoundingClientRect();
            dot.dispatchEvent(new MouseEvent('mousemove',{clientX:rect.left,clientY:rect.top,bubbles:true}));})()''')
        wait(app, lambda: '200.00' in js(app, view, 'document.getElementById("tooltip").textContent'))
        assert '实测' in js(app, view, 'document.getElementById("tooltip").textContent')
        assert '恢复速度 8' in js(app, view, 'document.getElementById("tooltip").textContent')
        js(app, view, '''document.getElementById('collapse-details').click();Analysis.inspectBlock(Analysis.data.blocks.find(b=>b.lane==='skill').id)''')
        assert js(app, view, 'document.getElementById("inspector").open') is False
        wait(app, lambda: '展开详情' in js(app, view, 'document.getElementById("toggle-details").textContent'))
        js(app, view, '''document.getElementById('unit').value='frames';document.getElementById('unit').dispatchEvent(new Event('change'));
            document.getElementById('buffs').click(); document.getElementById('graphics').value=125;
            document.getElementById('graphics').dispatchEvent(new Event('input'));''')
        assert js(app, view, 'document.querySelectorAll(".node.buff").length') == 3
        assert js(app, view, 'document.querySelectorAll(".stack-dot").length') > 0
        assert 'F' in js(app, view, 'document.querySelector("[data-ruler]").textContent')
        js(app, view, 'document.querySelector("[data-lane]").click(); Analysis.setCharacter("chr_0005_chen")')
        assert js(app, view, 'document.getElementById("skill-character").value') == 'chr_0005_chen'
        # Character filtering deliberately leaves team energy and enemy data visible.
        assert '全队技力' in js(app, view, 'document.getElementById("timeline-grid").textContent')
        wait(app, lambda: dialog._web_pending_state is not None and dialog._web_pending_state['character']=='chr_0005_chen')
        original_model = view.bridge.model
        dialog.view_mode_combo.setCurrentIndex(0)
        assert dialog.character_combo.currentData() == 'chr_0005_chen'
        assert dialog.buff_check.isChecked() and dialog.graphics_zoom_slider.value() == 125
        assert dialog.time_unit_combo.currentData() == 'frames'
        assert dialog.inspector._block is not None and not dialog.detail_split.details_expanded()
        dialog.view_mode_combo.setCurrentIndex(1)
        assert dialog.web_analysis is view and view.bridge.model is original_model
        assert not view.page.console_errors and snapshot == before
    finally:
        dialog.close(); app.processEvents()


def test_web_tabs_reuse_dom_and_lazy_evidence_without_stale_filters(app):
    dialog, view = open_web(app, evidence_snapshot())
    try:
        paint_frame(app, view)
        assert not view.bridge.model._details
        js(app, view, '''window.savedNode=document.querySelector('.node');window.savedGrid=document.getElementById('timeline-grid').firstChild;
            window.builds=0;const build=Analysis.renderTimeline;Analysis.renderTimeline=function(){window.builds++;return build();};''')
        for _ in range(3):
            for tab in ('skills', 'enemy', 'timeline'):
                js(app, view, f'document.querySelector("[data-tab={tab}]").click()')
                paint_frame(app, view)
        assert js(app, view, 'window.builds') == 0
        assert js(app, view, 'window.savedNode.isConnected && window.savedGrid===document.getElementById("timeline-grid").firstChild')
        # Hidden pages defer work, then render the current filter on demand.
        js(app, view, '''document.querySelector('[data-tab=enemy]').click();Analysis.setCharacter('chr_0005_chen');''')
        assert js(app, view, 'window.builds') == 0
        js(app, view, 'document.querySelector("[data-tab=skills]").click()')
        assert js(app, view, 'Analysis.skillsDirty') is False
        js(app, view, 'document.querySelector("[data-tab=timeline]").click()')
        paint_frame(app, view)
        assert js(app, view, 'window.builds') == 1
        assert js(app, view, 'Array.from(document.querySelectorAll(".node")).every(n=>Analysis.data.blocks[+n.dataset.block].owner==="chr_0005_chen")')
        js(app, view, '''document.getElementById('toggle-details').click();
            Analysis.inspectBlock(Analysis.data.blocks.find(b=>b.lane==='skill').id);
            Analysis.detailTab='raw';Analysis.renderInspector();''')
        wait(app, lambda: 'event_type' in js(app, view, 'document.getElementById("inspector-body").textContent'))
        assert len(view.bridge.model._details) == 1
        assert not view.page.console_errors
    finally:
        dialog.close();app.processEvents()


def test_web_offline_empty_and_untrusted_log_text_remain_text(app):
    label = '<img src=x onerror="window.injected=true"> & 测试'
    dialog, view = open_web(app, {}, label)
    try:
        assert js(app, view, 'document.getElementById("record-name").textContent') == label
        assert not js(app, view, 'Boolean(window.injected || document.querySelector("#record-name img"))')
        assert js(app, view, 'document.querySelectorAll(".hit").length') == 0
        # A log cannot fetch remote resources through this offline profile.
        js(app, view, '''window.remoteLoaded=null; const image=new Image(); image.onload=()=>window.remoteLoaded=true;
            image.onerror=()=>window.remoteLoaded=false;image.src='https://example.com/analysis-test.png';''')
        wait(app, lambda: js(app, view, 'window.remoteLoaded') is False)
        dialog.set_record_label('重命名后的记录')
        wait(app, lambda: js(app, view, 'document.getElementById("record-name").textContent') == '重命名后的记录')
    finally:
        dialog.close(); app.processEvents()


def test_analysis_choice_config_is_backward_compatible(tmp_path):
    path = tmp_path/'settings.json'
    config = AppConfig(service=default_service_config(), battle_analysis_view='web')
    save_app_config(config, path)
    assert load_app_config(path).battle_analysis_view == 'web'
    data = json.loads(path.read_text(encoding='utf-8'))
    data.pop('battle_analysis_view')
    path.write_text(json.dumps(data), encoding='utf-8')
    assert load_app_config(path).battle_analysis_view == 'native'


def test_synthetic_battle_website_style_screenshots_and_full_evidence(app):
    snapshot = evidence_snapshot()
    before = deepcopy(snapshot)
    dialog, view = open_web(app, snapshot, '合成战斗展示')
    try:
        for theme in (Theme.DARK, Theme.LIGHT):
            setTheme(theme);QTest.qWait(150)
            wait(app, lambda: js(app, view, 'document.documentElement.dataset.theme') == theme.value.lower())
            paint_frame(app, view)
            assert dialog.grab().save(str(EVIDENCE/f'battle-analysis-web-{theme.value}.png'))
        js(app, view, 'document.querySelector("[data-tab=skills]").click()');paint_frame(app, view)
        assert dialog.grab().save(str(EVIDENCE/'battle-analysis-web-skills.png'))
        js(app, view, '''document.querySelector('[data-tab=timeline]').click(); document.getElementById('buffs').click();
            const chart=document.querySelector('.plot-row.chart');chart.scrollIntoView({block:'center'});''')
        assert js(app, view, 'document.getElementById("skills").hidden') is True
        paint_frame(app, view)
        assert dialog.grab().save(str(EVIDENCE/'battle-analysis-web-resources.png'))
        assert not view.page.console_errors and snapshot == before
        assert js(app, view, 'Analysis.data.blocks.length') == len(timeline_blocks(snapshot))
    finally:
        dialog.close(); app.processEvents();setTheme(Theme.LIGHT)
