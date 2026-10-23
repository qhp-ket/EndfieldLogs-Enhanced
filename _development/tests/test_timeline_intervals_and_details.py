"""Logged lifecycles, independent hit markers and collapsible evidence panes."""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from endfield_pcap.battle_detail import timeline_blocks
from endfield_pcap.gui_battle_detail import BattleDetailDialog
from endfield_pcap.skill_frame_reference import display_bounds
from endfield_pcap.timeline_time import format_time, ruler_ticks
from test_qt_snapshot_bridge import EVIDENCE


OWNER = 'chr_0004_pelica'
SKILL = OWNER + '_normal_skill'


def report(*, end=900, with_cast=True, hits=(400, 650), skill=SKILL):
    return {'battle': {'duration_ms': 7000, 'total_damage': 200},
            'participants': [{'character_key': OWNER}],
            'casts': [dict(character_key=OWNER, skill_key=skill,
                           ts_ms_from_start=100, end_ms_from_start=end)] if with_cast else [],
            'timeline_events': [dict(lane_type='skill', event_type='damage',
                source_character_key=OWNER, event_key=skill, event_group_key='cast-1',
                actual_start_ms_from_start=100 if with_cast else None,
                actual_end_ms_from_start=end if with_cast else None,
                ts_ms_from_start=stamp, value=100) for stamp in hits]}


@pytest.mark.parametrize('with_cast', [True, False])
def test_complete_lifecycle_uses_logged_bounds_despite_fixed_frame_setting(with_cast):
    snapshot = report(with_cast=with_cast)
    if not with_cast:
        for event in snapshot['timeline_events']:
            event.update(actual_start_ms_from_start=100, actual_end_ms_from_start=900)
    before = deepcopy(snapshot)
    block, = timeline_blocks(snapshot)
    assert display_bounds(block, True) == display_bounds(block, False) == (100, 900)
    assert block.frame_reference == {}
    assert [e['ts_ms_from_start'] for e in block.events if e['event_type'] == 'damage'] == [400, 650]
    assert block.contribution_summary()['damage'] == 200
    assert snapshot == before


def test_missing_end_uses_first_hit_fixed_duration_only_for_display():
    snapshot = report(end=None, hits=(650, 400))
    before = deepcopy(snapshot)
    block, = timeline_blocks(snapshot)
    start, end = display_bounds(block)
    assert start == 400  # Hit anchor, even though the cast began at 100.
    assert end-start == pytest.approx(155/30*1000)
    assert display_bounds(block, False) == (100, 100)
    assert '不还原前摇' in block.description()
    assert block.contribution_summary()['damage'] == 200
    assert snapshot == before


def test_no_hits_or_unknown_exact_skill_never_inherit_a_fixed_duration():
    cast, = timeline_blocks(report(end=None, hits=()))
    assert display_bounds(cast) == (100, 100)
    unknown, = timeline_blocks(report(end=None, skill=SKILL+'_unknown_projectile'))
    assert unknown.frame_reference == {}
    assert display_bounds(unknown) == (100, 100)


def test_details_fold_restores_space_and_click_does_not_reopen_it(app):
    dialog = BattleDetailDialog(report(), '完整起止与独立伤害点')
    try:
        dialog.show()
        QTest.qWait(100)
        assert dialog.inspector.count() == 4
        assert not dialog.details_toggle.isChecked()
        assert not dialog.skill_frames_check.isChecked()
        assert dialog.detail_split.sizes()[1] == 0
        dialog.detail_split.setSizes([180, 210])
        QTest.qWait(30)
        expanded_height = dialog.timeline.height()
        QTest.mouseClick(dialog.details_toggle, Qt.MouseButton.LeftButton)
        QTest.qWait(40)
        assert dialog.detail_split.sizes()[1] == 0
        assert dialog.timeline.height() > expanded_height
        assert dialog.grab().save(str(EVIDENCE/'timeline-details-collapsed.png'))
        block = dialog.timeline._blocks[0]
        dialog.timeline._activate(block)
        app.processEvents()
        assert dialog.detail_split.sizes()[1] == 0
        assert dialog.event_detail.toPlainText() == block.description()
        QTest.mouseClick(dialog.details_toggle, Qt.MouseButton.LeftButton)
        QTest.qWait(40)
        assert dialog.details_toggle.isChecked()
        assert dialog.detail_split.sizes()[1] > 0
        assert dialog.grab().save(str(EVIDENCE/'timeline-details-expanded.png'))
    finally:
        dialog.close()
        app.processEvents()


def test_details_drag_corner_buttons_and_toolbar_share_panel_state(app):
    dialog = BattleDetailDialog(report(), '详情面板交互')
    try:
        dialog.show()
        QTest.qWait(80)
        dialog.details_toggle.click()
        assert dialog.detail_split.details_expanded()
        before = dialog.detail_split.sizes()
        dialog.inspector.maximize_button.click()
        assert dialog.detail_split.details_maximized()
        assert dialog.inspector.maximize_button.toolTip() == '还原详情'
        assert dialog.details_toggle.isChecked()
        QTest.qWait(40)
        assert dialog.grab().save(str(EVIDENCE/'timeline-details-maximized.png'))
        dialog.inspector.maximize_button.click()
        assert all(dialog.detail_split.sizes())
        assert dialog.detail_split.sizes() == before
        dialog.detail_split.moveSplitter(0, 1)
        assert dialog.detail_split.details_maximized()
        assert dialog.inspector.maximize_button.toolTip() == '还原详情'
        dialog.detail_split.moveSplitter(dialog.detail_split.height(), 1)
        assert not dialog.detail_split.details_expanded()
        assert not dialog.details_toggle.isChecked()
        assert dialog.details_toggle.text() == '展开详情'
        dialog.details_toggle.click()
        assert dialog.detail_split.details_expanded()
        dialog.inspector.collapse_button.click()
        assert dialog.detail_split.sizes()[1] == 0
        assert not dialog.details_toggle.isChecked()
        dialog._update_hover_time('1.234s · 技力未知')
        assert dialog.hover_time_label.text() == '时间 1.234s'
        dialog._update_hover_time('')
        assert dialog.hover_time_label.text() == '时间 —'
    finally:
        dialog.close()
        app.processEvents()


def test_unit_switch_keeps_lifecycle_and_hit_geometry_and_inspection(app):
    snapshot = report()
    before = deepcopy(snapshot)
    dialog = BattleDetailDialog(snapshot, '秒/帧显示单位')
    try:
        dialog.show()
        QTest.qWait(70)
        block = dialog.timeline._blocks[0]
        dialog.timeline._activate(block)
        extent = dialog.timeline._time_extent
        bounds = display_bounds(block)
        assert dialog.timeline.hit_markers == 2
        dialog.time_unit_combo.setCurrentIndex(1)
        app.processEvents()
        assert dialog.timeline._time_extent == extent
        assert display_bounds(block) == bounds
        assert dialog.timeline.hit_markers == 2
        assert dialog.inspector.hits.item(0, 0).text() == '12'
        assert '时间 / F' in dialog.inspector.hits.horizontalHeaderItem(0).text()
        assert snapshot == before
    finally:
        dialog.close()
        app.processEvents()
    assert format_time(350, 'frames') == '10.5F'
    ticks = list(ruler_ticks(0, 2000, 400, unit='frames'))
    assert ticks and all(label.endswith('F') for _, label in ticks)
