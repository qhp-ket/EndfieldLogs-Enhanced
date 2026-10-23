"""Compact analysis controls, draggable labels and cursor evidence previews."""
from copy import deepcopy
from PySide6.QtCore import QPoint, QPointF, Qt, QRectF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QToolTip
from qfluentwidgets import Theme, setTheme

from endfield_pcap.battle_buff_labels import buff_display_name
from endfield_pcap.gui_battle_detail import BattleDetailDialog
from endfield_pcap.gui_battle_poise_plot import poise_hover_text
from endfield_pcap.gui_battle_timeline_labels import label_tooltip
from test_buff_display_states import buff
from test_qt_snapshot_bridge import EVIDENCE
from test_timeline_intervals_and_details import report, OWNER


def sample():
    snapshot = report()
    snapshot['participants'].append({'character_key': 'chr_0005_chen'})
    for event, value in zip(snapshot['timeline_events'], (90, 0)):
        event.update(target_character_key='enemy', target_actor_id='1', target_character_name='测试敌人',
                     poise_damage={'current_value': value, 'value': -10})
    snapshot['timeline_events'] += [
        {**buff(0, 2000), 'event_name': '增伤', 'event_key': 'buff_unknown_a',
             'source_character_key': 'chr_0005_chen', 'target_character_key': OWNER},
        {**buff(2500, 4000, 'second'), 'event_name': '增伤', 'event_key': 'buff_unknown_a',
             'source_character_key': 'chr_0005_chen', 'target_character_key': OWNER},
        {**buff(100, 3000), 'event_name': '测试实际名称', 'event_key': 'buff_unknown_b',
             'source_character_key': OWNER, 'target_character_key': OWNER}]
    return snapshot


def test_compact_rows_and_page_local_character_selectors(app):
    dialog = BattleDetailDialog(sample(), '紧凑战斗分析')
    try:
        dialog.show(); QTest.qWait(80)
        pos = lambda widget: widget.mapTo(dialog, QPoint())
        assert abs(pos(dialog.heading).y()-pos(dialog.metrics_label).y()) < 8
        assert dialog.tabs.count() == 3
        assert '技力数据' not in [dialog.tabs.tabText(i) for i in range(dialog.tabs.count())]
        assert abs(pos(dialog.character_combo).y()-pos(dialog.buff_check).y()) < 8
        assert abs(pos(dialog.character_combo).y()-pos(dialog.skill_frames_check).y()) < 8
        assert abs(pos(dialog.zoom_slider).y()-pos(dialog.graphics_zoom_slider).y()) < 8
        assert abs(pos(dialog.zoom_slider).y()-pos(dialog.time_unit_combo).y()) < 8
        assert '回退' in dialog.skill_frames_check.text() and '兜底' not in dialog.skill_frames_check.text()
        assert dialog.tabs.widget(0).isAncestorOf(dialog.character_combo)
        dialog.tabs.setCurrentIndex(1)
        assert dialog.skill_character_combo.isVisible()
        dialog.skill_character_combo.setCurrentIndex(2)
        assert dialog.character_combo.currentData() == 'chr_0005_chen'
        assert dialog.timeline._character == 'chr_0005_chen'
        dialog.tabs.setCurrentIndex(0)
        assert not dialog.skill_character_combo.isVisible()
    finally:
        dialog.close(); app.processEvents()


def test_buff_actual_name_or_recorded_source_without_guessing_from_id():
    base = dict(event_key='buff_chr_0032_lizhiyan_mystery', event_name='增伤 / 暴击',
                source_character_key='chr_0005_chen', source_skill_key='chr_0005_chen_normal_skill')
    label = buff_display_name(base)
    assert label.startswith('陈千语 · ')
    assert '增伤 / 暴击' in label and 'lizhiyan' not in label
    assert buff_display_name({**base, 'buff_name': '明确记录的名称'}) == '明确记录的名称'
    assert buff_display_name({**base, 'event_name': '实际状态名'}) == '实际状态名'
    assert buff_display_name(dict(event_key='buff_no_source', event_name='增伤')).startswith('未知来源')


def test_each_buff_track_has_border_and_both_columns_drag_independently(app):
    snapshot = sample()
    before = deepcopy(snapshot)
    dialog = BattleDetailDialog(snapshot, '轨道边框和列宽')
    try:
        dialog.buff_check.setChecked(True)
        dialog.show(); QTest.qWait(80)
        view = dialog.timeline
        assert len(view.buff_row_borders) == 2  # Two episodes of a share one track.
        original_blocks = view._blocks
        role, track = view._role_column_width, view._track_column_width
        def drag(x, delta):
            start = QPoint(round(x), 12)
            QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
            QTest.mouseMove(view.viewport(), start+QPoint(delta, 0), 20)
            QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=start+QPoint(delta, 0))
            app.processEvents()
        drag(view._role_width, -25)
        assert view._role_column_width < role
        assert view._track_column_width == track
        drag(view.LEFT, 100)
        assert view._track_column_width > track
        adjusted = view._role_column_width, view._track_column_width
        view.set_graphics_zoom(120)
        assert (view._role_column_width, view._track_column_width) == adjusted
        assert view._blocks is original_blocks
        y, block = view._buff_labels[0]
        text = label_tooltip(view, view._role_width+12, y+10)
        assert block.name in text and block.events[0]['event_key'] in text
        assert snapshot == before
    finally:
        dialog.close(); app.processEvents()


def test_poise_hover_anywhere_on_track_reports_last_observation_and_zero(app):
    dialog = BattleDetailDialog(sample(), '失衡悬浮预览')
    try:
        dialog.show(); QTest.qWait(80)
        view = dialog.timeline
        axis = next(a for a in view._poise_axes if a['enemy']['samples'])
        y = axis['y']+axis['height']*.65
        assert '此前没有观测' in poise_hover_text(view, 200, y)
        assert '90' in poise_hover_text(view, 525, y)
        assert '最近观测' in poise_hover_text(view, 525, y)
        assert '失衡观测值 0（实测）' in poise_hover_text(view, 650, y)
        assert poise_hover_text(view, 525, 0) is None
        start, duration, width = view._time_extent
        x = view.LEFT+(525-start)/duration*width
        view.ensureVisible(QRectF(x, axis['y'], 1, axis['height']), 0, 0)
        app.processEvents()
        point = view.mapFromScene(x, y)
        assert view.viewport().rect().contains(point)
        previews = []
        view.timeHovered.connect(previews.append)
        move = QMouseEvent(QEvent.Type.MouseMove, QPointF(point),
            QPointF(view.viewport().mapToGlobal(point)), Qt.MouseButton.NoButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(view.viewport(), move)
        QTest.qWait(60)
        assert previews and '失衡观测值 90' in previews[-1]
        assert dialog.hover_time_label.text() == '时间 0.525s'
        assert '失衡观测值 90' in QToolTip.text()
        view.set_time_unit('frames')
        assert abs(float(dialog.hover_time_label.text()[3:-1])-15.75) < .03
        assert '15.75F' in poise_hover_text(view, 525, y)
    finally:
        QToolTip.hideText()
        dialog.close(); app.processEvents()


def test_synthetic_battle_compact_light_and_dark_screenshots(app):
    snapshot = sample()
    for theme in (Theme.LIGHT, Theme.DARK):
        setTheme(theme)
        dialog = BattleDetailDialog(snapshot, '合成战斗展示')
        try:
            dialog.buff_check.setChecked(True)
            dialog.details_toggle.setChecked(False)
            dialog.show(); QTest.qWait(100)
            assert dialog.grab().save(str(EVIDENCE/f'battle-analysis-compact-{theme.value}.png'))
            dialog.tabs.setCurrentIndex(1)
            QTest.qWait(40)
            assert dialog.grab().save(str(EVIDENCE/f'battle-analysis-skills-{theme.value}.png'))
        finally:
            dialog.close(); app.processEvents()
    setTheme(Theme.LIGHT)
