"""Per-character track membership, fallback and portable GUI preferences."""
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from qfluentwidgets import Theme, setTheme
from shiboken6 import isValid

from app_test_support.scenarios.timeline import OWNER, report
from app_test_support.ui.qt import EVIDENCE
from endfield_pcap.analysis.battle.detail import TimelineBlock, timeline_blocks
from endfield_pcap.analysis.battle.lane_config import (
    default_lanes, normalize_lane_configs, resolved_lanes, skill_key, skill_options,
)
from endfield_pcap.analysis.battle.layout import skill_lanes
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.gui.battle.lane_settings import RoleLanesDialog
from endfield_pcap.gui.config import load_app_config


def blocks():
    return [TimelineBlock(OWNER, 'skill', 100+i*20, 900+i*20, name, category,
                         [dict(event_key=name)], cast_evidence={'skill_key': name})
            for i, (name, category) in enumerate([
                ('skill-a', '战技'), ('skill-b', '战技'), ('combo', '连携'),
                ('ultimate', '大招'), ('heavy', '重击'), ('extra', '其他')])]


def test_defaults_merge_combo_ultimate_and_omit_other_track():
    items = blocks()
    rows = default_lanes(skill_options(items, OWNER))
    assert [row['name'] for row in rows] == ['战技', '连携 / 终结']
    assert [row['skills'] for row in rows] == [
        [skill_key(b) for b in items[:2]], [skill_key(b) for b in items[2:4]]]
    assert resolved_lanes(items, OWNER) == rows
    # All evidenced skills remain available in the role settings editor.
    assert len(skill_options(items, OWNER)) == len(items)
    lanes = skill_lanes(items, [OWNER], set(), lambda t: t/10, 4)
    assert [lane.name for lane in lanes] == ['战技', '连携 / 终结']
    assert len([p for lane in lanes for p in lane.placements]) == 4


def test_custom_tracks_preserve_order_and_evidence_with_unassigned_fallback():
    items = blocks()
    saved = [dict(id='finish', name='收尾', skills=[skill_key(items[3]), skill_key(items[0]), 'old']),
             dict(id='其他', name='自定义', skills=[skill_key(items[2])])]
    before = deepcopy((items, saved))
    rows = resolved_lanes(items, OWNER, saved)
    assert [row['name'] for row in rows] == ['收尾', '自定义', '其他']
    assert rows[-1]['id'] != '其他'  # A renamed track keeps its own membership.
    assert set(rows[-1]['skills']) == {skill_key(items[i]) for i in (1, 4, 5)}
    options = skill_options(items+[items[0], TimelineBlock('another', 'skill', 0, 1, 'foreign', '战技')], OWNER)
    assert len(options) == 6 and 'old' not in {option['key'] for option in options}
    lanes = skill_lanes(items, [OWNER], {(OWNER, 'finish')}, lambda t: t/10, 4,
                        lane_configs={OWNER: saved})
    assert [lane.category for lane in lanes] == [row['id'] for row in rows]
    assert lanes[0].rows == 2
    placements = [placement for lane in lanes for placement in lane.placements]
    assert len(placements) == len(items)
    assert {id(p[0]) for p in placements} == {id(b) for b in items}
    assert all((left, right) == (b.start_ms/10, b.end_ms/10) for b, _, left, right in placements)
    assert (items, saved) == before


def test_empty_configuration_and_new_skills_stay_in_other():
    items = blocks()
    assert normalize_lane_configs({OWNER: []}) == {OWNER: []}
    all_other = resolved_lanes(items, OWNER, [])
    assert len(all_other) == 1 and all_other[0]['name'] == '其他'
    saved = [dict(id='keep', name='其他', skills=[skill_key(items[2])])]
    rows = resolved_lanes(items, OWNER, saved)
    assert len(rows) == 1 and len(rows[0]['skills']) == len(items)
    assert normalize_lane_configs({OWNER: saved+[dict(id='dup', name='重复', skills=saved[0]['skills'])]})[OWNER][1]['skills'] == []


def test_editor_allows_unchecking_removing_reordering_and_cancel(app):
    items = blocks()
    saved = default_lanes(skill_options(items, OWNER))
    before = deepcopy(saved)
    dialog = RoleLanesDialog(items, OWNER, saved)
    try:
        dialog.skills.item(0).setCheckState(Qt.CheckState.Unchecked)
        assert dialog.save_button.isEnabled() and '其他' in dialog.status.text()
        assert skill_key(items[0]) not in dialog.value()[0]['skills']
        dialog.add_button.click()
        dialog.skills.item(2).setCheckState(Qt.CheckState.Checked)
        assert sum(skill_key(items[2]) in row['skills'] for row in dialog.rows) == 1
        moved = dialog.rows[-1]['id']
        dialog.up_button.click()
        assert dialog.rows[-2]['id'] == moved
        # Exercise the same model move as a list drag-and-drop.
        model = dialog.tracks.model()
        model.moveRow(model.index(-1, -1), len(dialog.rows)-2, model.index(-1, -1), 0)
        assert dialog.rows[0]['id'] == moved
        dialog.reset_button.click()
        assert dialog.rows == before
        while dialog.rows:
            dialog.remove_button.click()
        assert dialog.save_button.isEnabled() and dialog.value() == []
        dialog.reject()
        assert saved == before
    finally:
        dialog.close()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize('theme', [Theme.LIGHT, Theme.DARK])
def test_role_button_saves_configuration_and_reopens_from_portable_settings(app, tmp_path, theme):
    setTheme(theme)
    parent = QWidget()
    parent.config_path = tmp_path/'settings.json'
    parent.app_config = load_app_config(parent.config_path)
    snapshot = report()
    snapshot['casts'] += [dict(character_key=OWNER, skill_key=OWNER+suffix,
                              ts_ms_from_start=300, end_ms_from_start=1500)
                          for suffix in ('_combo_skill', '_ultimate_skill')]
    before = deepcopy(snapshot)
    dialog = BattleDetailDialog(snapshot, '角色轨道', parent)
    try:
        dialog._initial_placement_scheduled = True
        dialog.resize(1160, 760)
        dialog.show(); QTest.qWait(60)
        view = dialog.timeline
        assert view.skill_lane_rows == {(OWNER, '战技'): 1, (OWNER, '连携'): 1}
        button = view._role_buttons[OWNER]
        assert button.isVisible() and button.y() >= view.TOP
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        QTest.qWait(40)
        editor = dialog._lane_dialog
        assert editor.isVisible()
        assert editor.skills.count() == len(skill_options(timeline_blocks(snapshot), OWNER))
        assert editor.grab().save(str(EVIDENCE/f'role-lanes-{theme.value}.png'))
        # Delete all explicit tracks; every skill must survive in Other.
        while editor.rows:
            editor.remove_button.click()
        editor.save_button.click(); QTest.qWait(40)
        assert view.skill_lane_rows == {(OWNER, '其他'): 1}
        assert view.drawn_blocks == 3 and view.hit_markers == 2
        assert view._time_extent[:2] == (0., 7000.)
        assert load_app_config(parent.config_path).battle_lane_configs[OWNER] == []
        assert dialog.grab().save(str(EVIDENCE/f'role-lanes-merged-{theme.value}.png'))
        view.set_graphics_zoom(200)
        view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
        app.processEvents()
        if button.isVisible():
            assert view.viewport().rect().contains(button.geometry())
            assert button.y() >= view.TOP
        assert snapshot == before
        dialog.close(); app.processEvents()
        parent.app_config = load_app_config(parent.config_path)
        restored = BattleDetailDialog(snapshot, '恢复轨道', parent)
        try:
            assert restored.timeline.skill_lane_rows == {(OWNER, '其他'): 1}
            assert restored.timeline.drawn_blocks == 3
        finally:
            restored.close()
    finally:
        if isValid(dialog):
            dialog.close()
        parent.close(); parent.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
        setTheme(Theme.LIGHT)
