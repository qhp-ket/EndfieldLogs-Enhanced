"""History evidence is displayed without inventing states or reallocating rD."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QRect, QSize, QPoint
from PySide6.QtTest import QTest
from qfluentwidgets import Theme, setTheme
from endfield_pcap.analysis.battle.detail import timeline_blocks
from endfield_pcap.analysis.battle.enemy import enemy_observations
from endfield_pcap.analysis.battle.enemy import hit_resistance
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.gui.shared.placement import centered_frame
from endfield_pcap.gui.shared.placement import place_initial_window
from app_test_support.ui.window import main_window
from app_test_support.ui.qt import snapshot_message, EVIDENCE


@pytest.mark.parametrize('bounds,size', [
    (QRect(-1920, 40, 1920, 1040), QSize(1200, 800)),
    (QRect(1920, -180, 1280, 720), QSize(2000, 1500)),
    (QRect(-400, -200, 400, 260), QSize(720, 480)),
    (QRect(0, 0, 1, 1), QSize(1200, 800)),
])
def test_frame_centering_handles_negative_origins_and_small_work_areas(bounds, size):
    frame = centered_frame(bounds, size)
    assert bounds.contains(frame)
    assert (frame.center()-bounds.center()).manhattanLength() <= 2


def event(actor='101', stamp=1000, poise=20):
    return {'event_type': 'damage', 'lane_type': 'skill', 'ts_ms_from_start': stamp,
            'source_character_key': 'chr_0004_pelica', 'target_character_key': 'eny_test',
            'target_actor_id': actor, 'event_key': 'chr_0004_pelica_combo_skill',
            'value': 120, 'rdps_basis_value': 120, 'event_group_key': 'one-cast',
            'damage_element': 'fire', 'packet_attr_conflict': False,
            'poise_damage': {'current_value': poise, 'value': -5, 'source': 'skill'}}


def test_hit_resistance_keeps_unknown_zero_conflict_and_entity_snapshot_distinct():
    e = event()
    e['target_entity'] = {'target_resistance_points': {'fire': 0}}
    assert hit_resistance(e) is None, 'Entity snapshot is not hit-time evidence'
    for tokens, expected in [(['98:0,0'], 0), (['98:-38.6419'], -38.6419),
                             (['98:10,20'], None), (['98:nan'], None),
                             (['98:0,bad'], None), (['97:10'], None)]:
        e['packet_attr_details'] = {'defender': tokens}
        assert hit_resistance(e) == expected
    e['packet_attr_details'] = {'defender': ['98:0']}
    e['packet_attr_conflict'] = True
    assert hit_resistance(e) is None
    e.pop('packet_attr_conflict')
    assert hit_resistance(e) is None, 'Old cached snapshots lack the conflict flag'


def test_poise_samples_isolate_instances_and_flag_ambiguous_pairing():
    a, b, c = event(), event('102', 2000, 50), event('101', 3000, 0)
    unknown = event('103', 4000, None)
    snap = {'timeline_events': [a, deepcopy(a), b, c, unknown]}
    before = deepcopy(snap)
    tracks, observations = enemy_observations(snap)
    assert [p['value'] for p in tracks[0]['samples']] == [20, 0]
    assert [p['value'] for p in tracks[1]['samples']] == [50]
    assert tracks[2]['samples'] == [] and tracks[2]['peak'] is None
    assert not observations
    assert before == snap
    tracks, _ = enemy_observations({'timeline_events': [event(), event('102')]})
    assert not tracks[0]['samples'] and not tracks[1]['samples']
    assert tracks[2]['key'] == ('', 'unbound')
    assert tracks[2]['samples'][0]['ambiguous']


def test_block_contribution_uses_final_canonical_values_including_ink_and_missing_allocations():
    a, b, missing = event(), event(stamp=2000), event(stamp=3000)
    a['rdps_contributions'] = [{'character_key': 'chr_0036_jsspsi', 'value': 41.2},
                               {'character_key': 'chr_0035_liino', 'value': 78.8}]
    b['rdps_contributions'] = [{'character_key': 'chr_0036_jsspsi', 'value': 120}]
    snap = {'participants': [{'character_key': 'chr_0004_pelica'}], 'timeline_events': [a, b, missing]}
    before = deepcopy(snap)
    block = timeline_blocks(snap)[0]
    summary = block.contribution_summary()
    assert summary['damage'] == summary['basis'] == 360
    assert summary['allocated'] == 240
    assert summary['covered'] == 2 and summary['hits'] == 3
    assert [(c['key'], c['value']) for c in summary['contributions']] == [('chr_0036_jsspsi', 161.2), ('chr_0035_liino', 78.8)]
    assert sum(c['percent'] for c in summary['contributions']) == pytest.approx(100)
    assert snap == before
    missing.pop('rdps_basis_value')
    assert timeline_blocks(snap)[0].contribution_summary()['basis'] is None
    assert '未知（部分命中缺失基数）' in timeline_blocks(snap)[0].description()


def test_initial_dialog_frame_fits_after_layout_long_filename_and_theme(app):
    dialog = BattleDetailDialog(snapshot_message()['snapshot'], 'trace_' + 'very_long_filename_' * 30 + '.log')
    try:
        dialog.show()
        QTest.qWait(160)
        available = dialog.screen().availableGeometry()
        assert available.contains(dialog.frameGeometry())
        assert (dialog.frameGeometry().center()-available.center()).manhattanLength() <= 3
        for theme in (Theme.DARK, Theme.LIGHT):
            setTheme(theme)
            for tab in range(dialog.tabs.count()):
                dialog.tabs.setCurrentIndex(tab)
                QTest.qWait(20)
                assert available.contains(dialog.frameGeometry())
        position = dialog.pos()+QPoint(7, 3)
        dialog.move(position)
        dialog.hide(); dialog.show(); QTest.qWait(100)
        assert dialog.pos() == position, 'Do not recenter subsequent shows'
    finally:
        dialog.close(); app.processEvents()


def test_main_gui_initial_frame_is_centered_and_on_monitor(main_window, app):
    QTest.qWait(160)
    available = main_window.screen().availableGeometry()
    assert available.contains(main_window.frameGeometry())
    assert (main_window.frameGeometry().center()-available.center()).manhattanLength() <= 3
    assert main_window.grab().save(str(EVIDENCE / 'gui-centered.png'))


def test_native_dialog_can_shrink_to_smaller_work_area(app):
    dialog = BattleDetailDialog(snapshot_message()['snapshot'], 'small work area')
    try:
        dialog.show(); QTest.qWait(120)
        bounds = QRect(80, 40, 810, 580)
        place_initial_window(dialog, screen=SimpleNamespace(availableGeometry=lambda: bounds))
        app.processEvents()
        assert bounds.contains(dialog.frameGeometry())
    finally:
        dialog.close(); app.processEvents()


def test_large_scene_scrolls_inside_timeline_and_keeps_inspector_visible(app):
    snapshot = snapshot_message()['snapshot']
    source = next(e for e in snapshot['timeline_events'] if e.get('event_type') == 'damage')
    snapshot['timeline_events'] = [{**source, 'event_group_key': f'group-{i}', 'duration_ms': 2000} for i in range(90)]
    dialog = BattleDetailDialog(snapshot, 'many overlapping skills')
    try:
        dialog.show(); QTest.qWait(180)
        # The compact header gives the default collapsed tracks more room.
        # Expand overlapping tracks to exercise scrolling a genuinely tall scene.
        for key in list(dialog.timeline.skill_lane_rows):
            dialog.timeline.toggle_lane(key)
        app.processEvents()
        assert dialog.timeline.verticalScrollBar().maximum() > 0
        body = dialog.body_scroll.widget()
        if dialog.body_scroll.viewport().height() >= body.minimumSizeHint().height():
            assert dialog.body_scroll.verticalScrollBar().maximum() == 0
            assert dialog.inspector.mapTo(body, dialog.inspector.rect().bottomRight()).y() < body.height()
        assert dialog.screen().availableGeometry().contains(dialog.frameGeometry())
    finally:
        dialog.close(); app.processEvents()


def test_inspector_enemy_tables_and_timeline_markers_use_existing_evidence(app):
    snapshot = snapshot_message()['snapshot']
    hit = next(e for e in snapshot['timeline_events'] if e.get('event_type') == 'damage')
    hit.update(target_actor_id='3001', target_entity={
        'target_resistance_points': {'physical': 20, 'fire': 0},
        'target_resistance_points_source': 'ENTITY_STATS.attr94_99',
        'target_stats_snapshot_ts_ms': 36000000, 'target_stats_snapshot_line_no': 2})
    hit['poise_damage'] = {'current_value': 0, 'value': -10, 'source': 'skill'}
    hit['damage_element'] = 'fire'
    hit['packet_attr_details'] = {'defender': ['98:-20']}
    dialog = BattleDetailDialog(snapshot, '敌人证据与贡献测试')
    try:
        dialog.show(); QTest.qWait(150)
        block = next(b for b in dialog.timeline._blocks if b.lane == 'skill')
        dialog.timeline._activate(block)
        assert dialog.event_detail.toPlainText() == block.description()
        assert dialog.inspector.contributions.rowCount() == 2
        assert dialog.inspector.hits.rowCount() == len(block.events)
        assert '灼热 -20.00' == dialog.inspector.hits.item(0, 5).text()
        assert dialog.inspector.hits.item(0, 6).text() == '0.00'
        assert dialog.enemy_page.stats.item(0, 3).text() == '20.00'
        assert dialog.enemy_page.stats.item(0, 4).text() == '未知'
        assert dialog.enemy_page.stats.item(0, 7).text() == '0.00'
        assert dialog.timeline.hit_markers == 6
        dialog.zoom_slider.setValue(600)
        dialog.timeline.horizontalScrollBar().setValue(200)
        assert dialog.timeline.horizontalScrollBar().value() > 0
        assert dialog.grab().save(str(EVIDENCE / 'battle-timeline-scrolled.png'))
    finally:
        dialog.close(); app.processEvents()
