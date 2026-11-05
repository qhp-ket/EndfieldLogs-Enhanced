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
from endfield_pcap.service.session.helpers import _load_multi_phase_dungeon_map
from endfield_pcap.service.config import ServiceConfig
from endfield_pcap.service.session.pipeline import SessionPipeline
from endfield_pcap.service.runtime.websocket import WebSocketDelivery
from endfield_pcap.service.runtime.analysis import AnalysisStreams
from endfield_pcap.service.runtime.flow import FlowCapture
from endfield_pcap.service.runtime.debug import DebugOutput
from endfield_pcap.service.runtime.recording import DiskRecording
from endfield_pcap.trace.recording_context import RecordingContext
from endfield_pcap.trace.recording import TraceRecording


LOGGER = logging.getLogger(__name__)


class DamageLogService(DiskRecording, WebSocketDelivery, AnalysisStreams, FlowCapture, DebugOutput):
    def __init__(self, config: ServiceConfig, observer: ServiceObserver | None = None) -> None:
        if config.trace_format not in ('legacy', 'jsonl'):
            raise ValueError('Unsupported trace recording format')
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
        self._trace_recording = None
        self._disk_trace = None
        self._recording_context = RecordingContext()
        structured = config.trace_format == 'jsonl'
        if structured:
            from endfield_pcap.trace.recording import make_recording_header
            trace_header = make_recording_header()
        publisher_options = (dict(structured=True, timezone_offset_minutes=trace_header.timezone_offset_minutes)
                             if structured else {})
        self.snapshot_publisher = SnapshotPublisher(use_process=True, minimum_interval=1.0, **publisher_options)
        self.summary_publisher = SnapshotPublisher(use_process=True, summary=True, **publisher_options)
        self._client_senders = {}
        self._summary_clients = set()
        self._custom_full = False
        self._full_handshakes = 0
        self._full_demand_changed = asyncio.Event()
        self._analysis_demand_changed = asyncio.Event()
        self._analysis_streams = None  # Standalone service retains its default streams.
        self._summary_handshakes = 0
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
        self._log_session_id = None
        self._log_volume = self._log_event_count = 0
        self.log_write_errors = 0
        self.debug_session_dir: Path | None = None
        self.debug_counters: dict[tuple[str, str], int] = defaultdict(int)
        self.server = None
        if structured:
            from endfield_pcap.trace.recording import TraceRecording
            self._trace_recording = self.trace_bridge = TraceRecording(self._handle_trace_events, trace_header,
                log_directory=None)
        else:
            self.trace_bridge = TraceBridge(write_enabled=False, line_sink=self._handle_trace_line)
        self.status_file = config.status_file
        if config.recording_on_start and config.trace_enabled:
            self.set_recording(True)
        else:
            config.trace_file = None
        if self.status_file is not None:
            self.status_file.parent.mkdir(parents=True, exist_ok=True)
        # Open native handles after fallible trace/directory initialization.
        try:
            self.capture_manager = CaptureManager.create(config.npcap_device, self._on_packet_from_thread)
        except BaseException:
            self._close_trace_recording()
            raise
        if self.status_file is not None:
            self._write_status()

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        self.snapshot_publisher.reset(new_stream=True)
        self.summary_publisher.reset(new_stream=True)
        try:
            await self._publish_analysis_snapshot()
            await self._publish_analysis_summary()
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
            self._close_trace_recording()
            raise
        self._set_state(ServiceState.WAITING_RESTART if self._game_running() else ServiceState.WAITING_GAME)
        tasks = [
            asyncio.create_task(self._process_monitor_loop(), name="process-monitor"),
            asyncio.create_task(self._packet_loop(), name="packet-loop"),
            asyncio.create_task(self._batch_flush_loop(), name="batch-flush"),
            asyncio.create_task(self._analysis_snapshot_loop(), name="analysis-snapshot"),
            asyncio.create_task(self._analysis_summary_loop(), name="analysis-summary"),
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
            await self._publish_analysis_snapshot()
            await self._publish_analysis_summary()
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
            self._close_trace_recording()
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
            "recording": self.recording,
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
        if self.status_file is None or not hasattr(self, 'capture_manager'):
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
        if not self.recording:
            return
        if self.log_file is not None:
            return
        day_dir = self._disk_trace.trace_file.parent
        day_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"session_{session_id}.ndjson"
        self.current_log_path = day_dir / file_name
        structured = isinstance(self._disk_trace, TraceRecording)
        self.log_file = self.current_log_path.open("x" if structured else "a", encoding="utf-8", newline='\n')
        self._log_session_id, self._log_volume, self._log_event_count = session_id, 1, 0
        if structured:
            self._write_session_header(self.log_file, 1, None)

    def _write_session_header(self, stream, volume, previous):
        header = self._disk_trace.header
        value = dict(type='session_volume', schema_version=1,
            recording_id=self._log_session_id, session_id=self._log_session_id,
            volume=volume, previous_volume=previous, event_offset=self._log_event_count,
            trace_recording_id=header.recording_id, trace_volume=header.volume,
            timezone_offset_minutes=header.timezone_offset_minutes)
        stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')
        stream.flush()

    def rotate_recording(self):
        """Called by the capture event loop between complete business calls."""
        if (self.active_session is None or self.log_file is None or self.current_log_path is None
                or not isinstance(self._disk_trace, TraceRecording)):
            raise ValueError('请在 JSONL 抓包会话开始后新建记录')
        volume = self._log_volume + 1
        path = self.current_log_path.with_name(f'session_{self._log_session_id}_v{volume:03d}.ndjson')
        # Reserve the paired raw file before switching the trace writer.
        next_stream = path.open('x', encoding='utf8', newline='\n')
        old_trace = self._disk_trace.trace_file
        try:
            self.log_file.flush()
            trace = self._disk_trace.rotate_volume()
            self._write_session_header(next_stream, volume,
                dict(volume=self._log_volume, file=self.current_log_path.name))
        except BaseException as exc:
            next_stream.close()
            if self._disk_trace.trace_file != old_trace:
                # A disk failure after one writer switched cannot safely resume
                # the old pair. Reuse the service's fatal shutdown boundary.
                self._fatal_exception = exc
                self._fatal_error = dict(task='recording-rotation', type=type(exc).__name__, message=str(exc))
                self._write_status()
                self.request_stop()
            raise
        previous = self.log_file
        self.log_file, self.current_log_path, self._log_volume = next_stream, path, volume
        self.config.trace_file = trace
        self.config.status_file = self.status_file = trace.with_suffix('.jsonl.status.json')
        previous.close()
        self._write_status()
        return path, trace

    def _reset_session(self) -> None:
        had_capture_session = self.active_flow is not None or self.active_session is not None
        if had_capture_session and self.trace_bridge is not None:
            self.trace_bridge.end_capture_session()
        self._recording_context.clear()
        if self.active_session is not None:
            self.active_session.flush_debug_state()
        self.active_flow = None
        self.active_session = None
        self._active_flow_capture_locked = False
        self.capture_manager.restore_default_filters()
        self.debug_session_dir = None
        self.debug_counters.clear()
        publisher = getattr(self, "snapshot_publisher", None)
        if had_capture_session and publisher is not None:
            publisher.reset()
            self.summary_publisher.reset()

    def _handle_trace_line(self, line: str) -> None:
        self._write_disk_line(line)
        self.snapshot_publisher.feed_line(line)
        self.summary_publisher.feed_line(line)

    def _handle_trace_events(self, events) -> None:
        self._write_disk_events(events)
        self.snapshot_publisher.feed_events(events)
        self.summary_publisher.feed_events(events)

    def _close_trace_recording(self):
        if self._trace_recording is not None:
            self._trace_recording.close()
        if self.recording:
            self.set_recording(False)

    def _handle_outbound_event(self, event: OutboundEvent) -> None:
        payload = event.as_dict()
        if self.trace_bridge is not None:
            self.trace_bridge.handle_event(payload)
        self._recording_context.observe(payload)
        self._write_recorded_event(payload)
        self.batch.append(payload)
        if self.observer is not None and self.observer.on_event is not None:
            self.observer.on_event(payload)
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
