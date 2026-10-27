"""Compose sidebar pages, dispatch service messages, and own window lifetime."""
from __future__ import annotations

import ctypes
import logging
import queue
import sys
import threading
from pathlib import Path
from collections.abc import Callable
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (
    FluentIcon as FIF,
    FluentWindow,
    InfoBar,
    NavigationItemPosition,
    setTheme,
)
from endfield_pcap.gui.config import (
    AppConfig,
    default_config_path,
    load_app_config,
    save_app_config,
)
from endfield_pcap.runtime.logging import configure_logging, runtime_log_directory
from endfield_pcap.models import FlowKey, RuntimeMetrics, ServiceState, SquadMemberPayload
from endfield_pcap.overlays.manager import OverlayManager
from endfield_pcap.overlays.templates import template_for
from endfield_pcap.history.records import CombatRecord
from endfield_pcap.history.index import HistoryIndex
from endfield_pcap.gui.pages.history.actions import HistoryActions
from endfield_pcap.gui.pages.history.view import BattleLogPage
from endfield_pcap.gui.pages.settings.view import SettingsPage
from endfield_pcap.gui.service import ServiceController
from endfield_pcap.gui.pages.logs.view import RuntimeLogPage, QtLogHandler
from endfield_pcap.gui.pages.overlays.view import OverlayPage
from endfield_pcap.gui.pages.home.view import HomePage
from endfield_pcap.gui.shared.placement import schedule_initial_placement
from endfield_pcap.gui.shared.typography import GuiTypography
from endfield_pcap._version import APP_NAME, __version__
from endfield_pcap.gui.resources import APP_USER_MODEL_ID, _app_icon_path, _load_avatar_index
from endfield_pcap.gui.theme import _theme_from_mode, WindowTheme
from endfield_pcap.gui.pages.home.actions import CaptureActions
from endfield_pcap.gui.pages.overlays.actions import OverlayActions
from endfield_pcap.gui.pages.settings.actions import SettingsActions
from endfield_pcap.gui.pages.overlays.hotkeys import OverlayHotkeys
from endfield_pcap.gui.updates import UpdateActions
from endfield_pcap.gui.services import IndependentServices
from endfield_pcap.gui.lifecycle import GuiLifecycle


LOGGER = logging.getLogger(__name__)


class MainWindow(
    GuiLifecycle,
    IndependentServices,
    CaptureActions,
    OverlayActions,
    SettingsActions,
    OverlayHotkeys,
    UpdateActions,
    WindowTheme,
    HistoryActions,
    FluentWindow,
):
    def __init__(self, app_config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self.app_config = app_config
        self.config_path = config_path
        self.service_controller = ServiceController(self.app_config.service)
        self._init_independent_services()
        self.overlay_manager = OverlayManager(
            self.app_config.service.ws_port,
            ws_browser_token=self.app_config.service.ws_browser_token,
            on_entry_changed=self._handle_overlay_entry_changed,
            use_in_process_snapshots=True,
            on_full_requirement=self.service_controller.set_full_analysis_required,
            on_analysis_requirement=self._set_analysis_requirements,
        )
        self.avatar_index = _load_avatar_index()
        self.records: list[CombatRecord] = []
        self._selected_record: CombatRecord | None = None
        self._history_generation = 0
        self._history_record: CombatRecord | None = None
        self._history_selection_order: list[tuple] = []
        self._history_pending_keys: set[str] = set()
        self._history_cancel = threading.Event()
        self._stop_pending = False
        self._auto_start_attempted = False
        self._closing = False
        self._capture_error = ''
        self._capture_error_bar = None
        self._history_displayed_key: str | None = None
        self._history_detail_snapshot = None
        self._history_detail_key = None
        self._history_detail_signature = None
        self._history_detail_dialog = None
        self._history_inspect_generation = None
        self._records_generation = 0
        self._records_pending = False
        self._records_log_dir: Path | None = None
        self._raw_records: list[CombatRecord] = []
        self._history_index = HistoryIndex(config_path.parent / 'history-index')
        self._trace_import_generation = 0
        self._trace_import_pending = False
        self._trace_records: dict[Path, list[CombatRecord]] = {}
        self._trace_signatures: dict[Path, tuple[int, int]] = {}
        self.current_state = ServiceState.WAITING_GAME
        self.current_session_id: str | None = None
        self.current_flow: FlowKey | None = None
        self.current_metrics = RuntimeMetrics()
        self.current_squad: list[SquadMemberPayload] = []
        self._global_hotkey_registered = False
        self._registered_hotkey = ""
        self._game_dir_infobar: InfoBar | None = None
        self._restart_required_infobar: InfoBar | None = None
        self._npcap_infobar: InfoBar | None = None

        self.log_handler = QtLogHandler(self.service_controller.queue)
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logging.getLogger().addHandler(self.log_handler)
        self.home_page = HomePage(self.avatar_index, self)
        self.overlay_page = OverlayPage(self)
        self.records_page = BattleLogPage(self)
        self.settings_page = SettingsPage(self)
        self.logs_page = RuntimeLogPage(runtime_log_directory(config_path.parent / 'logs'), self)

        self._init_window()
        self._init_gui_lifecycle()
        self._bind_events()
        self.home_page.status_card.set_squad_members([])
        self._refresh_overlay_views()
        self._load_records()
        self._refresh_settings_page()
        self._apply_gui_theme()
        self.gui_typography = GuiTypography(self, app_config.gui_font_percent/100)
        self.overlay_manager.sync_entries(self.app_config.overlays)
        self._ensure_game_directory_ready()
        self._update_service_status()

        self._init_update_check()

        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(33)
        self.queue_timer.timeout.connect(self._drain_queue)
        self.queue_timer.start()
        self._bind_independent_services()
        if app_config.overlay_migration_count:
            from endfield_pcap.gui.config import save_app_config
            count = app_config.overlay_migration_count
            app_config.overlay_migration_count = 0
            save_app_config(app_config, config_path)
            QTimer.singleShot(0, self, lambda: InfoBar.info(
                '???????', f'??? {count} ???????????????????????',
                duration=9000, parent=self))

    def _drain_queue(self) -> None:
        self._drain_independent_services()
        while True:
            try:
                event_type, payload = self.service_controller.queue.get_nowait()
            except queue.Empty:
                break
            if event_type == "log":
                self.logs_page.append_log(str(payload))
            elif event_type == "state":
                data = payload if isinstance(payload, dict) else {}
                self.current_state = data.get("state", ServiceState.WAITING_GAME)
                self.current_session_id = data.get("session_id")
                self.current_flow = data.get("flow")
                self._update_service_status()
            elif event_type == 'started':
                self._update_service_status()
            elif event_type == 'trace_path':
                self.input_controller.set_trace(payload)
            elif event_type == "metrics":
                data = payload if isinstance(payload, dict) else {}
                self.current_metrics = data.get("metrics", RuntimeMetrics())
                self.current_flow = data.get("flow")
                self._update_service_status()
            elif event_type == "event":
                self._handle_service_event(payload if isinstance(payload, dict) else {})
            elif event_type == "analysis_snapshot":
                self.overlay_manager.apply_analysis_snapshot(payload, take_ownership=True)
            elif event_type == "analysis_summary":
                self.overlay_manager.apply_analysis_summary(payload, take_ownership=True)
            elif event_type == "history_snapshot":
                self._complete_history_load(payload)
            elif event_type == "history_batch":
                self._complete_history_batch(payload)
            elif event_type == "trace_import":
                self._complete_trace_import(payload)
            elif event_type == "history_index":
                self._complete_record_index(payload)
            elif event_type == "error":
                exc = payload if isinstance(payload, BaseException) else RuntimeError(str(payload))
                LOGGER.error("service thread crashed", exc_info=(type(exc), exc, exc.__traceback__))
                reason = (str(exc).splitlines() or [type(exc).__name__])[0][:180]
                self._show_capture_error(f'抓包失败：{reason}')
            elif event_type == "stopped":
                self.input_controller.set_trace(None)
                self.vision_controller.set_identity([],None)
                self._finish_service_stop()

    def _handle_service_event(self, event: dict[str, object]) -> None:
        if str(event.get("type", "")) != "SC_SELF_SCENE_INFO":
            return
        members: list[SquadMemberPayload] = []
        for item in event.get("char_list", []):
            if not isinstance(item, dict):
                continue
            battle_inst_id = item.get("battle_inst_id")
            if battle_inst_id is None:
                continue
            members.append(
                SquadMemberPayload(
                    battle_inst_id=int(battle_inst_id),
                    templateid=str(item.get("templateid")) if item.get("templateid") is not None else None,
                    display_name=str(item.get("display_name")) if item.get("display_name") is not None else None,
                    is_leader=bool(item.get("is_leader", False)),
                    squad_index=int(item.get("squad_index", len(members))),
                )
            )
        self.current_squad = members
        self.home_page.status_card.set_squad_members(self.current_squad)
        self.vision_controller.set_identity(members,self.current_session_id)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        schedule_initial_placement(self)
        self._update_gui_poll_interval()
        if hasattr(self,'home_page'):
            QTimer.singleShot(0,self._update_service_status)

    def _init_window(self) -> None:
        self.resize(1200, 800)
        self.setWindowTitle(f"{APP_NAME} · 战斗分析")
        icon_path = _app_icon_path()
        if icon_path is not None:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.navigationInterface.setExpandWidth(220)
        self.navigationInterface.setCollapsible(False)
        self.addSubInterface(self.home_page, FIF.HOME, "首页")
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.overlay_page, FIF.APPLICATION, "悬浮窗")
        self.addSubInterface(self.records_page, FIF.HISTORY, "战斗日志", NavigationItemPosition.SCROLL)
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.logs_page, FIF.DOCUMENT, "运行日志", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.settings_page, FIF.SETTING, "设置", NavigationItemPosition.SCROLL)

    def _bind_events(self) -> None:
        self._bind_home_events()
        self._bind_overlay_events()
        self._bind_records_events()
        self._bind_settings_events()

        stacked = getattr(self, "stackedWidget", None)
        if stacked is not None:
                    stacked.currentChanged.connect(self._handle_current_interface_changed)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        self._history_cancel.set()
        self._history_generation += 1
        self._trace_import_generation += 1
        self._records_generation += 1
        self.queue_timer.stop()
        logging.getLogger().removeHandler(self.log_handler)
        self._unregister_overlay_hotkey()
        self._unregister_gui_hotkey()
        self.tray_icon.hide()
        if self._history_detail_dialog is not None:self._history_detail_dialog.close()
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.close_all()
        self._stop_independent_services()
        self.service_controller.stop()
        self.service_controller.join(timeout=5.0)
        super().closeEvent(event)


def run_gui(
    config_path: Path | None = None,
    debug_enabled: bool = False,
    debug_dir: Path | None = None,
    on_ready: Callable[[], None] | None = None,
) -> int:
    target_path = config_path or default_config_path()
    app_config = load_app_config(target_path)
    app_config.service.debug_enabled = debug_enabled
    if debug_dir is not None:
        app_config.service.debug_dir = debug_dir.resolve()
    configure_logging(app_config.service.log_level)

    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    icon_path = _app_icon_path()
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    app.setFont(QFont("Microsoft YaHei UI", 10))
    setTheme(_theme_from_mode(app_config.theme_mode))

    window = MainWindow(app_config, target_path)
    window.show()
    if on_ready is not None:
        def notify_when_visible():
            handle = window.windowHandle()
            if window.isVisible() and handle is not None and handle.isExposed():
                on_ready()
            else:
                QTimer.singleShot(50, window, notify_when_visible)
        QTimer.singleShot(0, window, notify_when_visible)
    return app.exec()
