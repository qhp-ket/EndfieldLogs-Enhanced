from __future__ import annotations
import asyncio
import queue
import socket
import sys
import threading
import logging
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from endfield_pcap.models import OverlayEntry, OverlaySourceType, ServiceObserver
from endfield_pcap.service.runtime.server import DamageLogService
from endfield_pcap.service.config import ServiceConfig
from endfield_pcap.overlays.manager import OverlayManager


LOGGER = logging.getLogger(__name__)


def run_with_overlay(service_config: ServiceConfig) -> int:
    service: DamageLogService | None = None
    service_thread: threading.Thread | None = None
    service_error: list[BaseException] = []
    snapshots: queue.Queue[dict[str, object]] = queue.Queue()

    def port_is_available(port: int) -> bool:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            probe.close()

    def service_main() -> None:
        try:
            assert service is not None
            asyncio.run(service.run())
        except BaseException as exc:  # noqa: BLE001
            LOGGER.error("service thread failed", exc_info=(type(exc), exc, exc.__traceback__))
            service_error.append(exc)

    attach_only = not port_is_available(service_config.ws_port)
    if attach_only:
        LOGGER.warning(
            "ws port %d is already in use; the overlay will attach to the existing service instead of starting a new one",
            service_config.ws_port,
        )
    else:
        service = DamageLogService(
            service_config, observer=ServiceObserver(on_analysis_summary=snapshots.put, on_buff_snapshot=snapshots.put),
        )
        service_thread = threading.Thread(target=service_main, name="damage-service", daemon=True)
        service_thread.start()

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    manager = OverlayManager(service_config.ws_port, use_in_process_snapshots=not attach_only)
    manager.sync_entries(
        [
            OverlayEntry(
                id="builtin-overlay",
                name="伤害统计",
                source_type=OverlaySourceType.BUILTIN,
                source_value="damage",
                enabled=True,
                locked=False,
                click_through=False,
                opacity=1.0,
            )
        ]
    )

    def poll_state() -> None:
        while True:
            try:
                message = snapshots.get_nowait()
                if message.get("type") == "buff_snapshot":
                    manager.apply_buff_snapshot(message)
                elif message.get("type") == "analysis_summary":
                    manager.apply_analysis_summary(message)
                else:
                    manager.apply_analysis_snapshot(message)
            except queue.Empty:
                break
        if service_error:
            LOGGER.error("overlay is closing because the service thread exited with an error")
            app.quit()
            return
        if service_thread is not None and not service_thread.is_alive():
            app.quit()

    app.aboutToQuit.connect(manager.close_all)
    if service is not None:
        app.aboutToQuit.connect(service.request_stop)

    poll_timer = QTimer()
    poll_timer.setInterval(33)
    poll_timer.timeout.connect(poll_state)
    poll_timer.start()

    exit_code = app.exec()

    if service is not None:
        service.request_stop()
    if service_thread is not None:
        service_thread.join(timeout=5)
    if service_error:
        raise service_error[0]
    return exit_code
