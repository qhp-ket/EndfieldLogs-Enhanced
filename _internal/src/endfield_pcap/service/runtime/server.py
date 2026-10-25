from __future__ import annotations
import asyncio
import json
import threading
import websockets
import logging
from collections import defaultdict, deque
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from endfield_pcap.crypto.srsa_bridge import SRSABridge
from endfield_pcap.data.names import load_name_index
from endfield_pcap.capture.registry import MessageRegistry
from endfield_pcap.models import (
    CapturedPacket,
    FlowKey,
    OutboundEvent,
    RuntimeMetrics,
    ServiceObserver,
    ServiceState,
)
from endfield_pcap.capture.manager import CaptureManager
from endfield_pcap.capture.protocol import load_private_key_from_txt
from endfield_pcap.runtime.paths import bundle_root
from endfield_pcap.trace.bridge import TraceBridge, make_archive_trace_file
from endfield_pcap.analysis.live.publisher import SnapshotPublisher
from endfield_pcap.analysis.buffs import BuffDisplayPublisher
from endfield_pcap.analysis.activity import DeferredDisplayInputs
from endfield_pcap.service.session.helpers import _load_multi_phase_dungeon_map
from endfield_pcap.service.config import ServiceConfig
from endfield_pcap.service.session.pipeline import SessionPipeline
from endfield_pcap.service.runtime.websocket import WebSocketDelivery
from endfield_pcap.service.runtime.analysis import AnalysisStreams
from endfield_pcap.service.runtime.flow import FlowCapture
from endfield_pcap.service.runtime.debug import DebugOutput


LOGGER = logging.getLogger(__name__)


class DamageLogService(WebSocketDelivery, AnalysisStreams, FlowCapture, DebugOutput):
    def __init__(self, config: ServiceConfig, observer: ServiceObserver | None = None) -> None:
        self.config = config
        self.observer = observer
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._started_event = threading.Event()
        self._fatal_exception: BaseException | None = None
        self._fatal_error: dict[str, str] | None = None
        self.state = ServiceState.WAITING_GAME
        self.metrics = RuntimeMetrics()
        self.packet_queue: asyncio.Queue[CapturedPacket] = asyncio.Queue(maxsize=20000)
        self.clients: set[Any] = set()
        self.snapshot_publisher = SnapshotPublisher(use_process=True, minimum_interval=1.0)
        self.summary_publisher = SnapshotPublisher(use_process=True, summary=True)
        self._client_senders = {}
        self._summary_clients = set()
        self._custom_full = False
        self._full_handshakes = 0
        self._full_demand_changed = asyncio.Event()
        self._analysis_demand_changed = asyncio.Event()
        self._analysis_streams = None  # Standalone service retains its default streams.
        self._summary_handshakes = 0
        self.buff_publisher = BuffDisplayPublisher()
        self._buff_inputs = DeferredDisplayInputs(lambda: self.buff_publisher)
        self._last_buff_message = None
        self._analysis_delivery_lock = asyncio.Lock()
        self.registry = MessageRegistry(bundle_root() / "data")
        self.name_index = load_name_index(config.name_index_path)
        self.multi_phase_dungeon_map = _load_multi_phase_dungeon_map(bundle_root() / "jsondata" / "Dungeon.json")
        self.private_key = load_private_key_from_txt(config.rsa_key_txt)
        self.srsa_bridge = SRSABridge(config.dll_dir)
        self.pending_packets: dict[FlowKey, deque[CapturedPacket]] = defaultdict(lambda: deque(maxlen=8192))
        self.active_flow: FlowKey | None = None
        self.active_session: SessionPipeline | None = None
        self._active_flow_capture_locked = False
        self.batch: list[dict[str, object]] = []
        self.log_file = None
        self.current_log_path: Path | None = None
        self.log_write_errors = 0
        self.debug_session_dir: Path | None = None
        self.debug_counters: dict[tuple[str, str], int] = defaultdict(int)
        self.server = None
        if config.trace_enabled:
            if config.trace_file is None:
                config.trace_file = make_archive_trace_file(config.log_dir)
            self.trace_bridge = TraceBridge(config.trace_file, line_sink=self._handle_trace_line)
            # Source GUI constructs the service directly instead of runner.py.
            # The official uploader recognizes managed traces by this sidecar.
            if config.status_file is None:
                config.status_file = config.trace_file.with_suffix(config.trace_file.suffix + ".status.json")
        else:
            self.trace_bridge = TraceBridge(write_enabled=False, line_sink=self._handle_trace_line)
        self.status_file = config.status_file
        if self.status_file is not None:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
        # Open native handles after fallible trace/directory initialization.
        self.capture_manager = CaptureManager.create(config.npcap_device, self._on_packet_from_thread)
        if self.status_file is not None:
            self._write_status()

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self.snapshot_publisher.reset(new_stream=True)
        self.summary_publisher.reset(new_stream=True)
        self.buff_publisher.reset(new_stream=True)
        self._buff_inputs.clear()
        try:
            await self._publish_analysis_snapshot()
            await self._publish_analysis_summary()
            await self._publish_buff_snapshot()
            self.server = await websockets.serve(self._ws_handler, "127.0.0.1", self.config.ws_port,
                                                 process_request=self._ws_process_request)
            self.capture_manager.start()
            if self._analysis_required('analysis_summary'):
                self.summary_publisher.start()
        except BaseException:
            await self.snapshot_publisher.close()
            await self.summary_publisher.close()
            self.capture_manager.stop()
            if self.server is not None:
                self.server.close()
                await self.server.wait_closed()
            if self.log_file is not None:
                self.log_file.close()
                self.log_file = None
            self.server = None
            self.loop = None
            self._stop_event = None
            raise
        self._set_state(ServiceState.WAITING_RESTART if self._game_running() else ServiceState.WAITING_GAME)
        tasks = [
            asyncio.create_task(self._process_monitor_loop(), name="process-monitor"),
            asyncio.create_task(self._packet_loop(), name="packet-loop"),
            asyncio.create_task(self._batch_flush_loop(), name="batch-flush"),
            asyncio.create_task(self._analysis_snapshot_loop(), name="analysis-snapshot"),
            asyncio.create_task(self._analysis_summary_loop(), name="analysis-summary"),
            asyncio.create_task(self._buff_snapshot_loop(), name="buff-snapshot"),
            asyncio.create_task(self._stats_loop(), name="stats-loop"),
        ]
        for task in tasks:
            task.add_done_callback(self._on_background_task_done)
        self._started_event.set()
        try:
            await self._stop_event.wait()
        finally:
            self._started_event.clear()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._reset_session()
            self.snapshot_publisher.reset()
            self.summary_publisher.reset()
            self.buff_publisher.reset()
            self._buff_inputs.clear()
            await self._publish_analysis_snapshot()
            await self._publish_analysis_summary()
            await self._publish_buff_snapshot()
            await self.snapshot_publisher.close()
            await self.summary_publisher.close()
            self.capture_manager.stop()
            if self.server is not None:
                self.server.close()
                await self.server.wait_closed()
            if self.log_file is not None:
                self.log_file.close()
                self.log_file = None
            self.server = None
            self.loop = None
            self._stop_event = None
            if self._fatal_exception is not None:
                exc = self._fatal_exception
                self._fatal_exception = None
                raise exc

    def wait_started(self, timeout: float | None = None) -> bool:
        return self._started_event.wait(timeout)

    def request_stop(self) -> None:
        if self.loop is None or self._stop_event is None:
            return
        if self.loop.is_closed():
            return
        try:
            self.loop.call_soon_threadsafe(self._stop_event.set)
        except RuntimeError:
            return

    def _on_background_task_done(self, task: asyncio.Task[None]) -> None:
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is None:
            return
        LOGGER.exception("background task failed", exc_info=exc)
        self._fatal_exception = exc
        self._fatal_error = {
            "task": task.get_name(),
            "type": type(exc).__name__,
            "message": str(exc),
        }
        # Persist the actual failure before stopping the heartbeat. The
        # overlay can then surface the cause instead of degrading it to the
        # ambiguous "capture disconnected" state.
        self._write_status()
        if self.loop is not None and self._stop_event is not None and not self._stop_event.is_set():
            if self.loop.is_closed():
                return
            try:
                self.loop.call_soon_threadsafe(self._stop_event.set)
            except RuntimeError:
                return

    def _on_packet_from_thread(self, packet: CapturedPacket) -> None:
        if self.loop is None:
            return
        self.loop.call_soon_threadsafe(self._queue_packet, packet)

    def _queue_packet(self, packet: CapturedPacket) -> None:
        self.metrics.packets_seen += 1
        try:
            self.packet_queue.put_nowait(packet)
        except asyncio.QueueFull:
            self.metrics.packets_dropped_queue += 1

    def _status_payload(self, pcap_stats: dict[str, int] | None = None) -> dict[str, object]:
        active_flow = None
        if self.active_flow is not None:
            active_flow = {
                "client": f"{self.active_flow.client.ip}:{self.active_flow.client.port}",
                "server": f"{self.active_flow.server.ip}:{self.active_flow.server.port}",
            }
        log_size = None
        if self.current_log_path is not None:
            try:
                log_size = self.current_log_path.stat().st_size
            except OSError:
                log_size = None
        return {
            "type": "status",
            "schema_version": 1,
            "state": self.state.value,
            "game_exe": self.config.game_exe,
            "session_id": self.active_session.session_id if self.active_session else None,
            "active_flow": active_flow,
            "session": self.active_session.status_snapshot() if self.active_session is not None else None,
            "log": {
                "dir": str(self.config.log_dir),
                "path": str(self.current_log_path) if self.current_log_path is not None else None,
                "size": log_size,
                "write_errors": self.log_write_errors,
            },
            "capture_devices": self.capture_manager.device_snapshot(),
            "metrics": asdict(self.metrics),
            "pcap_stats": pcap_stats or {},
            "fatal_error": self._fatal_error,
            "updated_at_ms": int(datetime.now().timestamp() * 1000),
        }

    def _write_status(self, pcap_stats: dict[str, int] | None = None) -> None:
        if self.status_file is None:
            return
        try:
            tmp_path = self.status_file.with_suffix(self.status_file.suffix + ".tmp")
            tmp_path.write_text(
                json.dumps(self._status_payload(pcap_stats), ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            tmp_path.replace(self.status_file)
        except OSError:
            LOGGER.debug("failed to write status file %s", self.status_file, exc_info=True)

    def _set_state(self, state: ServiceState) -> None:
        if self.state == state:
            return
        self.state = state
        LOGGER.info("service state -> %s", state.value)
        self._write_status()
        if self.observer is not None and self.observer.on_state_change is not None:
            self.observer.on_state_change(
                self.state,
                self.active_session.session_id if self.active_session else None,
                self.active_flow,
            )
        if self.loop is not None:
            self.loop.create_task(self._broadcast(self._hello_payload()))

    def _open_log_file(self, session_id: str) -> None:
        if self.log_file is not None:
            self.log_file.close()
        timestamp = datetime.now().strftime("%Y%m%d")
        day_dir = self.config.log_dir / timestamp
        day_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"session_{session_id}.ndjson"
        self.current_log_path = day_dir / file_name
        self.log_file = self.current_log_path.open("a", encoding="utf-8")

    def _reset_session(self) -> None:
        had_capture_session = self.active_flow is not None or self.active_session is not None
        if had_capture_session and self.trace_bridge is not None:
            self.trace_bridge.end_capture_session()
        if self.active_session is not None:
            self.active_session.flush_debug_state()
        self.active_flow = None
        self.active_session = None
        self._active_flow_capture_locked = False
        self.capture_manager.restore_default_filters()
        if self.log_file is not None:
            self.log_file.close()
            self.log_file = None
        self.current_log_path = None
        self.debug_session_dir = None
        self.debug_counters.clear()
        publisher = getattr(self, "snapshot_publisher", None)
        if had_capture_session and publisher is not None:
            publisher.reset()
            self.summary_publisher.reset()
            self.buff_publisher.reset()
            self._buff_inputs.clear()

    def _handle_trace_line(self, line: str) -> None:
        self.snapshot_publisher.feed_line(line)
        self.summary_publisher.feed_line(line)
        self._buff_inputs.feed(line, active=self._analysis_required('buff_snapshot'))

    def _handle_outbound_event(self, event: OutboundEvent) -> None:
        payload = event.as_dict()
        if self.trace_bridge is not None:
            self.trace_bridge.handle_event(payload)
        self.batch.append(payload)
        if self.observer is not None and self.observer.on_event is not None:
            self.observer.on_event(payload)
        if self.log_file is not None:
            try:
                self.log_file.write(json.dumps(payload, ensure_ascii=False) + "\n")
                self.log_file.flush()
            except OSError:
                self.log_write_errors += 1
                LOGGER.warning("failed to write combat log %s", self.current_log_path, exc_info=True)
        if len(self.batch) >= 128 and self.loop is not None:
            self.loop.create_task(self._flush_batch())

    async def _stats_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            stats = self.capture_manager.stats_snapshot()
            self._write_status(dict(stats))
            if self.observer is not None and self.observer.on_runtime_metrics is not None:
                self.observer.on_runtime_metrics(replace(self.metrics), dict(stats), self.active_flow)
            LOGGER.info(
                "metrics packets=%d queue_drop=%d frames=%d messages=%d events=%d batches=%d ps_drop=%d active_flow=%s",
                self.metrics.packets_seen,
                self.metrics.packets_dropped_queue,
                self.metrics.frames_decoded,
                self.metrics.messages_decoded,
                self.metrics.outbound_events_emitted,
                self.metrics.ws_batches_sent,
                stats["ps_drop"],
                self.active_flow,
            )
            LOGGER.info("analysis summary_ms=%.1f pending_trace_lines=%d worker=%s full_consumers=%s",
                        self.summary_publisher.last_analysis_ms,
                        len(self.summary_publisher._pending_lines),
                        self.summary_publisher.last_worker_metrics, self._has_full_consumers())
