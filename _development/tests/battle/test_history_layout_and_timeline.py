"""History readability and explicit trace evidence, independent of combat math."""
from app_test_support.paths import ROOT
from copy import deepcopy
from PySide6.QtCore import QPoint
from PySide6.QtTest import QTest
from endfield_pcap.analysis.battle.detail import timeline_blocks
from endfield_pcap.analysis.battle.buffs.states import buff_tracks
from endfield_pcap.analysis.battle.energy import energy_tracks
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.gui.pages.history.view import BattleLogPage
from endfield_pcap.gui.shared.typography import apply_fonts
from app_test_support.scenarios.buffs import buff
from app_test_support.ui.qt import EVIDENCE


def test_casts_keep_distinct_start_end_and_hits_without_simulating_animation():
    owner = 'chr_0004_pelica'
    normal, combo = owner+'_normal_skill', owner+'_combo_skill'
    snapshot = {'participants': [{'character_key': owner}], 'casts': [
        dict(character_key=owner, skill_key=normal, ts_ms_from_start=-100, end_ms_from_start=700),
        dict(character_key=owner, skill_key=combo, ts_ms_from_start=300, end_ms_from_start=800)],
        'timeline_events': [dict(lane_type='skill', event_type='damage', source_character_key=owner,
            event_key=skill, ts_ms_from_start=500, actual_start_ms_from_start=start,
            actual_end_ms_from_start=end, event_group_key=skill, value=value)
            for skill, start, end, value in [(normal, -100, 700, 100), (combo, 300, 800, 200)]]}
    before = deepcopy(snapshot)
    blocks = timeline_blocks(snapshot)
    assert [(b.start_ms, b.end_ms) for b in blocks] == [(-100, 700), (300, 800)]
    assert [b.contribution_summary()['damage'] for b in blocks] == [100, 200]
    assert all('不代表按键或完整动画' in b.description() for b in blocks)
    assert snapshot == before


def test_timeline_hides_normal_attacks_keeps_heavy_and_unknown_end_is_point():
    owner = 'chr_0004_pelica'
    casts = [dict(character_key=owner, skill_key=owner+suffix, ts_ms_from_start=i*100,
                  end_ms_from_start=None, recovers_energy=recover)
             for i, (suffix, recover) in enumerate([('_attack1', False), ('_attack4', True),
                ('_power_attack', False), ('_normal_skill', False), ('_combo_skill', False)])]
    blocks = timeline_blocks({'participants': [{'character_key': owner}], 'casts': casts})
    assert [b.category for b in blocks] == ['重击', '重击', '战技', '连携']
    assert all(b.start_ms == b.end_ms for b in blocks)
    assert all('结束未知' in b.description() for b in blocks)


def test_atb_projection_values_and_missing_values_are_not_reconstructed():
    from pathlib import Path
    from parser_core.unified import parse_overlay_battle_snapshot_text
    text = (ROOT / '_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log').read_text(encoding='utf8')
    text += '\n[10:00:01.100] ATB_UPDATE owner=chr_0004_pelica ownerId=1001 tick=500 reason=AddValue atb=2 delta=1 recoverySpeed=0 source=chr_0004_pelica_attack4\n'
    text += '[10:00:01.200] ATB_UPDATE owner=chr_0004_pelica ownerId=1001 reason=unknown atb=unknown delta=unknown\n'
    snapshot = parse_overlay_battle_snapshot_text(text)
    assert len(snapshot['atb_events']) == 2
    samples = energy_tracks(snapshot)[0]['samples']
    assert len(samples) == 1 and samples[0]['value'] == 2 and samples[0]['delta'] == 1
    assert samples[0]['recovery_speed'] == 0 and samples[0]['client_tick_ms'] == 500
    assert snapshot['battle']['total_damage'] == 760
    assert energy_tracks({}) == []


def test_contiguous_buff_updates_are_one_episode_and_true_gaps_remain():
    contiguous = [buff(0, 1000, policy='Stack'), buff(1000, 2000, 'b', 'Stack')]
    assert len(list(buff_tracks(contiguous))) == 1
    assert len(list(buff_tracks([contiguous[0], {**contiguous[1], 'ts_ms_from_start': 1001, 'duration_ms': 999}]))) == 2


def test_blue_markers_only_follow_stack_changes_not_duration_refresh(app):
    snapshot = {'participants': [{'character_key': 'target'}], 'timeline_events': [
        buff(0, 10000, 'a', 'Stack'), buff(2000, 10000, 'b', 'Stack'),
        buff(3000, 10000, 'b', 'Stack')]}
    dialog = BattleDetailDialog(snapshot, '蓝色层数变化点')
    try:
        dialog.buff_check.setChecked(True)
        assert dialog.timeline.buff_change_markers == 2  # 0→1, 1→2; refreshing b adds no point.
        dialog.show(); QTest.qWait(80)
        assert dialog.grab().save(str(EVIDENCE / 'timeline-buff-blue-points.png'))
    finally:
        dialog.close(); app.processEvents()


def test_history_cards_order_and_outer_scroll_at_large_font(app):
    page = BattleLogPage()
    try:
        page.resize(1050, 650)
        apply_fonts(page, 1.6)
        page.show(); QTest.qWait(120)
        y = lambda w: w.mapTo(page.container, QPoint()).y()
        assert abs(y(page.metrics_card)-y(page.ranking_card)) < 3
        assert y(page.actions_card) > y(page.metrics_card)
        assert abs(y(page.actions_card)-y(page.list_card)) < 3
        assert page.actions_card.mapTo(page.container, QPoint()).x() < page.list_card.mapTo(page.container, QPoint()).x()
        assert page.verticalScrollBar().maximum() > 0
        assert page.record_list.height() >= 400
        page.grab().save(str(EVIDENCE / 'history-layout-top.png'))
        page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
        QTest.qWait(60)
        page.grab().save(str(EVIDENCE / 'history-layout-bottom.png'))
    finally:
        page.close(); app.processEvents()
