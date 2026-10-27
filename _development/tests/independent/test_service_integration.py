"""Independent service controls and shared history evidence, without game hardware."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
from app_test_support.ui.window import main_window
from app_test_support.ui.qt import EVIDENCE
from app_test_support.scenarios.trace import wait_for
from app_test_support.scenarios.compact import sample
from endfield_pcap.gui.battle.detail import BattleDetailDialog
from endfield_pcap.settings import load_app_config
from endfield_pcap.models import OverlayEntry, OverlaySourceType
from endfield_pcap.overlays.templates import with_template_value
from endfield_pcap.overlays.window import OverlayWindow, OverlayWindowConfig


def test_input_threshold_and_alignment_numeric_editors_remain_readable(main_window, app):
    from PySide6.QtGui import QFontMetrics
    from endfield_pcap.gui.independent.input_settings import InputSettingsDialog
    from endfield_pcap.gui.shared.spinboxes import ReadableDoubleSpinBox
    dialog = InputSettingsDialog({}, main_window)
    offset = ReadableDoubleSpinBox(dialog)
    offset.setRange(-86400000, 86400000)
    offset.setDecimals(3)
    offset.setSuffix(' ms')
    dialog.layout().insertWidget(1, offset)
    try:
        dialog.show()
        for percent in (80, 115, 180):
            main_window.gui_typography.set_scale(percent/100)
            QTest.qWait(60)
            for spin in (dialog.hold, offset):
                editor = spin.lineEdit()
                assert editor.width() >= QFontMetrics(editor.font()).horizontalAdvance(spin.text())+4
                assert editor.geometry().right() < spin.upButton.geometry().left()
            assert dialog.hold.value() == 280
        QTest.mouseClick(dialog.hold.upButton, Qt.MouseButton.LeftButton)
        assert dialog.hold.value() == 281
        dialog.hold.lineEdit().selectAll()
        QTest.keyClicks(dialog.hold.lineEdit(), '320')
        dialog.hold.interpretText()
        assert dialog.value()['hold_ms'] == 320
    finally:
        dialog.close()
        main_window.gui_typography.set_scale(1.15)


def test_home_input_and_combo_subscriptions_are_independent_of_capture(main_window, app):
    window=main_window
    calls=[]
    class Input:
        running=False
        def start(self, game_exe, log_dir, *, elevated=False):
            self.running=True; calls.append(('input_start',str(game_exe),elevated))
        def stop(self,wait=False):
            self.running=False; calls.append(('input_stop',wait))
        def snapshot(self): return dict(status='waiting_game',count=0,lost=0,recent=[])
    window.input_controller=Input()
    window.vision_controller.stop()
    window.vision_controller=SimpleNamespace(
        game_exe=None,set_enabled=lambda value:calls.append(('vision',value)),
        set_identity=lambda *a:None,take_snapshot=lambda:None,
        state={'status':'等待游戏窗口'},stop=lambda:None)
    assert not window.service_controller.is_running()
    window._toggle_input_recording()
    assert window.input_controller.running
    assert ('input_start',str(window._game_executable()),True) in calls
    assert not window.service_controller.is_running()
    window._drain_independent_services()
    assert '等待游戏前台' in window.home_page.input_status.text()
    assert not load_app_config(window.config_path).input_recording_enabled
    assert not load_app_config(window.config_path).start_input_recording_on_launch
    combo=OverlayEntry('visual','连携',OverlaySourceType.BUILTIN,'combo_skill',True,False,False)
    window.overlay_manager.apply_entry(combo)
    assert ('vision',True) in calls
    count=len(calls)
    window.overlay_manager.apply_entry(replace(combo,hidden=True))
    assert not any(c==('vision',False) for c in calls[count:])
    window.overlay_manager.apply_entry(replace(combo,enabled=False))
    assert calls[-1]==('vision',False)
    assert window.input_controller.running
    window._toggle_input_recording()
    assert not window.input_controller.running
    assert not load_app_config(window.config_path).input_recording_enabled




def test_native_analysis_evidence_filter_preserves_canonical_snapshot(app):
    snapshot=sample();original=deepcopy(snapshot)
    owner=snapshot['participants'][0]['character_key']
    evidence=dict(settings={},raw=[],warnings=[],actions=[
        dict(action='skill',character_key=owner,start_ms=100,end_ms=300,interrupted=False,tooltip='蓝色战技输入'),
        dict(action='ultimate',character_key=owner,start_ms=400,end_ms=900,interrupted=True,tooltip='中断终结技'),
        dict(action='combo',character_key=None,start_ms=1000,end_ms=1100,interrupted=False,tooltip='全局连携')])
    dialog=BattleDetailDialog(snapshot,'输入证据合成验证')
    try:
        dialog.show();dialog.timeline.set_input_evidence(evidence)
        assert dialog.timeline.input_markers==3
        tips=[item.toolTip() for item in dialog.timeline.scene().items()]
        assert '蓝色战技输入' in tips and '中断终结技' in tips
        dialog.timeline.set_filter('unselected',False)
        assert not dialog.timeline._role_cells
        assert dialog.timeline.input_markers == 0
        dialog.timeline.set_input_evidence(dict(actions=[],raw=[],settings={}))
        assert dialog.timeline.input_markers == 0
        assert snapshot==original
    finally:
        dialog.close();dialog.deleteLater();app.processEvents()
