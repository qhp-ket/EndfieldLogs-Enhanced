"""Local history details use canonical reports and AKEData display names."""
from copy import deepcopy
from dataclasses import replace
import threading
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from qfluentwidgets import Theme, setTheme
from endfield_pcap.analysis.battle.detail import timeline_blocks
from endfield_pcap.analysis.battle.detail import skill_rows
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.models import SquadMemberPayload
from endfield_pcap.data.skill_names import dictionary
from endfield_pcap.data.skill_names import skill_label
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import two_battles, wait_for
from app_test_support.ui.qt import EVIDENCE, snapshot_message


def test_chinese_dictionary_resolves_variants_and_leaves_unknown_skills_visible():
    assert len(dictionary()['groups']) == 140
    assert skill_label('chr_0032_lizhiyan_normal_skill').name == '摧玉网格'
    assert skill_label('chr_0032_lizhiyan_normal_skill_projhit_2').name == '摧玉网格 · 弹体命中·2'
    assert skill_label('chr_0004_pelica_attack_2').name.endswith('②')
    assert skill_label('chr_0036_jsspsi_ultimate_skill').name == '谁都不许扫兴'
    # Prefix lookup must never mistake a character or an unknown talent for an
    # arbitrary normal attack. Retain a canonical name if the dict lacks it.
    key = 'chr_0032_lizhiyan_talent_new'
    assert skill_label(key).name == key
    assert skill_label(key, '核心已有译名').name == '核心已有译名'
    assert skill_label('chr_0032_lizhiyan').group_key == ''


def test_timeline_preserves_core_grouping_and_skill_counts_without_mutating_snapshot():
    snapshot = snapshot_message()['snapshot']
    before = deepcopy(snapshot)
    blocks = timeline_blocks(snapshot)
    assert len([b for b in blocks if b.lane == 'skill']) == 1
    skill = next(b for b in blocks if b.lane == 'skill')
    assert len(skill.events) > 1
    assert 'rDMG 分配' in skill.description()
    rows = skill_rows(snapshot)
    assert rows[0]['cast_count'] == snapshot['role_skill_stats'][0]['cast_count'] == 1
    assert rows[0]['total_damage'] == 760
    assert rows[0]['damage_percent'] == 100
    assert snapshot == before


def test_detail_filters_sort_zoom_and_empty_report(app):
    snapshot = snapshot_message()['snapshot']
    dialog = BattleDetailDialog(snapshot, '中文技能分析测试')
    try:
        dialog.show()
        QTest.qWait(100)
        assert dialog.skill_table.rowCount() == len(snapshot['role_skill_stats'])
        dialog.buff_check.setChecked(True)
        count = dialog.timeline.drawn_blocks
        assert count > 1
        dialog.buff_check.setChecked(False)
        assert dialog.timeline.drawn_blocks < count
        initial = dialog.timeline.sceneRect().width()
        dialog.zoom_slider.setValue(400)
        assert dialog.timeline.sceneRect().width() > initial * 2
        supporter = dialog.character_combo.findData('chr_0035_liino')
        dialog.character_combo.setCurrentIndex(supporter)
        assert dialog.skill_table.rowCount() == 0
        assert dialog.timeline.drawn_blocks == 0
        dialog.character_combo.setCurrentIndex(0)
        block_item = next(item for item in dialog.timeline.scene().items() if hasattr(item, 'block'))
        dialog.timeline.ensureVisible(block_item)
        point = dialog.timeline.mapFromScene(block_item.rect().center())
        # A zoomed block can be wider than the viewport. Click its visible
        # interior, outside the sticky ruler and character column.
        point.setX(max(dialog.timeline.LEFT + 8, min(dialog.timeline.viewport().width()-8, point.x())))
        point.setY(max(dialog.timeline.TOP + 8, min(dialog.timeline.viewport().height()-8, point.y())))
        QTest.mouseClick(dialog.timeline.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert dialog.event_detail.toPlainText() == block_item.block.description()
        assert snapshot_message()['snapshot'] == snapshot
    finally:
        dialog.close(); app.processEvents()
    empty = BattleDetailDialog({}, '无证据')
    try:
        assert empty.timeline.drawn_blocks == 0
        assert empty.skill_table.rowCount() == 0
    finally:
        empty.close(); app.processEvents()


def test_history_details_load_only_requested_record_and_reuse_last_report(main_window, app, tmp_path, monkeypatch):
    window = main_window
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    assert all(not r.snapshot for r in window.records)
    calls = []
    from endfield_pcap.history.analysis import load_record_snapshot
    def analyze(record):
        calls.append(record.record_index)
        return load_record_snapshot(record)
    monkeypatch.setattr('endfield_pcap.gui.pages.history.actions.load_record_snapshot', analyze)
    listing = window.records_page.record_list
    window.records_page.select_all_btn.click()
    target = window._selected_history_records()[-1]
    window.records_page.analysis_detail_btn.click()
    wait_for(lambda: window._history_detail_dialog is not None, app)
    assert calls == [target.record_index], 'Inspect must not eagerly parse every selected/file record'
    assert window._history_detail_dialog.snapshot['battle']['total_damage'] == target.total_damage
    window._history_detail_dialog.close()
    window.records_page.analysis_detail_btn.click()
    assert calls == [target.record_index]
    assert window._history_detail_dialog is not None
    window._return_live_overlay()
    assert not window.overlay_manager._history_mode
    window.records_page.remove_record_btn.click()
    assert window._history_detail_snapshot is None
    assert window._history_detail_dialog is None
    assert source.exists()


def test_console_editor_fits_card_and_page_scrolls_in_short_window(main_window, app):
    window = main_window
    window.resize(1050, 650)
    for i in range(80):
        window.logs_page.append_log(f'控制台完整行 {i}：日志内容 / 截取时间 / 统计快照')
    window.home_page.status_card.set_squad_members([
        SquadMemberPayload(battle_inst_id=i+1, templateid='chr_0004_pelica', display_name='佩丽卡', squad_index=i, is_leader=i==0)
        for i in range(4)])
    base = window.app_config.overlays[0]
    window.overlay_page.status_card.set_entries([
        *window.app_config.overlays,
        replace(base, id='buff-preview', name='BUFF 监控', source_value='buff'),
        replace(base, id='uid-preview', name='UID 遮挡', source_value='uid_mask')])
    window.switchTo(window.logs_page)
    QTest.qWait(180)
    page = window.logs_page
    editor = page.log_view
    assert editor.height() >= 160
    assert editor.verticalScrollBar().maximum() > 0
    QTest.qWait(100)
    visible = editor.mapTo(page.viewport(), editor.rect().bottomRight()).y()
    assert visible < page.viewport().height()
    assert window.grab().save(str(EVIDENCE / 'gui-console-complete.png'))


def test_return_live_cancels_pending_detail_dialog(main_window, app, tmp_path, monkeypatch):
    window = main_window
    source = tmp_path / 'trace_20261022-100000.log'
    source.write_text(two_battles(), encoding='utf8')
    window._queue_trace_import([source])
    wait_for(lambda: not window._trace_import_pending, app)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def analyze(record):
        entered.set()
        release.wait(5)
        finished.set()
        return snapshot_message()['snapshot']
    monkeypatch.setattr('endfield_pcap.gui.pages.history.actions.load_record_snapshot', analyze)
    window.records_page.analysis_detail_btn.click()
    wait_for(entered.is_set, app)
    window._return_live_overlay()
    release.set()
    wait_for(finished.is_set, app)
    window._drain_queue()
    assert window._history_detail_dialog is None
    assert not window.overlay_manager._history_mode


def test_detail_screenshots_with_synthetic_trace(app):
    # The current local fixture has multi-hit skills and multiple buff tracks.
    snapshot = snapshot_message()['snapshot']
    for mode in (Theme.LIGHT, Theme.DARK):
        setTheme(mode)
        dialog = BattleDetailDialog(snapshot, '战斗时间轴与角色技能构成')
        try:
            dialog.resize(1160, 760)
            dialog.show()
            QTest.qWait(180)
            assert dialog.grab().save(str(EVIDENCE / f'battle-detail-{mode.value}-timeline.png'))
            dialog.tabs.setCurrentIndex(1)
            QTest.qWait(100)
            assert dialog.grab().save(str(EVIDENCE / f'battle-detail-{mode.value}-skills.png'))
        finally:
            dialog.close(); app.processEvents()
    setTheme(Theme.LIGHT)
