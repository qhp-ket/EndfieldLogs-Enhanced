"""Merged role cells, immediate wheel input, and stage-dependent resources."""
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from endfield_pcap import battle_energy_evidence as energy
from endfield_pcap.gui_battle_timeline import BattleTimeline
from endfield_pcap.gui_widgets import InterfacePage


def test_role_cells_span_adjacent_type_lanes_without_a_heading_row(app):
    owner = 'chr_0004_pelica'
    view = BattleTimeline()
    view.resize(800, 400)
    view.set_snapshot(dict(battle={'duration_ms': 5000}, participants=[{'character_key': owner}],
        casts=[dict(character_key=owner, skill_key=owner+kind,
                    ts_ms_from_start=stamp, end_ms_from_start=stamp+2000)
               for kind in ('_normal_skill', '_combo_skill') for stamp in (0, 500)]))
    try:
        view.show(); app.processEvents()
        assert len(view._role_cells) == 1
        top, height, name, key = view._role_cells[0]
        assert key == owner and name == '佩丽卡'
        assert not any(row[3] == 'role' for row in view._labels)
        assert top == view._expand_rows[0][0]
        assert top+height == sum(view._expand_rows[-1][:2])
        view.toggle_lane((owner, '战技'))
        assert view._role_cells[0][1] > height
        assert len(view._role_cells) == 1  # Re-render replaces merged cells.
    finally:
        view.close()


def test_wheel_moves_immediately_and_does_not_continue_after_release(app):
    page = InterfacePage('scroll-test', '', '')
    content = QWidget()
    content.setMinimumHeight(3000)
    page.content_layout.addWidget(content)
    page.resize(500, 400)
    try:
        page.show(); QTest.qWait(40)
        viewport = page.viewport()
        event = QWheelEvent(QPointF(100, 100), QPointF(viewport.mapToGlobal(QPoint(100, 100))),
            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(viewport, event)
        value = page.verticalScrollBar().value()
        assert value > 0
        QTest.qWait(200)
        assert page.verticalScrollBar().value() == value
        momentum = QWheelEvent(QPointF(100, 100), QPointF(100, 100), QPoint(0, -50), QPoint(),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollMomentum, False)
        QApplication.sendEvent(viewport, momentum)
        assert page.verticalScrollBar().value() == value
    finally:
        page.close()


def test_unknown_stage_does_not_assume_300_capacity_8_speed_or_initial_resource(monkeypatch):
    monkeypatch.setattr(energy, 'energy_rules', lambda: dict(capacity=300, base_recovery_per_second=8, skills={}))
    series = energy.energy_series(dict(battle={'duration_ms': 3000}, atb_events=[
        dict(ts_ms_from_start=1000, value=450)]))
    assert series['capacity'] is None and series['initial_value'] is None
    assert not series['segments']
    assert energy.energy_value_at(series, 0)[0] is None
    assert energy.energy_value_at(series, 1000) == (450, '实测')
    assert energy.energy_value_at(series, 2000)[0] is None


def test_observed_stage_speed_changes_override_defaults_and_initial_value_is_measured(monkeypatch):
    monkeypatch.setattr(energy, 'energy_rules', lambda: dict(skills={}, stages={
        'fixture-stage': {'capacity': 600, 'base_recovery_per_second': 1}}))
    series = energy.energy_series(dict(battle={'duration_ms': 4000, 'dungeon_context_id': 'fixture-stage'},
        atb_events=[dict(ts_ms_from_start=0, value=450, recovery_speed=20),
                    dict(ts_ms_from_start=1000, value=470, recovery_speed=0),
                    dict(ts_ms_from_start=2000, value=470, recovery_speed=100)]))
    assert series['initial_value'] == 450 and series['capacity'] == 600
    assert energy.energy_value_at(series, 500)[0] == 460
    assert energy.energy_value_at(series, 1500)[0] == 470
    assert energy.energy_value_at(series, 3000)[0] == 570
    assert energy.energy_value_at(series, 4000)[0] == 600
