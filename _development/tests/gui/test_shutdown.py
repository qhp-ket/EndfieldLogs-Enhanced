"""Closing waits for resource ownership without blocking the Qt event loop."""
import threading
from types import SimpleNamespace
import pytest

from PySide6.QtCore import QTimer

from app_test_support.scenarios.trace import wait_for
from app_test_support.ui.window import main_window
from endfield_pcap.application.shutdown import ShutdownController


@pytest.mark.parametrize('hidden', [False, True])
def test_close_keeps_event_loop_responsive_until_capture_and_input_stop(main_window, app, monkeypatch, hidden):
    window = main_window
    entered, release = threading.Event(), threading.Event()
    capture_active = [True]
    stops, worker_threads, beats = [], [], []
    finished = []
    window.shutdownFinished.connect(lambda: finished.append(True))

    def stop_input(wait=False):
        worker_threads.append(threading.get_ident())
        assert wait
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr(window.independent_controller.input, 'stop', stop_input)
    monkeypatch.setattr(window.service_controller, 'stop', lambda: stops.append('capture'))
    monkeypatch.setattr(window.service_controller, 'is_running', lambda: capture_active[0])
    monkeypatch.setattr(window.service_controller, 'join', lambda **kwargs: (_ for _ in ()).throw(AssertionError('GUI join')))
    try:
        if hidden:
            window.hide()
        window.close()
        assert entered.wait(2)
        assert stops == ['capture'] and not window._close_ready
        assert window.isVisible() == (not hidden) and not window.queue_timer.isActive()
        QTimer.singleShot(0, lambda: beats.append(True))
        wait_for(lambda: bool(beats), app)
        assert len(worker_threads) == 1 and worker_threads[0] != threading.get_ident()
        window.independent_controller.start_input()
        assert not window.independent_controller.input.running
        release.set()
        wait_for(lambda: not window.shutdown_controller._input_thread.is_alive(), app)
        assert not window._close_ready
        capture_active[0] = False
        wait_for(lambda: bool(finished), app)
        assert not window.isVisible()
    finally:
        capture_active[0] = False
        release.set()
        wait_for(lambda: window._close_ready, app)


def test_shutdown_failure_is_reported_and_other_resource_owners_still_stop():
    calls = []
    def failed_capture():
        calls.append('capture')
        raise OSError('capture stop failed')
    def failed_input(wait=False):
        calls.append('input')
        raise OSError('input stop failed')
    independent = SimpleNamespace(
        close=lambda: calls.append('invalidate'),
        input=SimpleNamespace(stop=failed_input, running=False),
        vision=SimpleNamespace(stop=lambda: calls.append('vision'), is_running=lambda: False))
    capture = SimpleNamespace(stop=failed_capture, is_running=lambda: False)
    controller = ShutdownController(capture, independent)
    controller.begin()
    controller._input_thread.join(2)
    state = controller.poll()
    assert state.complete
    assert calls == ['invalidate', 'capture', 'vision', 'input']
    assert state.errors == ('capture：capture stop failed', 'input：input stop failed')
    controller.begin()
    assert len(calls) == 4
