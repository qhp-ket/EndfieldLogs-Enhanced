from __future__ import annotations
import socket
import threading
import dpkt
import logging
from typing import Callable
from endfield_pcap.models import CapturedPacket, Endpoint, FlowKey
from endfield_pcap.capture.npcap import (
    LOGGER,
    DEFAULT_BPF_FILTER,
    pcap_stat,
    DeviceInfo,
    build_flow_bpf,
    _device_preference_score,
    _format_device_list,
    _select_requested_devices,
    _parse_ipv4_from_capture,
    Wpcap,
)


LOGGER = logging.getLogger(__name__)


class CaptureHandle:
    def __init__(
        self,
        api: Wpcap,
        device: DeviceInfo,
        bpf_filter: str,
        on_packet: Callable[[CapturedPacket], None],
    ) -> None:
        self._api = api
        self._device = device
        self._handle = api.open_live(device.name, bpf_filter)
        self._on_packet = on_packet
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"pcap:{device.name}", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._api.close(self._handle)

    def stats(self) -> pcap_stat | None:
        return self._api.stats(self._handle)

    @property
    def device(self) -> DeviceInfo:
        return self._device

    def _run(self) -> None:
        while not self._stop.is_set():
            packet = self._api.next_packet(self._handle)
            if packet is None:
                continue
            timestamp_ms, raw = packet
            try:
                ip = _parse_ipv4_from_capture(raw)
                if ip is None:
                    continue
                tcp = ip.data
                if not isinstance(tcp, dpkt.tcp.TCP) or not tcp.data:
                    continue
                captured = CapturedPacket(
                    timestamp_ms=timestamp_ms,
                    src=Endpoint(socket.inet_ntoa(ip.src), int(tcp.sport)),
                    dst=Endpoint(socket.inet_ntoa(ip.dst), int(tcp.dport)),
                    seq=int(tcp.seq),
                    payload=bytes(tcp.data),
                    device_name=self._device.name,
                )
            except (dpkt.UnpackError, ValueError):
                continue
            self._on_packet(captured)

class CaptureManager:
    def __init__(self, api: Wpcap, devices: list[DeviceInfo], on_packet: Callable[[CapturedPacket], None]) -> None:
        self._api = api
        self._default_devices = list(devices)
        self._on_packet = on_packet
        self._lock = threading.Lock()
        self._locked_flow: FlowKey | None = None
        self._locked_device_name: str | None = None
        self._handles = self._build_handles(devices, DEFAULT_BPF_FILTER)

    @classmethod
    def create(cls, requested_device: str, on_packet: Callable[[CapturedPacket], None]) -> "CaptureManager":
        api = Wpcap()
        devices = api.list_devices()
        selected = _select_requested_devices(devices, requested_device)
        if not selected:
            raise RuntimeError(
                f"no Npcap devices matched {requested_device!r}. Available devices:\n{_format_device_list(devices)}"
            )
        LOGGER.info("opening %d Npcap device(s)", len(selected))
        return cls(api, selected, on_packet)

    def start(self) -> None:
        for handle in self._snapshot_handles():
            handle.start()

    def stop(self) -> None:
        with self._lock:
            handles = self._handles
            self._handles = []
            self._locked_flow = None
            self._locked_device_name = None
        for handle in handles:
            handle.stop()

    def lock_to_flow(self, flow: FlowKey, observed_device_names: set[str]) -> None:
        with self._lock:
            if self._locked_flow == flow and self._locked_device_name is not None:
                return
            device = self._select_device(flow, observed_device_names)
            if device is None:
                LOGGER.warning(
                    "could not determine capture device for flow %s:%d -> %s:%d; keeping broad capture",
                    flow.client.ip,
                    flow.client.port,
                    flow.server.ip,
                    flow.server.port,
                )
                return
            bpf_filter = build_flow_bpf(flow)
            new_handles = self._build_handles([device], bpf_filter)
            old_handles = self._handles
            self._handles = new_handles
            self._locked_flow = flow
            self._locked_device_name = device.name
        LOGGER.info("locking capture to device %s with exact flow BPF", device.name)
        for handle in new_handles:
            handle.start()
        for handle in old_handles:
            handle.stop()

    def restore_default_filters(self) -> None:
        with self._lock:
            if self._locked_flow is None and len(self._handles) == len(self._default_devices):
                return
            new_handles = self._build_handles(self._default_devices, DEFAULT_BPF_FILTER)
            old_handles = self._handles
            self._handles = new_handles
            self._locked_flow = None
            self._locked_device_name = None
        LOGGER.info("restoring discovery capture across %d device(s)", len(new_handles))
        for handle in new_handles:
            handle.start()
        for handle in old_handles:
            handle.stop()

    def stats_snapshot(self) -> dict[str, int]:
        recv = 0
        drop = 0
        ifdrop = 0
        for handle in self._snapshot_handles():
            stats = handle.stats()
            if stats is None:
                continue
            recv += int(stats.ps_recv)
            drop += int(stats.ps_drop)
            ifdrop += int(stats.ps_ifdrop)
        return {"ps_recv": recv, "ps_drop": drop, "ps_ifdrop": ifdrop}

    def device_snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "name": handle.device.name,
                "description": handle.device.description,
                "ipv4_addrs": list(handle.device.ipv4_addrs),
            }
            for handle in self._snapshot_handles()
        ]

    def _build_handles(self, devices: list[DeviceInfo], bpf_filter: str) -> list[CaptureHandle]:
        handles: list[CaptureHandle] = []
        errors: list[str] = []
        for device in devices:
            try:
                handles.append(CaptureHandle(self._api, device, bpf_filter, self._on_packet))
            except Exception as exc:
                errors.append(f"{device.name} ({device.description or '-'}) -> {type(exc).__name__}: {exc}")
                LOGGER.warning("failed to open capture device %s: %s", device.name, exc)
        if handles:
            return handles
        if errors:
            raise RuntimeError("failed to open any selected Npcap devices:\n" + "\n".join(errors))
        return []

    def _snapshot_handles(self) -> list[CaptureHandle]:
        with self._lock:
            return list(self._handles)

    def _select_device(self, flow: FlowKey, observed_device_names: set[str]) -> DeviceInfo | None:
        exact_ip_matches = [device for device in self._default_devices if flow.client.ip in device.ipv4_addrs]
        if exact_ip_matches:
            candidates = exact_ip_matches
        elif observed_device_names:
            candidates = [device for device in self._default_devices if device.name in observed_device_names]
        else:
            candidates = list(self._default_devices)
        if not candidates:
            return None
        candidates.sort(key=lambda device: _device_preference_score(device, observed_device_names), reverse=True)
        return candidates[0]
