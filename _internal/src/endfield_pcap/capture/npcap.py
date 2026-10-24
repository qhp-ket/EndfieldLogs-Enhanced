from __future__ import annotations
import ctypes
import logging
import socket
import dpkt
from ctypes import POINTER
from dataclasses import dataclass
from endfield_pcap.models import FlowKey


LOGGER = logging.getLogger(__name__)

PCAP_ERRBUF_SIZE = 256

PCAP_IF_LOOPBACK = 0x00000001

DEFAULT_BPF_FILTER = "tcp port 30000"

DEFAULT_SNAPLEN = 65535

DEFAULT_PROMISC = 0

DEFAULT_TIMEOUT_MS = 100

DEFAULT_BUFFER_SIZE = 32 * 1024 * 1024

_AUTO_NO_IPV4_DESCRIPTION_HINTS = (
    "wan miniport (ip)",
    "ndiswan",
    "ppp adapter",
)

def has_npcap() -> bool:
    try:
        ctypes.WinDLL("wpcap.dll")
    except OSError:
        return False
    return True

class timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]

class pcap_pkthdr(ctypes.Structure):
    _fields_ = [("ts", timeval), ("caplen", ctypes.c_uint32), ("len", ctypes.c_uint32)]

class sockaddr(ctypes.Structure):
    _fields_ = [("sa_family", ctypes.c_ushort), ("sa_data", ctypes.c_ubyte * 14)]

class sockaddr_in(ctypes.Structure):
    _fields_ = [
        ("sin_family", ctypes.c_short),
        ("sin_port", ctypes.c_ushort),
        ("sin_addr", ctypes.c_ubyte * 4),
        ("sin_zero", ctypes.c_ubyte * 8),
    ]

class pcap_addr_t(ctypes.Structure):
    pass

pcap_addr_t._fields_ = [
    ("next", POINTER(pcap_addr_t)),
    ("addr", POINTER(sockaddr)),
    ("netmask", POINTER(sockaddr)),
    ("broadaddr", POINTER(sockaddr)),
    ("dstaddr", POINTER(sockaddr)),
]

class pcap_if_t(ctypes.Structure):
    pass

pcap_if_t._fields_ = [
    ("next", POINTER(pcap_if_t)),
    ("name", ctypes.c_char_p),
    ("description", ctypes.c_char_p),
    ("addresses", POINTER(pcap_addr_t)),
    ("flags", ctypes.c_uint32),
]

class bpf_program(ctypes.Structure):
    _fields_ = [("bf_len", ctypes.c_uint32), ("bf_insns", ctypes.c_void_p)]

class pcap_stat(ctypes.Structure):
    _fields_ = [("ps_recv", ctypes.c_uint), ("ps_drop", ctypes.c_uint), ("ps_ifdrop", ctypes.c_uint)]

@dataclass(slots=True)
class DeviceInfo:
    name: str
    description: str | None
    ipv4_addrs: list[str]
    flags: int

def build_flow_bpf(flow: FlowKey) -> str:
    client = flow.client
    server = flow.server
    return (
        "tcp and ("
        f"(src host {client.ip} and src port {client.port} and dst host {server.ip} and dst port {server.port}) or "
        f"(src host {server.ip} and src port {server.port} and dst host {client.ip} and dst port {client.port})"
        ")"
    )

def _device_preference_score(device: DeviceInfo, observed_device_names: set[str]) -> tuple[int, int, str]:
    description = (device.description or "").lower()
    score = 0
    if device.name in observed_device_names:
        score += 100
    if "virtual" in description or "vmware" in description or "hyper-v" in description:
        score -= 20
    if "ethernet" in description or "wi-fi" in description or "wireless" in description:
        score += 5
    return (score, len(device.ipv4_addrs), device.name)

def _format_device_list(devices: list[DeviceInfo]) -> str:
    lines = []
    for index, device in enumerate(devices, 1):
        lines.append(
            f"[{index}] name={device.name} desc={device.description or '-'} "
            f"ipv4={','.join(device.ipv4_addrs) or '-'}"
        )
    return "\n".join(lines)

def _is_auto_capture_device(device: DeviceInfo) -> bool:
    if device.flags & PCAP_IF_LOOPBACK:
        return True
    if device.ipv4_addrs:
        return True
    description = (device.description or "").casefold()
    return any(hint in description for hint in _AUTO_NO_IPV4_DESCRIPTION_HINTS)

def _select_requested_devices(devices: list[DeviceInfo], requested_device: str) -> list[DeviceInfo]:
    requested = str(requested_device or "auto").strip().strip('"').strip("'")
    if requested.casefold() == "auto":
        return [device for device in devices if _is_auto_capture_device(device)]

    if requested.isdigit():
        index = int(requested)
        if 1 <= index <= len(devices):
            return [devices[index - 1]]
        return []

    pattern = requested.casefold()
    selected = []
    for device in devices:
        haystack = [
            device.name,
            device.description or "",
            *device.ipv4_addrs,
        ]
        if any(pattern in item.casefold() for item in haystack):
            selected.append(device)
    return selected

def _parse_ipv4_from_capture(raw: bytes) -> dpkt.ip.IP | None:
    if not raw:
        return None

    try:
        eth = dpkt.ethernet.Ethernet(raw)
    except (dpkt.UnpackError, ValueError):
        eth = None
    if eth is not None and isinstance(eth.data, dpkt.ip.IP):
        return eth.data

    version = raw[0] >> 4
    if version == 4:
        try:
            return dpkt.ip.IP(raw)
        except (dpkt.UnpackError, ValueError):
            pass

    for offset in (4, 14, 16):
        if len(raw) <= offset or raw[offset] >> 4 != 4:
            continue
        try:
            return dpkt.ip.IP(raw[offset:])
        except (dpkt.UnpackError, ValueError):
            continue
    return None

class Wpcap:
    def __init__(self) -> None:
        self._dll = ctypes.WinDLL("wpcap.dll")
        self._dll.pcap_findalldevs.argtypes = [POINTER(POINTER(pcap_if_t)), ctypes.c_char_p]
        self._dll.pcap_findalldevs.restype = ctypes.c_int
        self._dll.pcap_freealldevs.argtypes = [POINTER(pcap_if_t)]
        self._dll.pcap_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        self._dll.pcap_create.restype = ctypes.c_void_p
        self._dll.pcap_set_snaplen.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._dll.pcap_set_snaplen.restype = ctypes.c_int
        self._dll.pcap_set_promisc.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._dll.pcap_set_promisc.restype = ctypes.c_int
        self._dll.pcap_set_timeout.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._dll.pcap_set_timeout.restype = ctypes.c_int
        self._dll.pcap_set_buffer_size.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._dll.pcap_set_buffer_size.restype = ctypes.c_int
        self._dll.pcap_activate.argtypes = [ctypes.c_void_p]
        self._dll.pcap_activate.restype = ctypes.c_int
        self._dll.pcap_open_live.argtypes = [
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_char_p,
        ]
        self._dll.pcap_open_live.restype = ctypes.c_void_p
        self._dll.pcap_next_ex.argtypes = [
            ctypes.c_void_p,
            POINTER(POINTER(pcap_pkthdr)),
            POINTER(POINTER(ctypes.c_ubyte)),
        ]
        self._dll.pcap_next_ex.restype = ctypes.c_int
        self._dll.pcap_close.argtypes = [ctypes.c_void_p]
        self._dll.pcap_compile.argtypes = [
            ctypes.c_void_p,
            POINTER(bpf_program),
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_uint32,
        ]
        self._dll.pcap_compile.restype = ctypes.c_int
        self._dll.pcap_setfilter.argtypes = [ctypes.c_void_p, POINTER(bpf_program)]
        self._dll.pcap_setfilter.restype = ctypes.c_int
        self._dll.pcap_freecode.argtypes = [POINTER(bpf_program)]
        self._dll.pcap_stats.argtypes = [ctypes.c_void_p, POINTER(pcap_stat)]
        self._dll.pcap_stats.restype = ctypes.c_int
        self._dll.pcap_geterr.argtypes = [ctypes.c_void_p]
        self._dll.pcap_geterr.restype = ctypes.c_char_p

    def list_devices(self) -> list[DeviceInfo]:
        alldevs = POINTER(pcap_if_t)()
        errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        result = self._dll.pcap_findalldevs(ctypes.byref(alldevs), errbuf)
        if result != 0:
            raise RuntimeError(errbuf.value.decode("utf-8", errors="replace"))

        devices: list[DeviceInfo] = []
        try:
            current = alldevs
            while current:
                raw = current.contents
                ipv4_addrs: list[str] = []
                addr_node = raw.addresses
                while addr_node:
                    addr = addr_node.contents.addr
                    if addr and addr.contents.sa_family == socket.AF_INET:
                        ipv4 = ctypes.cast(addr, POINTER(sockaddr_in)).contents
                        ipv4_addrs.append(socket.inet_ntoa(bytes(ipv4.sin_addr)))
                    addr_node = addr_node.contents.next
                devices.append(
                    DeviceInfo(
                        name=raw.name.decode("utf-8", errors="replace"),
                        description=raw.description.decode("utf-8", errors="replace") if raw.description else None,
                        ipv4_addrs=ipv4_addrs,
                        flags=int(raw.flags),
                    )
                )
                current = raw.next
        finally:
            self._dll.pcap_freealldevs(alldevs)
        return devices

    def open_live(self, device_name: str, bpf_filter: str) -> ctypes.c_void_p:
        try:
            return self._open_activated(device_name, bpf_filter)
        except Exception as exc:
            LOGGER.warning("pcap_create/activate failed for %s, falling back to open_live: %s", device_name, exc)
            return self._open_live_fallback(device_name, bpf_filter)

    def _open_activated(self, device_name: str, bpf_filter: str) -> ctypes.c_void_p:
        errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        handle = self._dll.pcap_create(device_name.encode("utf-8"), errbuf)
        if not handle:
            raise RuntimeError(errbuf.value.decode("utf-8", errors="replace"))
        try:
            self._check_status(handle, self._dll.pcap_set_snaplen(handle, DEFAULT_SNAPLEN), "pcap_set_snaplen")
            self._check_status(handle, self._dll.pcap_set_promisc(handle, DEFAULT_PROMISC), "pcap_set_promisc")
            self._check_status(handle, self._dll.pcap_set_timeout(handle, DEFAULT_TIMEOUT_MS), "pcap_set_timeout")
            self._check_status(
                handle,
                self._dll.pcap_set_buffer_size(handle, DEFAULT_BUFFER_SIZE),
                "pcap_set_buffer_size",
            )
            self._check_status(handle, self._dll.pcap_activate(handle), "pcap_activate")
            self._apply_bpf_filter(handle, bpf_filter)
            LOGGER.info(
                "opened %s via pcap_create/activate buffer=%d timeout_ms=%d",
                device_name,
                DEFAULT_BUFFER_SIZE,
                DEFAULT_TIMEOUT_MS,
            )
            return handle
        except Exception:
            self._dll.pcap_close(handle)
            raise

    def _open_live_fallback(self, device_name: str, bpf_filter: str) -> ctypes.c_void_p:
        errbuf = ctypes.create_string_buffer(PCAP_ERRBUF_SIZE)
        handle = self._dll.pcap_open_live(
            device_name.encode("utf-8"),
            DEFAULT_SNAPLEN,
            DEFAULT_PROMISC,
            DEFAULT_TIMEOUT_MS,
            errbuf,
        )
        if not handle:
            raise RuntimeError(errbuf.value.decode("utf-8", errors="replace"))
        try:
            self._apply_bpf_filter(handle, bpf_filter)
            LOGGER.info("opened %s via pcap_open_live timeout_ms=%d", device_name, DEFAULT_TIMEOUT_MS)
            return handle
        except Exception:
            self._dll.pcap_close(handle)
            raise

    def _apply_bpf_filter(self, handle: ctypes.c_void_p, bpf_filter: str) -> None:
        program = bpf_program()
        result = self._dll.pcap_compile(handle, ctypes.byref(program), bpf_filter.encode("utf-8"), 1, 0xFFFFFFFF)
        if result != 0:
            message = self._dll.pcap_geterr(handle).decode("utf-8", errors="replace")
            raise RuntimeError(message)
        try:
            result = self._dll.pcap_setfilter(handle, ctypes.byref(program))
            if result != 0:
                message = self._dll.pcap_geterr(handle).decode("utf-8", errors="replace")
                raise RuntimeError(message)
        finally:
            self._dll.pcap_freecode(ctypes.byref(program))

    def _check_status(self, handle: ctypes.c_void_p, result: int, operation: str) -> None:
        if result == 0:
            return
        message = self._dll.pcap_geterr(handle)
        decoded = message.decode("utf-8", errors="replace") if message else f"{operation} failed with code {result}"
        raise RuntimeError(decoded)

    def close(self, handle: ctypes.c_void_p) -> None:
        self._dll.pcap_close(handle)

    def stats(self, handle: ctypes.c_void_p) -> pcap_stat | None:
        value = pcap_stat()
        if self._dll.pcap_stats(handle, ctypes.byref(value)) != 0:
            return None
        return value

    def next_packet(self, handle: ctypes.c_void_p) -> tuple[int, bytes] | None:
        header_ptr = POINTER(pcap_pkthdr)()
        data_ptr = POINTER(ctypes.c_ubyte)()
        result = self._dll.pcap_next_ex(handle, ctypes.byref(header_ptr), ctypes.byref(data_ptr))
        if result <= 0:
            return None
        header = header_ptr.contents
        packet_data = ctypes.string_at(data_ptr, header.caplen)
        timestamp_ms = int(header.ts.tv_sec * 1000 + header.ts.tv_usec / 1000)
        return timestamp_ms, packet_data
