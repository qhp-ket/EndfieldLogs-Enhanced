"""Worker-thread ownership and observer delivery for the capture service."""
from __future__ import annotations
import asyncio
import queue
import threading
from copy import deepcopy
from enum import StrEnum
from endfield_pcap.models import ServiceObserver
from endfield_pcap.service.runtime.server import DamageLogService
from endfield_pcap.service.config import ServiceConfig
from endfield_pcap.analysis.live.delivery import GuiDeliveryQueue


class CaptureLifecycle(StrEnum):
    STOPPED = 'stopped'
    STARTING = 'starting'
    RUNNING = 'running'
    STOPPING = 'stopping'


class ServiceController:
    def __init__(self, config: ServiceConfig) -> None:
        self.config = config
        self.queue: "queue.Queue[tuple[str, object]]" = GuiDeliveryQueue()
        self._full_analysis_required = False
        self._analysis_streams = None
        self._thread: threading.Thread | None = None
        self._service: DamageLogService | None = None
        self.running_config: ServiceConfig | None = None
        self._stop_requested = threading.Event()
        self._lifecycle = CaptureLifecycle.STOPPED
        self._lifecycle_lock = threading.Lock()

    @property
    def lifecycle(self) -> CaptureLifecycle:
        with self._lifecycle_lock:
            return self._lifecycle

    def _on_state(self, state, session_id, flow):
        # The first service state is emitted only after capture and WS startup.
        # A late state callback cannot cancel a stop already requested by Qt.
        with self._lifecycle_lock:
            if self._lifecycle == CaptureLifecycle.STARTING:
                self._lifecycle = CaptureLifecycle.RUNNING
        self.queue.put(('state', dict(state=state, session_id=session_id, flow=flow)))

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running():
            return
        with self._lifecycle_lock:
            self._lifecycle = CaptureLifecycle.STARTING
        self._stop_requested.clear()
        self._service = None
        # Service construction fills generated trace/status paths. Isolate it
        # from persisted settings so every restart creates a fresh capture.
        self.running_config = deepcopy(self.config)
        observer = ServiceObserver(
            on_state_change=self._on_state,
            on_runtime_metrics=lambda metrics, pcap_stats, flow: self.queue.put(
                ("metrics", {"metrics": metrics, "pcap_stats": pcap_stats, "flow": flow})
            ),
            on_event=lambda event: self.queue.put(("event", event))
            if str(event.get("type", "")) == "SC_SELF_SCENE_INFO"
            else None,
            on_analysis_summary=lambda message: self.queue.put(("analysis_summary", message)),
            on_buff_snapshot=lambda message: self.queue.put(("buff_snapshot", message)),
        )
        def runner() -> None:
            try:
                self._service = DamageLogService(self.running_config, observer=observer)
                if getattr(self.running_config,'trace_file',None) is not None:
                    self.queue.put(('trace_path',str(self.running_config.trace_file)))
                self._service.observer.on_analysis_snapshot = self._on_full_snapshot if self._full_analysis_required else None
                self._service.set_full_analysis_required(self._full_analysis_required)
                if self._analysis_streams is not None:
                    setter = getattr(self._service, 'set_analysis_streams', None)
                    if setter is not None:
                        setter(self._analysis_streams)
                async def run() -> None:
                    task = asyncio.create_task(self._service.run())
                    await asyncio.sleep(0)
                    if self._stop_requested.is_set():
                        self._service.request_stop()
                    # WAITING_GAME is already the service's initial state, so
                    # _set_state may intentionally emit no change on startup.
                    # Use the existing explicit readiness event as well.
                    wait_started = getattr(self._service, 'wait_started', None)
                    while wait_started is not None and not task.done() and self.lifecycle == CaptureLifecycle.STARTING:
                        if wait_started(0):
                            with self._lifecycle_lock:
                                if self._lifecycle == CaptureLifecycle.STARTING:
                                    self._lifecycle = CaptureLifecycle.RUNNING
                                    self.queue.put(('started', None))
                            break
                        await asyncio.wait((task,), timeout=.02)
                    await task
                asyncio.run(run())
            except BaseException as exc:  # noqa: BLE001
                self.queue.put(("error", exc))
            finally:
                # run() has unwound its capture/WS/worker cleanup before here.
                # is_running() also guards the final thread-return boundary.
                with self._lifecycle_lock:
                    self._lifecycle = CaptureLifecycle.STOPPED
                self.queue.put(("stopped", None))

        self._thread = threading.Thread(target=runner, name="damage-service", daemon=True)
        try:
            self._thread.start()
        except BaseException:
            with self._lifecycle_lock:
                self._lifecycle = CaptureLifecycle.STOPPED
            raise

    def stop(self) -> None:
        self._stop_requested.set()
        with self._lifecycle_lock:
            if self.is_running():
                self._lifecycle = CaptureLifecycle.STOPPING
        if self._service is not None:
            self._service.request_stop()

    def _on_full_snapshot(self, message):
        self.queue.put(('analysis_snapshot', message))

    def set_full_analysis_required(self, required):
        self._full_analysis_required = bool(required)
        service = self._service
        if service is not None and service.loop is not None:
            def update():
                service.observer.on_analysis_snapshot = self._on_full_snapshot if required else None
                service.set_full_analysis_required(required)
            service.loop.call_soon_threadsafe(update)

    def join(self, timeout: float = 5.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def set_analysis_streams(self, streams):
        self._analysis_streams = frozenset(streams)
        service = self._service
        if service is not None and service.loop is not None:
            setter = getattr(service, 'set_analysis_streams', None)
            if setter is not None:
                service.loop.call_soon_threadsafe(setter, self._analysis_streams)
