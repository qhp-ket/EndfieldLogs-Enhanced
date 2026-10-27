"""Native curve semantics, compact controls and sorted evidence."""
from copy import deepcopy
import json
import pytest
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from app_test_support.scenarios.compact import sample
from app_test_support.scenarios.timeline import report
from app_test_support.ui.qt import EVIDENCE
from app_test_support.ui.window import main_window
from endfield_pcap.analysis.battle.damage import damage_series
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.gui.battle.presenter import BattleDetailPresenter
from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.gui.battle.plots.damage import damage_hover_text
from endfield_pcap.gui.battle.tables import EvidenceItem


def test_native_summary_preserves_participant_totals_quality_and_column_widths(main_window, app):
    from endfield_pcap.settings import load_app_config
    snapshot = sample()
    snapshot['participants'][0].update(total_damage=1234.5, total_rd=1111.25,
                                       dps=123.45, rdps=111.125, crit_rate=.25)
    snapshot['participants'][1]['crit_rate'] = float('nan')
    snapshot['snapshot_quality'] = {'rdps': {'status': 'provisional', 'reasons': ['保留的原因']}}
    before = deepcopy(snapshot)
    dialog = BattleDetailPresenter.create(snapshot, '原生报告信息', main_window.settings_store, parent=main_window)
    try:
        assert not hasattr(dialog, '_summary_dialog')
        dialog._show_summary()
        summary = dialog._summary_dialog
        app.processEvents()
        table = summary.participants
        assert [table.item(0, c).text() for c in range(1, 6)] == ['1,234.50', '1,111.25', '123.45', '111.12', '25.00%']
        assert table.item(1, 5).text() == '未知'
        assert json.loads(summary.quality.toPlainText()) == snapshot['snapshot_quality']
        table.setColumnWidth(2, 176)
        summary._table_timer.start()
        summary.accept()
        assert load_app_config(main_window.config_path).battle_table_widths['participants'][2] == 176
        assert snapshot['snapshot_quality'] == before['snapshot_quality']
        assert snapshot['participants'][0] == before['participants'][0]
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize('metric,expected', [('dmg', 350), ('dps', 350/1.5), ('rdmg', 70), ('rdps', 70/1.5)])
def test_bucket_boundaries_and_final_denominator(metric, expected):
    snapshot = dict(battle={'duration_ms':1500}, participants=[{'character_key':'a'}, {'character_key':'b'}], timeline_events=[])
    for stamp, value in [(-1,999), (0,100), (999,50), (1000,80), (1500,120), (1501,999)]:
        snapshot['timeline_events'].append(dict(event_type='damage', ts_ms_from_start=stamp, value=value,
            source_character_key='a', rdps_contributions=[dict(character_key='b', value=value/5)]))
    before = deepcopy(snapshot)
    series = damage_series(snapshot, metric)
    owner = 'b' if metric.startswith('r') else 'a'
    assert [p['time_ms'] for p in series['points']] == [0,1000,1500]
    assert series['points'][-1]['values'][owner] == pytest.approx(expected)
    assert series['hits'] == 4 and series['missing'] == 0
    assert damage_series(snapshot, metric, owner)['points'][-1]['values'] == {owner:pytest.approx(expected)}
    assert snapshot == before


def test_unknown_and_partial_allocations_differ_from_zero():
    snapshot = report()
    for event in snapshot['timeline_events']:
        event.pop('rdps_contributions', None)
    unknown = damage_series(snapshot, 'rdps')
    assert not unknown['points'] and unknown['missing'] == unknown['hits'] == 2
    snapshot['timeline_events'][0]['rdps_contributions'] = [dict(character_key='a', value=0)]
    partial = damage_series(snapshot, 'rdmg')
    assert partial['missing'] == 1 and partial['points'][-1]['values']['a'] == 0


def test_curve_cache_bounds_and_controls(app):
    dialog = BattleDetailDialog(sample(), 'Native curves')
    try:
        # The test screen is 800px wide; placement itself has separate coverage.
        dialog._initial_placement_scheduled = True
        dialog.resize(1160,760)
        dialog.show(); QTest.qWait(80)
        view = dialog.timeline
        assert dialog.curve_combo.currentData() == 'rdmg'
        assert view._damage_axis['series']['metric'] == 'rdmg'
        dialog.curve_combo.setCurrentIndex(dialog.curve_combo.findData('dps'))
        curve = view._damage_axis['series']
        assert curve['points'][-1]['values']['chr_0004_pelica'] == pytest.approx(200/7)
        assert dialog.grab().save(str(EVIDENCE/'battle-native-wide.png'))
        assert view.height()/dialog.height() >= .80, (dialog.size(), view.size(), dialog.body_scroll.size())
        view.set_zoom(200)
        assert view._damage_axis['series'] is curve
        assert view._time_extent[:2] == (0.,7000.)
        axis = view._damage_axis
        assert '桶终点' in damage_hover_text(view,525,axis['y']+60)
        dialog.display_settings.click(); QTest.qWait(30)
        assert dialog.skill_frames_check.isVisible() and dialog.curve_combo.isVisible()
        dialog.display_menu.close()
        dialog.input_button.click(); QTest.qWait(30)
        assert dialog.input_history.attach.isVisible()
        dialog.input_menu.close()
        dialog.curve_combo.setCurrentIndex(dialog.curve_combo.findData('none'))
        assert view._damage_axis is None
        view.set_snapshot(dict(battle={'duration_ms':2500},timeline_events=[]))
        assert not view._damage_cache
        from endfield_pcap.gui.shared.typography import apply_fonts
        apply_fonts(dialog,1.6)
        dialog.resize(720,560); QTest.qWait(60)
        for widget in (dialog.character_combo,dialog.input_button,dialog.details_toggle,dialog.time_unit_combo):
            assert dialog.rect().contains(widget.rect().translated(widget.mapTo(dialog,QPoint())))
        assert dialog.grab().save(str(EVIDENCE/'battle-native-narrow-large-font.png'))
    finally:
        dialog.close(); app.processEvents()


def test_sorted_hit_identity(app):
    snapshot = report()
    snapshot['timeline_events'][0]['value'] = 9
    snapshot['timeline_events'][1]['value'] = 1000
    dialog = BattleDetailDialog(snapshot,'Sorted evidence')
    try:
        dialog._inspect_block(dialog.timeline._blocks[0])
        table = dialog.inspector.hits
        table.sortItems(2,Qt.SortOrder.DescendingOrder)
        table.setCurrentCell(0,2)
        dialog.inspector._select_hit()
        assert json.loads(dialog.inspector.raw.toPlainText())['value'] == 1000
        assert EvidenceItem('9') < EvidenceItem('1,000.00')
        assert EvidenceItem('2.00%') < EvidenceItem('10.00%')
        assert dialog.detail_split.sizes()[1] == 0
    finally:
        dialog.close(); app.processEvents()


def test_timeline_mouse_hover_escapes_plain_evidence_tooltips(app,monkeypatch):
    from PySide6.QtCore import QEvent,QPointF,QRectF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QToolTip
    dialog=BattleDetailDialog(report(),'悬停证据')
    shown=[]
    monkeypatch.setattr(QToolTip,'showText',lambda position,text,*args:shown.append(text))
    try:
        dialog.show();app.processEvents()
        view=dialog.timeline
        item=next(item for item in view.scene().items() if item.toolTip())
        center=item.sceneBoundingRect().center()
        marker=view.scene().addRect(QRectF(center.x()-2,center.y()-2,4,4))
        marker.setToolTip('输入 <键> & 证据')
        point=view.mapFromScene(center)
        event=QMouseEvent(QEvent.Type.MouseMove,QPointF(point),QPointF(view.viewport().mapToGlobal(point)),
                          Qt.MouseButton.NoButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        view.mouseMoveEvent(event)
        assert any('输入 &lt;键&gt; &amp; 证据' in text for text in shown)
    finally:
        dialog.close();app.processEvents()


@pytest.mark.parametrize('character', ['', 'chr_0004_pelica', 'absent'])
def test_combo_input_spans_only_visible_character_tracks(app, character):
    from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsLineItem
    dialog = BattleDetailDialog(sample(), '连携输入范围')
    try:
        view = dialog.timeline
        view.set_filter(character)
        view.set_graphics_zoom(125)
        view.set_input_evidence({'actions': [dict(action='combo', start_ms=200,
            end_ms=350, interrupted=False, tooltip='连携输入范围')],
            'raw': [dict(device='mouse', code='M:X', time_ms=250, value=2)]})
        markers = [item for item in view.scene().items() if item.toolTip() == '连携输入范围']
        cells = [cell for cell in view._role_cells if cell[3]]
        if not cells:
            assert not markers and view.input_markers == 0
            return
        top = min(cell[0] for cell in cells)
        bottom = max(cell[0]+cell[1] for cell in cells)
        assert len(markers) == 2 and view.input_markers == 1
        for item in markers:
            if isinstance(item, QGraphicsRectItem):
                assert item.rect().top() == pytest.approx(top)
                assert item.rect().bottom() == pytest.approx(bottom)
            else:
                assert isinstance(item, QGraphicsLineItem)
                assert item.line().y1() == pytest.approx(top)
                assert item.line().y2() == pytest.approx(bottom)
                assert item.pen().style() == Qt.PenStyle.DashLine
        assert view._damage_axis['y'] >= bottom
        assert view._poise_axes and all(axis['y'] >= bottom for axis in view._poise_axes)
        assert next(row[0] for row in view._labels if row[3] == 'input') > bottom
        assert view._time_extent[:2] == (0., 7000.)
    finally:
        dialog.close(); app.processEvents()


def test_user_table_resize_persists_in_portable_settings(app, tmp_path):
    from PySide6.QtWidgets import QWidget
    from endfield_pcap.settings import load_app_config
    owner = QWidget()
    path = tmp_path/'settings.json'
    store = SettingsStore(load_app_config(path), path)
    dialog = BattleDetailPresenter.create(sample(), 'Column widths', store, parent=owner)
    try:
        dialog.show(); dialog.tabs.setCurrentIndex(1); QTest.qWait(120)
        header = dialog.skill_table.horizontalHeader()
        before = header.sectionSize(0)
        point = QPoint(header.sectionViewportPosition(0)+before-1, header.height()//2)
        QTest.mouseMove(header.viewport(),point)
        QTest.mousePress(header.viewport(),Qt.MouseButton.LeftButton,pos=point)
        QTest.mouseMove(header.viewport(),point+QPoint(48,0),30)
        QTest.mouseRelease(header.viewport(),Qt.MouseButton.LeftButton,pos=point+QPoint(48,0))
        QTest.qWait(400)
        assert header.sectionSize(0) > before
        saved = load_app_config(path).battle_table_widths['skills'][0]
        assert saved == header.sectionSize(0)
    finally:
        dialog.close(); app.processEvents()
    restored = BattleDetailPresenter.create(sample(), 'Restored widths', store, parent=owner)
    try:
        assert restored.skill_table.columnWidth(0) == saved
    finally:
        restored.close(); owner.close()
        owner.deleteLater()
        from PySide6.QtCore import QEvent
        app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        app.processEvents()
