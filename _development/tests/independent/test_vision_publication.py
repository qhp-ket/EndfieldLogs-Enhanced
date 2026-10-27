"""Visual updates and Qt resource ownership remain bounded across state changes."""
from copy import deepcopy
from types import SimpleNamespace
from endfield_pcap.vision.controller import VisionController


def test_timing_only_changes_are_not_published_but_identity_and_state_are(app):
    controller=VisionController('unused.exe')
    controller.hwnd=1
    state=dict(target_hwnd=1,frame_valid=True,status='识别中',layout='keyboard',
               processing_ms=1,published_mono=1,slots=[dict(slot=0,status='ready',progress=1.,
               estimated_remaining_ms=0,stale=False,held=False)])
    controller.receive(state)
    first=controller.take_snapshot()
    assert first['sequence']==1
    for i in range(20):
        controller.receive(dict(state,processing_ms=i,published_mono=i))
        assert controller.take_snapshot() is None
    controller.set_identity([SimpleNamespace(squad_index=0,templateid='char_1',display_name='角色')],'session')
    assert controller.take_snapshot()['snapshot']['slots'][0]['character_key']=='char_1'
    changed=deepcopy(state)
    changed['slots'][0].update(status='cooldown',progress=0.)
    controller.receive(changed)
    assert controller.take_snapshot()['snapshot']['slots'][0]['status']=='cooldown'
    controller.deleteLater()


def test_stop_is_nonblocking_and_reenable_waits_for_old_worker(app, monkeypatch):
    import threading
    from PySide6.QtCore import QObject, Signal, Slot
    from app_test_support.scenarios.trace import wait_for
    from endfield_pcap.vision import capture

    release = threading.Event()
    started, stopped = [], []
    class Worker(QObject):
        result = Signal(object)
        preview = Signal(object)

        def __init__(self, config):
            super().__init__()

        @Slot()
        def start(self):
            started.append(True)

        @Slot()
        def stop(self):
            assert release.wait(5)
            stopped.append(True)
            self.thread().quit()

        @Slot(object)
        def target(self, value): pass

        @Slot(object)
        def configure(self, value): pass

        @Slot(bool)
        def set_preview(self, value): pass

    monkeypatch.setattr(capture, 'CaptureWorker', Worker)
    controller = VisionController('unused.exe')
    monkeypatch.setattr(controller, 'discover', lambda: None)
    try:
        controller.set_enabled(True)
        wait_for(lambda: len(started) == 1, app)
        first = controller.thread
        controller.stop()
        assert controller.thread is first and controller.is_running()
        controller.receive({'target_hwnd': None, 'slots': []})
        assert controller.take_snapshot() is None
        controller.set_enabled(True)
        assert controller.thread is first and len(started) == 1
        release.set()
        wait_for(lambda: len(started) == 2, app)
        assert controller.thread is not first and stopped == [True]
    finally:
        release.set()
        controller.stop()
        wait_for(lambda: controller.thread is None, app)
        controller.deleteLater()
