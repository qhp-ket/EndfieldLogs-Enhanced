"""Native capture ownership across startup failure and bounded shutdown."""
import asyncio
import threading

import dpkt
import pytest

from app_test_support.runtime.service import service_factory
from endfield_pcap.capture.manager import CaptureHandle, CaptureManager
from endfield_pcap.capture.npcap import DEFAULT_BPF_FILTER, DeviceInfo
from endfield_pcap.models import Endpoint, FlowKey
import endfield_pcap.service.runtime.server as service_module


DEVICES = [DeviceInfo(f"device-{i}", None, [f"192.0.2.{i}"], 0) for i in (1, 2)]


class FakePcap:
    def __init__(self):
        self.opened = []
        self.closed = []
        self.reading = set()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.stats_calls = []

    def open_live(self, name, bpf_filter):
        handle = len(self.opened) + 1
        self.opened.append(handle)
        return handle

    def next_packet(self, handle):
        self.reading.add(handle)
        self.entered.set()
        try:
            self.release.wait(.01)
            return None
        finally:
            self.reading.remove(handle)

    def close(self, handle):
        assert handle not in self.reading, "closed while native read was active"
        assert handle not in self.closed, "native handle closed twice"
        self.closed.append(handle)

    def stats(self, handle):
        assert handle not in self.closed
        self.stats_calls.append(handle)
        return None


def make_handle(api, callback=lambda packet: None):
    return CaptureHandle(api, DEVICES[0], DEFAULT_BPF_FILTER, callback)


def test_stop_before_start_is_idempotent_and_stats_do_not_use_closed_handle():
    api = FakePcap()
    handle = make_handle(api)
    handle.stats()
    handle.stop()
    handle.stop()
    assert handle.stats() is None
    assert api.closed == api.opened == [1]
    assert api.stats_calls == [1]
    with pytest.raises(RuntimeError, match="stopped"):
        handle.start()


def test_started_handle_closes_once_and_repeated_start_is_safe():
    api = FakePcap()
    handle = make_handle(api)
    try:
        handle.start()
        assert api.entered.wait(1)
        handle.start()
    finally:
        handle.stop()
    handle.stop()
    assert api.closed == [1]


def test_stop_timeout_defers_close_until_native_read_returns(monkeypatch, caplog):
    api = FakePcap()
    reading = threading.Event()

    def blocked_read(native):
        api.reading.add(native)
        reading.set()
        try:
            assert api.release.wait(5), "test did not release blocked read"
            return None
        finally:
            api.reading.remove(native)

    api.next_packet = blocked_read
    handle = make_handle(api)
    original_join = handle._thread.join
    handle.start()
    try:
        assert reading.wait(1)
        monkeypatch.setattr(handle._thread, "join", lambda timeout: None)
        handle.stop()
        assert not api.closed
        assert "deferred" in caplog.text
        assert handle.stats() is None
    finally:
        api.release.set()
        original_join(2)
    assert not handle._thread.is_alive()
    assert api.closed == [1]
    handle.stop()


def test_worker_error_releases_native_handle(monkeypatch):
    api = FakePcap()
    handle = make_handle(api)
    error = OSError("native read failed")

    def fail(native):
        raise error

    monkeypatch.setattr(api, "next_packet", fail)
    # Call synchronously to assert the actual exception without an unhandled
    # thread warning obscuring ownership verification.
    with pytest.raises(OSError) as caught:
        handle._run()
    assert caught.value is error
    assert api.closed == [1]
    handle.stop()


def test_packet_delivery_can_stop_its_own_worker():
    api = FakePcap()
    packet = dpkt.ip.IP(src=b"\xc0\x00\x02\x01", dst=b"\xc0\x00\x02\x03", p=6,
                        data=dpkt.tcp.TCP(sport=40000, dport=30000, seq=7, data=b"payload"))
    api.next_packet = lambda native: (1234, bytes(packet))
    received = []

    def deliver(captured):
        received.append(captured)
        handle.stop()

    handle = make_handle(api, deliver)
    handle.start()
    handle._thread.join(2)
    assert not handle._thread.is_alive()
    assert len(received) == 1
    assert received[0].timestamp_ms == 1234 and received[0].payload == b"payload"
    assert received[0].device_name == DEVICES[0].name
    assert api.closed == [1]


@pytest.mark.parametrize("failure", ["trace", "status_directory"])
def test_service_constructor_failure_does_not_open_native_handles(service_factory, monkeypatch, tmp_path, failure):
    api = FakePcap()
    monkeypatch.setattr(service_module.CaptureManager, "create",
                        lambda _, callback: CaptureManager(api, DEVICES, callback))
    if failure == "trace":
        def fail(*args, **kwargs):
            raise OSError("trace initialization failed")
        monkeypatch.setattr(service_module, "TraceBridge", fail)
        with pytest.raises(OSError, match="trace initialization failed"):
            service_factory(trace_enabled=True)
    else:
        blocked = tmp_path / "blocked"
        blocked.write_text("file", encoding="utf-8")
        with pytest.raises(OSError):
            service_factory(status_file=blocked / "status.json")
    assert not api.opened


def test_manager_partial_start_failure_closes_started_and_unstarted_handles(monkeypatch):
    api = FakePcap()
    manager = CaptureManager(api, DEVICES, lambda packet: None)
    handles = manager._snapshot_handles()
    error = RuntimeError("thread start failed")

    def fail():
        raise error

    monkeypatch.setattr(handles[1]._thread, "start", fail)
    try:
        with pytest.raises(RuntimeError) as caught:
            manager.start()
        assert caught.value is error
        assert sorted(api.closed) == api.opened == [1, 2]
        assert not handles[0]._thread.is_alive()
    finally:
        manager.stop()


def test_manager_cleanup_attempts_every_handle_after_close_error(monkeypatch, caplog):
    api = FakePcap()
    manager = CaptureManager(api, DEVICES, lambda packet: None)
    original_close = api.close

    def close(native):
        original_close(native)
        if native == 1:
            raise OSError("synthetic close failure")

    monkeypatch.setattr(api, "close", close)
    manager.stop()
    manager.stop()
    assert api.closed == [1, 2]
    assert "synthetic close failure" in caplog.text
    assert not manager.device_snapshot()


@pytest.mark.parametrize("restore", [False, True])
def test_filter_replacement_start_failure_releases_both_generations(monkeypatch, restore):
    api = FakePcap()
    manager = CaptureManager(api, DEVICES, lambda packet: None)
    manager.start()
    flow = FlowKey(Endpoint("192.0.2.1", 40000), Endpoint("192.0.2.3", 30000))
    if restore:
        manager.lock_to_flow(flow, {DEVICES[0].name})
    original_start = CaptureHandle.start

    def fail_new(handle):
        if handle._handle == len(api.opened):
            raise RuntimeError("replacement start failed")
        original_start(handle)

    monkeypatch.setattr(CaptureHandle, "start", fail_new)
    try:
        with pytest.raises(RuntimeError, match="replacement start failed"):
            if restore:
                manager.restore_default_filters()
            else:
                manager.lock_to_flow(flow, {DEVICES[0].name})
        assert sorted(api.closed) == api.opened
    finally:
        manager.stop()


def test_ws_bind_failure_preserves_original_error_and_closes_unstarted_capture(service_factory, monkeypatch):
    async def scenario():
        service = service_factory()
        api = FakePcap()
        service.capture_manager = CaptureManager(api, DEVICES, service._on_packet_from_thread)
        error = OSError("synthetic address already in use")

        async def fail(*args, **kwargs):
            raise error

        monkeypatch.setattr(service_module.websockets, "serve", fail)
        with pytest.raises(OSError) as caught:
            await service.run()
        assert caught.value is error
        assert api.closed == api.opened == [1, 2]
        assert service.server is None and service.loop is None
        assert service._stop_event is None
        assert not service.wait_started(0)

    asyncio.run(scenario())
