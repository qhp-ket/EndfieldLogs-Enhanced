"""Hiding GUI must preserve services, usable recovery and bounded view caches."""
from types import SimpleNamespace
import ctypes
from ctypes import wintypes
from PySide6.QtCore import QCoreApplication,QEvent
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QDialog
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.settings import load_app_config
from endfield_pcap.gui.pages.overlays import hotkeys
from endfield_pcap.gui.lifecycle import QSystemTrayIcon


def test_tray_hide_restore_preserves_services_and_overlays(main_window,app,monkeypatch):
    window=main_window
    stopped=[]
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',lambda:True)
    monkeypatch.setattr(window.tray_icon,'show',lambda:None)
    monkeypatch.setattr(window.input_controller,'stop',lambda *a,**k:stopped.append('input'))
    monkeypatch.setattr(window.vision_controller,'stop',lambda:stopped.append('vision'))
    before=[(e.id,e.enabled,e.hidden) for e in window.app_config.overlays]
    window.home_page.hide_gui_btn.click();app.processEvents()
    assert not window.isVisible() and window.queue_timer.interval()==50
    window._toggle_gui_visibility();app.processEvents()
    assert window.isVisible() and not window.isMinimized() and window.queue_timer.interval()==33
    assert before==[(e.id,e.enabled,e.hidden) for e in window.app_config.overlays]
    assert not stopped


def test_no_tray_falls_back_to_taskbar_minimize(main_window,app,monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',lambda:False)
    minimized=[]
    # qframelesswindow queries a native HWND on minimize; offscreen Qt has none.
    monkeypatch.setattr(main_window,'showMinimized',lambda:minimized.append(True))
    main_window._hide_gui()
    assert minimized==[True] and main_window.isVisible()
    main_window._restore_gui();app.processEvents()
    assert main_window.isVisible() and not main_window.isMinimized()


def test_tray_controls_all_gui_keeps_icon_and_leaves_overlay_visible(main_window,app,monkeypatch):
    window=main_window
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',lambda:True)
    monkeypatch.setattr(window.tray_icon,'show',lambda:None)
    visible=QDialog(window);visible.show()
    previously_hidden=QDialog(window)
    overlay=QDialog();overlay.show()
    app.processEvents()
    try:
        labels=[action.text() for action in window.tray_icon.contextMenu().actions()]
        assert labels==['显示主界面','隐藏主界面','退出程序']
        icon_hides=[]
        monkeypatch.setattr(window.tray_icon,'hide',lambda:icon_hides.append(True))
        window._hide_gui();app.processEvents()
        assert not window.isVisible() and not visible.isVisible()
        assert overlay.isVisible() and not icon_hides
        window._restore_gui();app.processEvents()
        assert window.isVisible() and visible.isVisible()
        assert not previously_hidden.isVisible() and overlay.isVisible()
        window._toggle_overlay_visibility();app.processEvents()
        assert window.isVisible() and visible.isVisible()
    finally:
        visible.close();previously_hidden.close();overlay.close()


def test_gui_hotkey_is_separate_persisted_and_dispatched(main_window,app,monkeypatch):
    window=main_window
    registry={}
    fake=SimpleNamespace(RegisterHotKey=lambda hwnd,key,mods,vk:registry.setdefault(key,(mods,vk)) is not None,
                         UnregisterHotKey=lambda hwnd,key:registry.pop(key,None))
    monkeypatch.setattr(hotkeys,'USER32',fake)
    monkeypatch.setattr(window,'_update_gui_shortcut',lambda key=None:hotkeys.OverlayHotkeys._update_gui_shortcut(window,key))
    window.settings_page.gui_hotkey_edit.setKeySequence(QKeySequence('Ctrl+Alt+G'))
    window._apply_gui_hotkey()
    assert load_app_config(window.config_path).toggle_gui_hotkey=='Ctrl+Alt+G'
    assert hotkeys.GUI_HOTKEY_ID in registry and hotkeys.GLOBAL_HOTKEY_ID not in registry
    calls=[]
    monkeypatch.setattr(window,'_toggle_gui_visibility',lambda:calls.append('gui'))
    msg=wintypes.MSG(message=hotkeys.WM_HOTKEY,wParam=hotkeys.GUI_HOTKEY_ID)
    assert window.nativeEvent(b'windows_generic_MSG',ctypes.addressof(msg))==(True,0)
    assert calls==['gui']


def test_hidden_ui_defers_log_layout_but_drains_input_and_combo(main_window,app,monkeypatch):
    window=main_window
    monkeypatch.setattr(QSystemTrayIcon,'isSystemTrayAvailable',lambda:True)
    monkeypatch.setattr(window.tray_icon,'show',lambda:None)
    window._hide_gui();app.processEvents()
    shown=window.home_page.input_status.text()
    monkeypatch.setattr(window.input_controller,'snapshot',lambda:dict(status='recording',input_received={'key':12},count=30))
    combo=dict(type='combo_snapshot',schema_version=2,stream_id='test',sequence=1,snapshot={'slots':[]})
    monkeypatch.setattr(window.vision_controller,'take_snapshot',lambda:combo)
    window.service_controller.queue.put(('log','hidden runtime evidence'))
    window._drain_queue()
    assert window.home_page.input_status.text()==shown
    assert 'hidden runtime evidence' in '\n'.join(window.logs_page._lines)
    assert not window.logs_page.log_view.toPlainText()
    assert window.overlay_manager._combo_snapshot==combo
    window._restore_gui();app.processEvents()
    assert '键盘 12' in window.home_page.input_status.text()


def test_closed_history_view_releases_full_report_and_input_archive_caches(main_window,app,tmp_path):
    from app_test_support.scenarios.compact import sample
    from endfield_pcap.inputlog import history
    window=main_window
    from endfield_pcap.history.importer import TraceCombatRecord
    record=TraceCombatRecord(tmp_path/'fixture.log',1,1,'fixture',snapshot={'retained':'full report'})
    window.history_controller._trace_records={'fixture':[record]}
    window.history_controller.detail_snapshot=sample();window.history_controller.detail_key='fixture'
    with history._lock: history._cache['test']=object()
    window.history_presenter._show_detail(window.history_controller.detail_snapshot,record)
    dialog=window.history_presenter.dialog
    destroyed=[];dialog.destroyed.connect(lambda:destroyed.append(True))
    dialog.close()
    QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete);app.processEvents()
    assert destroyed
    assert window.history_presenter.dialog is None and window.history_controller.detail_snapshot is None
    assert record.snapshot=={} and not history._cache
