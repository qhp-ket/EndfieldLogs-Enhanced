from __future__ import annotations

import ctypes
import json
import logging
import queue
import sys
import threading
import uuid
from ctypes import wintypes
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import QApplication, QFileDialog, QFrame, QInputDialog, QMessageBox, QWidget
from qfluentwidgets import FluentIcon as FIF, FluentWindow, InfoBar, InfoBarPosition, NavigationItemPosition, PrimaryPushButton, Theme, isDarkTheme, setTheme

from .gui_config import AppConfig, default_config_path, load_app_config, save_app_config
from .logging_utils import configure_logging, runtime_log_directory
from .models import FlowKey, OverlayEntry, OverlayGeometry, OverlaySourceType, RuntimeMetrics, ServiceState, SquadMemberPayload
from .npcap import has_npcap
from .overlay_host import OverlayManager
from .overlay_templates import template_for, with_template_value
from .record_parser import CombatRecord
from .history_index import HistoryIndex
from .gui_history import HistoryActions
from .runtime_paths import bundle_root
from PySide6.QtGui import QIcon

from .gui_history_view import BattleLogPage
from .gui_settings_view import SettingsPage
from .gui_service import CaptureLifecycle, ServiceController
from .gui_log_view import RuntimeLogPage
from .gui_overlay_view import OverlayPage
from .gui_home_view import HomePage
from .gui_window_placement import schedule_initial_placement
from .gui_typography import GuiTypography
from ._version import APP_NAME, __version__

LOGGER = logging.getLogger(__name__)
ROOT = bundle_root()
APP_ICON_PNG = ROOT / "icon.png"
APP_ICON_ICO = ROOT / "icon.ico"
ICON_DIR = ROOT / "icon" / "Texture2D"
ACTOR_IMAGE_TABLE = ROOT / "jsondata" / "ActorImageTable.json"
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
APP_USER_MODEL_ID = "EndfieldLogs.Desktop"
GLOBAL_HOTKEY_ID = 0xB100
USER32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None


def _app_icon_path() -> Path | None:
    if APP_ICON_ICO.exists():
        return APP_ICON_ICO
    if APP_ICON_PNG.exists():
        return APP_ICON_PNG
    return None


class QtLogHandler(logging.Handler):
    def __init__(self, sink: "queue.Queue[tuple[str, object]]") -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.put_nowait(("log", self.format(record)))
        except Exception:
            return


def _load_avatar_index() -> dict[str, Path]:
    if not ACTOR_IMAGE_TABLE.exists():
        return {}
    payload = json.loads(ACTOR_IMAGE_TABLE.read_text(encoding="utf-8"))
    result: dict[str, Path] = {}
    for templateid, item in payload.items():
        avatar = item.get("avatarPath")
        if avatar:
            result[str(templateid)] = ICON_DIR / f"{avatar}.png"
    return result


def _theme_from_mode(mode: str) -> Theme:
    normalized = str(mode or "system").strip().lower()
    if normalized == "light":
        return Theme.LIGHT
    if normalized == "dark":
        return Theme.DARK
    return Theme.AUTO


def _is_valid_game_dir(path: Path | None) -> bool:
    if path is None:
        return False
    target = Path(path)
    return (target / "GameAssembly.dll").exists() and (target / "Endfield.exe").exists()


def _normalize_game_dir_selection(raw_path: str) -> Path | None:
    if not raw_path:
        return None
    try:
        target = Path(raw_path).expanduser().resolve()
    except OSError:
        return None
    if target.is_file():
        target = target.parent
    return target


def _select_game_directory_from_dialog(parent: QWidget | None, start_dir: Path, *, select_exe: bool) -> Path | None:
    if select_exe:
        selected, _ = QFileDialog.getOpenFileName(
            parent,
            "选择 Endfield.exe",
            str(start_dir),
            "Endfield.exe (Endfield.exe);;Executable Files (*.exe);;All Files (*)",
        )
    else:
        selected = QFileDialog.getExistingDirectory(parent, "选择 Endfield Game 目录", str(start_dir))
    return _normalize_game_dir_selection(selected)


def _run_game_directory_wizard(app_config: AppConfig, config_path: Path, parent: QWidget | None = None) -> bool:
    start_dir = app_config.service.dll_dir if app_config.service.dll_dir else ROOT
    while True:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("首次设置游戏路径")
        box.setText("请选择终末地游戏目录或 Endfield.exe。")
        box.setInformativeText("客户端会保存这个路径，后续启动不会自动扫描磁盘。")
        exe_button = box.addButton("选择 Endfield.exe", QMessageBox.ButtonRole.AcceptRole)
        dir_button = box.addButton("选择游戏目录", QMessageBox.ButtonRole.ActionRole)
        cancel_button = box.addButton("退出", QMessageBox.ButtonRole.RejectRole)
        box.exec()

        clicked = box.clickedButton()
        if clicked == cancel_button:
            return False

        selected_dir = _select_game_directory_from_dialog(
            parent,
            start_dir,
            select_exe=clicked == exe_button,
        )
        if selected_dir is None:
            continue
        start_dir = selected_dir
        if not _is_valid_game_dir(selected_dir):
            QMessageBox.warning(
                parent,
                "目录无效",
                "所选位置没有同时找到 Endfield.exe 和 GameAssembly.dll，请重新选择游戏根目录。",
            )
            continue

        app_config.service.dll_dir = selected_dir
        app_config.service.game_exe = "Endfield.exe"
        save_app_config(app_config, config_path)
        return True


def _qt_key_to_vk(key: Qt.Key) -> int | None:
    key_value = int(key)
    if int(Qt.Key.Key_0) <= key_value <= int(Qt.Key.Key_9):
        return key_value
    if int(Qt.Key.Key_A) <= key_value <= int(Qt.Key.Key_Z):
        return key_value
    if int(Qt.Key.Key_F1) <= key_value <= int(Qt.Key.Key_F24):
        return 0x70 + (key_value - int(Qt.Key.Key_F1))
    explicit_map = {
        int(Qt.Key.Key_Space): 0x20,
        int(Qt.Key.Key_Tab): 0x09,
        int(Qt.Key.Key_Backspace): 0x08,
        int(Qt.Key.Key_Return): 0x0D,
        int(Qt.Key.Key_Enter): 0x0D,
        int(Qt.Key.Key_Escape): 0x1B,
        int(Qt.Key.Key_Left): 0x25,
        int(Qt.Key.Key_Up): 0x26,
        int(Qt.Key.Key_Right): 0x27,
        int(Qt.Key.Key_Down): 0x28,
        int(Qt.Key.Key_Home): 0x24,
        int(Qt.Key.Key_End): 0x23,
        int(Qt.Key.Key_PageUp): 0x21,
        int(Qt.Key.Key_PageDown): 0x22,
        int(Qt.Key.Key_Insert): 0x2D,
        int(Qt.Key.Key_Delete): 0x2E,
        int(Qt.Key.Key_Minus): 0xBD,
        int(Qt.Key.Key_Equal): 0xBB,
        int(Qt.Key.Key_Comma): 0xBC,
        int(Qt.Key.Key_Period): 0xBE,
        int(Qt.Key.Key_Slash): 0xBF,
        int(Qt.Key.Key_Semicolon): 0xBA,
        int(Qt.Key.Key_Apostrophe): 0xDE,
        int(Qt.Key.Key_BracketLeft): 0xDB,
        int(Qt.Key.Key_BracketRight): 0xDD,
        int(Qt.Key.Key_Backslash): 0xDC,
        int(Qt.Key.Key_QuoteLeft): 0xC0,
    }
    return explicit_map.get(key_value)


def _portable_hotkey_to_native(hotkey: str) -> tuple[int, int] | None:
    sequence = QKeySequence(hotkey or "")
    combo = sequence[0]
    if combo.key() == Qt.Key.Key_unknown:
        return None
    modifiers = 0
    if combo.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier:
        modifiers |= MOD_CONTROL
    if combo.keyboardModifiers() & Qt.KeyboardModifier.AltModifier:
        modifiers |= MOD_ALT
    if combo.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
        modifiers |= MOD_SHIFT
    if combo.keyboardModifiers() & Qt.KeyboardModifier.MetaModifier:
        modifiers |= MOD_WIN
    vk = _qt_key_to_vk(combo.key())
    if vk is None:
        return None
    return modifiers, vk




def _directory_size(path: Path) -> int:
    total = 0
    try:
        if not path.exists():
            return 0
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except OSError:
                continue
    except OSError:
        return total
    return total


class MainWindow(HistoryActions, FluentWindow):
    def __init__(self, app_config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self.app_config = app_config
        self.app_config.overlays = [entry for entry in app_config.overlays
            if entry.source_value != 'combo_skill' and 'combo_snapshot' not in template_for(entry).subscriptions]
        self.config_path = config_path
        self.service_controller = ServiceController(self.app_config.service)
        self.overlay_manager = OverlayManager(
            self.app_config.service.ws_port,
            on_entry_changed=self._handle_overlay_entry_changed,
            use_in_process_snapshots=True,
            on_full_requirement=self.service_controller.set_full_analysis_required,
            on_analysis_requirement=self.service_controller.set_analysis_streams,
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

        self.queue_timer = QTimer(self)
        self.queue_timer.setInterval(33)
        self.queue_timer.timeout.connect(self._drain_queue)
        self.queue_timer.start()


    def _drain_queue(self) -> None:
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
            elif event_type == "buff_snapshot":
                self.overlay_manager.apply_buff_snapshot(payload)
            elif event_type == "error":
                exc = payload if isinstance(payload, BaseException) else RuntimeError(str(payload))
                LOGGER.error("service thread crashed", exc_info=(type(exc), exc, exc.__traceback__))
                reason = (str(exc).splitlines() or [type(exc).__name__])[0][:180]
                self._show_capture_error(f'抓包失败：{reason}')
            elif event_type == "stopped":
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

    def _update_service_status(self) -> None:
        lifecycle = self.service_controller.lifecycle
        if self._stop_pending or (lifecycle == CaptureLifecycle.STOPPED and self.service_controller.is_running()):
            lifecycle = CaptureLifecycle.STOPPING
        text, enabled, program = {
            CaptureLifecycle.STOPPED: ('启动抓包', True, '已停止'),
            CaptureLifecycle.STARTING: ('正在启动…', False, '正在启动'),
            CaptureLifecycle.RUNNING: ('停止抓包', True, '已启动'),
            CaptureLifecycle.STOPPING: ('正在停止…', False, '正在停止'),
        }[lifecycle]
        self.home_page.start_service_btn.setText(text)
        self.home_page.start_service_btn.setEnabled(enabled)
        running = lifecycle == CaptureLifecycle.RUNNING
        active = self.service_controller.running_config
        port = active.ws_port if self.service_controller.is_running() and active is not None else self.app_config.service.ws_port
        self.home_page.service_hint.setText(self._capture_error or f"{program} · ws://127.0.0.1:{port}/ws")
        if not running:
            game, server = '未监测', '未连接'
        elif self.current_state == ServiceState.WAITING_RESTART:
            game = "客户端已运行，需重开游戏"
            server = "等待新会话"
        elif self.current_state == ServiceState.WAITING_CONNECTION:
            game = "已检测到客户端"
            server = "等待游戏连接"
        elif self.current_state == ServiceState.WAITING_HANDSHAKE:
            game = "已检测到客户端"
            server = "等待登录完成"
        elif self.current_state == ServiceState.LIVE:
            game = "已检测到客户端"
            server = "已连接到战斗服务器"
        else:
            game = "等待客户端运行"
            server = "未连接"
        flow = (
            self.current_session_id
            if self.current_flow is None
            else f"{self.current_flow.client.ip}:{self.current_flow.client.port} -> {self.current_flow.server.ip}:{self.current_flow.server.port}"
        )
        self.home_page.status_card.set_status(program, game, server, flow or "-")
        self.overlay_page.status_card.set_entries(self.app_config.overlays, self.app_config.overlay_restore_ids)
        self.settings_page.set_service_info(self.app_config.service)
        self._sync_restart_required_infobar()

    def _refresh_overlay_views(self) -> None:
        self.overlay_page.set_entries(self.app_config.overlays)
        self._sync_overlay_selection()
        self._update_service_status()

    def _selected_overlay(self) -> OverlayEntry | None:
        entry_id = self.overlay_page.selected_entry_id()
        if entry_id is None:
            return None
        for entry in self.app_config.overlays:
            if entry.id == entry_id:
                return entry
        return None

    def _sync_overlay_selection(self) -> None:
        entry = self._selected_overlay()
        self.overlay_page.show_entry(entry)

    def _replace_overlay_entry(self, updated: OverlayEntry) -> None:
        self.app_config.overlays = [updated if entry.id == updated.id else entry for entry in self.app_config.overlays]
        self.overlay_manager.apply_entry(updated)
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _handle_overlay_entry_changed(self, entry: OverlayEntry) -> None:
        self.app_config.overlays = [entry if item.id == entry.id else item for item in self.app_config.overlays]
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _add_url_overlay(self) -> None:
        url, ok = QInputDialog.getText(self, "新增 URL 悬浮窗", "请输入悬浮窗 URL：")
        if not ok or not url.strip():
            return
        entry = OverlayEntry(
            id=str(uuid.uuid4()),
            name="在线悬浮窗",
            source_type=OverlaySourceType.URL,
            source_value=url.strip(),
            enabled=True,
            locked=False,
            click_through=False,
            opacity=1.0,
            scale=1.0,
        )
        self.app_config.overlays.append(entry)
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.apply_entry(entry)
        self._refresh_overlay_views()

    def _add_file_overlay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择本地悬浮窗模板或 HTML", str(ROOT), "悬浮窗模板/HTML (*.json *.html *.htm)")
        if not path:
            return
        entry = OverlayEntry(
            id=str(uuid.uuid4()),
            name=Path(path).stem,
            source_type=OverlaySourceType.FILE,
            source_value=path,
            enabled=True,
            locked=False,
            click_through=False,
            opacity=1.0,
            scale=1.0,
        )
        template = template_for(entry)
        if template.error:
            QMessageBox.warning(self, "模板无效", template.error)
            return
        if 'combo_snapshot' in template.subscriptions:
            QMessageBox.information(self, '功能已停用', '连携 CD 显示已停用。')
            return
        if template.path:
            entry = replace(entry, name=template.name)
        self.app_config.overlays.append(entry)
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.apply_entry(entry)
        self._refresh_overlay_views()

    def _remove_selected_overlay(self) -> None:
        entry = self._selected_overlay()
        if entry is None or entry.source_type == OverlaySourceType.BUILTIN:
            return
        self.app_config.overlays = [item for item in self.app_config.overlays if item.id != entry.id]
        self.app_config.overlay_restore_ids = [key for key in self.app_config.overlay_restore_ids if key != entry.id]
        self.overlay_manager.remove_entry(entry.id)
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _enable_all_overlays(self) -> None:
        self.app_config.overlays = [replace(entry, enabled=True) for entry in self.app_config.overlays]
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.sync_entries(self.app_config.overlays)
        self._refresh_overlay_views()

    def _disable_all_overlays(self) -> None:
        self.app_config.overlays = [replace(entry, enabled=False) for entry in self.app_config.overlays]
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.sync_entries(self.app_config.overlays)
        self._refresh_overlay_views()

    def _apply_overlay_name(self) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None:
            return
        name = self.overlay_page.name_edit.text().strip() or entry.name
        if name != entry.name:
            self._replace_overlay_entry(replace(entry, name=name))

    def _apply_overlay_source_value(self) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None or entry.source_type != OverlaySourceType.URL:
            return
        value = self.overlay_page.source_value_edit.text().strip()
        if value and value != entry.source_value:
            self._replace_overlay_entry(replace(entry, source_value=value))

    def _apply_overlay_enabled(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and checked != entry.enabled:
            self._replace_overlay_entry(replace(entry, enabled=checked))

    def _apply_template_setting(self, key: str, value: object) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None:
            updated = with_template_value(entry, key, value)
            if updated != entry:
                self._replace_overlay_entry(updated)

    def _apply_overlay_locked(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and checked != entry.locked:
            self._replace_overlay_entry(replace(entry, locked=checked))


    def _apply_overlay_click_through(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and checked != entry.click_through:
            self._replace_overlay_entry(replace(entry, click_through=checked))

    def _apply_overlay_opacity(self, value: int) -> None:
        self.overlay_page.opacity_value.setText(f"{value}%")
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None:
            return
        opacity = max(0.1, min(1.0, value / 100.0))
        if abs(opacity - entry.opacity) > 0.0001:
            self._replace_overlay_entry(replace(entry, opacity=opacity))

    def _apply_overlay_font_size(self, value: int) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        factor = value / 100.0
        if entry is not None and abs(factor - entry.font_scale) > 0.0001:
            self._replace_overlay_entry(replace(entry, font_scale=factor, scale=1.0))

    def _reset_selected_overlay_layout(self) -> None:
        entry = self._selected_overlay()
        if entry is not None:
            self._replace_overlay_entry(replace(entry, geometry=None, font_scale=1.0, scale=1.0))

    def _apply_overlay_dimensions(self, *_args) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None:
            return
        geometry = entry.geometry or OverlayGeometry(100, 100, 0, 0)
        updated = OverlayGeometry(geometry.x, geometry.y, self.overlay_page.width_edit.value(), self.overlay_page.height_edit.value())
        if updated != entry.geometry:
            self._replace_overlay_entry(replace(entry, geometry=updated))


    def showEvent(self, event) -> None:
        super().showEvent(event)
        schedule_initial_placement(self)

    def _init_window(self) -> None:
        self.resize(1200, 800)
        self.setWindowTitle(f"{APP_NAME} · 战斗分析")
        icon_path = _app_icon_path()
        if icon_path is not None:
            self.setWindowIcon(QIcon(str(icon_path)))
        self.navigationInterface.setExpandWidth(220)
        self.navigationInterface.setCollapsible(False)
        self.addSubInterface(self.home_page, FIF.HOME, "首页")
        self.addSubInterface(self.overlay_page, FIF.APPLICATION, "悬浮窗")
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.records_page, FIF.HISTORY, "战斗日志", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.logs_page, FIF.DOCUMENT, "运行日志", NavigationItemPosition.SCROLL)
        self.addSubInterface(self.settings_page, FIF.SETTING, "设置", NavigationItemPosition.BOTTOM)

    def _bind_events(self) -> None:
        self.home_page.start_service_btn.clicked.connect(self._toggle_capture)
        self.overlay_page.status_card.visibility_button.clicked.connect(self._toggle_overlay_visibility)
        self.overlay_page.overlay_list.currentItemChanged.connect(self._sync_overlay_selection)
        self.overlay_page.add_url_btn.clicked.connect(self._add_url_overlay)
        self.overlay_page.add_file_btn.clicked.connect(self._add_file_overlay)
        self.overlay_page.remove_btn.clicked.connect(self._remove_selected_overlay)
        self.overlay_page.enable_all_btn.clicked.connect(self._enable_all_overlays)
        self.overlay_page.disable_all_btn.clicked.connect(self._disable_all_overlays)
        self.overlay_page.reset_layout_btn.clicked.connect(self._reset_selected_overlay_layout)
        self.overlay_page.name_edit.editingFinished.connect(self._apply_overlay_name)
        self.overlay_page.source_value_edit.editingFinished.connect(self._apply_overlay_source_value)
        self.overlay_page.setting_changed.connect(self._apply_template_setting)
        self.overlay_page.enabled_switch.checkedChanged.connect(self._apply_overlay_enabled)
        self.overlay_page.visible_switch.checkedChanged.connect(self._apply_overlay_visible)
        self.overlay_page.locked_switch.checkedChanged.connect(self._apply_overlay_locked)
        self.overlay_page.click_switch.checkedChanged.connect(self._apply_overlay_click_through)
        self.overlay_page.opacity_slider.valueChanged.connect(self._apply_overlay_opacity)
        self.overlay_page.font_size_edit.valueChanged.connect(self._apply_overlay_font_size)
        self.overlay_page.width_edit.valueChanged.connect(self._apply_overlay_dimensions)
        self.overlay_page.height_edit.valueChanged.connect(self._apply_overlay_dimensions)
        self.records_page.reload_btn.clicked.connect(self._load_records)
        self.records_page.import_trace_btn.clicked.connect(self._import_trace_logs)
        self.records_page.remove_record_btn.clicked.connect(self._remove_selected_history)
        self.records_page.rename_record_btn.clicked.connect(self._rename_selected_history)
        self.records_page.open_folder_btn.clicked.connect(self._open_history_folder)
        self.records_page.load_overlay_btn.clicked.connect(self._load_selected_history)
        self.records_page.analysis_detail_btn.clicked.connect(self._inspect_selected_history)
        self.records_page.return_live_btn.clicked.connect(self._return_live_overlay)
        self.records_page.record_list.currentItemChanged.connect(self._sync_record_selection)
        self.records_page.record_list.itemSelectionChanged.connect(self._sync_record_selection)
        self.settings_page.port_edit.valueChanged.connect(self._apply_service_port)
        self.settings_page.theme_combo.currentIndexChanged.connect(self._apply_theme_mode)
        self.settings_page.gui_font_edit.valueChanged.connect(self._apply_gui_font_size)
        self.settings_page.log_dir_btn.clicked.connect(self._choose_log_dir)
        self.settings_page.log_dir_refresh_btn.clicked.connect(self._refresh_log_dir_size)
        self.settings_page.hotkey_edit.editingFinished.connect(self._apply_overlay_hotkey)
        self.settings_page.merge_multi_phase_switch.checkedChanged.connect(self._apply_merge_multi_phase_enemy_battles)
        stacked = getattr(self, "stackedWidget", None)
        if stacked is not None:
            stacked.currentChanged.connect(self._handle_current_interface_changed)

    def _refresh_settings_page(self) -> None:
        self.settings_page.gui_font_edit.blockSignals(True)
        self.settings_page.gui_font_edit.setValue(self.app_config.gui_font_percent)
        self.settings_page.gui_font_edit.blockSignals(False)
        self.settings_page.port_edit.blockSignals(True)
        self.settings_page.port_edit.setValue(self.app_config.service.ws_port)
        self.settings_page.port_edit.blockSignals(False)
        self.settings_page.theme_combo.blockSignals(True)
        self.settings_page.hotkey_edit.blockSignals(True)
        self.settings_page.merge_multi_phase_switch.blockSignals(True)
        self.settings_page.set_theme_mode(self.app_config.theme_mode)
        self.settings_page.set_hotkey(self.app_config.toggle_overlays_hotkey)
        self.settings_page.set_merge_multi_phase_enemy_battles(self.app_config.service.merge_multi_phase_enemy_battles)
        self.settings_page.theme_combo.blockSignals(False)
        self.settings_page.hotkey_edit.blockSignals(False)
        self.settings_page.merge_multi_phase_switch.blockSignals(False)
        self.settings_page.set_log_dir(self.app_config.service.log_dir)
        self.settings_page.set_service_info(self.app_config.service)
        self._refresh_log_dir_size()
        self._update_overlay_shortcut()

    def _refresh_log_dir_size(self) -> None:
        self.settings_page.set_log_size(_directory_size(self.app_config.service.log_dir))

    def _apply_gui_font_size(self, value):
        self.app_config.gui_font_percent = value
        self.gui_typography.set_scale(value/100)
        save_app_config(self.app_config, self.config_path)

    def _apply_merge_multi_phase_enemy_battles(self, checked: bool) -> None:
        if checked == self.app_config.service.merge_multi_phase_enemy_battles:
            return
        self.app_config.service.merge_multi_phase_enemy_battles = checked
        service = getattr(self.service_controller, "_service", None)
        active_session = getattr(service, "active_session", None) if service is not None else None
        if active_session is not None:
            active_session.merge_multi_phase_enemy_battles = checked
        save_app_config(self.app_config, self.config_path)

    def _choose_log_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "选择日志目录", str(self.app_config.service.log_dir))
        if not selected:
            return
        target = Path(selected).resolve()
        self.app_config.service.log_dir = target
        save_app_config(self.app_config, self.config_path)
        self._refresh_settings_page()
        self._load_records()

    def _start_service_if_needed(self) -> None:
        self._auto_start_attempted = True
        if self._closing or self._stop_pending or self.service_controller.is_running():
            return
        if not self._ensure_npcap_ready():
            self._update_service_status()
            return
        if not _is_valid_game_dir(self.app_config.service.dll_dir):
            self._show_game_dir_infobar()
            self._capture_error = '未设置有效游戏目录；仍可使用历史分析。'
            LOGGER.warning(self._capture_error)
            self._update_service_status()
            return
        if not self.app_config.service.rsa_key_txt.is_file():
            self._show_capture_error('缺少抓包密钥；请准备 _internal/secrets/client_privkey.pem。仍可使用历史分析。')
            return
        self._capture_error = ''
        if self._capture_error_bar is not None:
            self._capture_error_bar.close()
            self._capture_error_bar = None
        self._clear_game_dir_infobar()
        if not self.service_controller.is_running():
            self.current_state = ServiceState.WAITING_GAME
            self._set_overlay_port(self.app_config.service.ws_port)
            try:
                self.service_controller.start()
            except Exception as exc:
                LOGGER.exception('Unable to start capture thread')
                self._show_capture_error(f'抓包启动失败：{exc}')
        self._update_service_status()

    def _auto_start_service(self):
        if not self._auto_start_attempted and not self._closing:
            self._start_service_if_needed()

    def _toggle_capture(self):
        self._auto_start_attempted = True
        if self.service_controller.lifecycle == CaptureLifecycle.RUNNING:
            self._stop_pending = True
            self._capture_error = ''
            self.service_controller.stop()
            self._update_service_status()
            self._finish_service_stop()
        elif self.service_controller.lifecycle == CaptureLifecycle.STOPPED:
            self._start_service_if_needed()

    def _show_capture_error(self, message):
        self._capture_error = message
        LOGGER.warning(message)
        if self._capture_error_bar is not None:
            self._capture_error_bar.close()
        self._capture_error_bar = InfoBar.warning(
            title='抓包不可用', content=message, duration=-1,
            position=InfoBarPosition.TOP, parent=self)
        self._capture_error_bar.closedSignal.connect(lambda: setattr(self, '_capture_error_bar', None))
        self._update_service_status()

    def _set_overlay_port(self, port: int) -> None:
        self.overlay_manager.ws_port = port
        for window in self.overlay_manager._windows.values():
            if window.config.ws_port != port:
                window.config.ws_port = port
                window._load_overlay()

    def _apply_service_port(self, port: int) -> None:
        if port == self.app_config.service.ws_port:
            return
        self.app_config.service.ws_port = port
        save_app_config(self.app_config, self.config_path)
        self.settings_page.port_hint.setText('端口已保存；下次启动抓包生效。')
        self._update_service_status()

    def _finish_service_stop(self) -> None:
        if self._closing or (not self._stop_pending and self.service_controller.lifecycle != CaptureLifecycle.STOPPED):
            return
        if self.service_controller.is_running():
            self._stop_pending = True
            self._update_service_status()
            QTimer.singleShot(100, self._finish_service_stop)
            return
        self._stop_pending = False
        self.current_session_id = None
        self.current_flow = None
        self.current_state = ServiceState.WAITING_GAME
        self.current_squad = []
        self.home_page.status_card.set_squad_members([])
        self._update_service_status()

    def _clear_game_dir_infobar(self) -> None:
        if self._game_dir_infobar is None:
            return
        self._game_dir_infobar.close()
        self._game_dir_infobar = None

    def _clear_restart_required_infobar(self) -> None:
        if self._restart_required_infobar is None:
            return
        self._restart_required_infobar.close()
        self._restart_required_infobar = None

    def _clear_npcap_infobar(self) -> None:
        if self._npcap_infobar is None:
            return
        self._npcap_infobar.close()
        self._npcap_infobar = None

    def _show_game_dir_infobar(self) -> None:
        if self._game_dir_infobar is not None:
            return
        bar = InfoBar.error(
            title="错误",
            content="没有找到游戏安装目录，请手动指定 Endfield Game 目录",
            duration=-1,
            position=InfoBarPosition.TOP,
            parent=self,
        )
        button = PrimaryPushButton("选择游戏目录", bar)
        button.clicked.connect(self._choose_game_dir)
        bar.addWidget(button)
        self._game_dir_infobar = bar
        bar.closedSignal.connect(lambda: setattr(self, '_game_dir_infobar', None))

    def _show_restart_required_infobar(self) -> None:
        if self._restart_required_infobar is not None:
            return
        self._restart_required_infobar = InfoBar.error(
            title="错误",
            content="需要先开启本工具再开启游戏，请重开游戏。",
            duration=-1,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _show_npcap_infobar(self) -> None:
        if self._npcap_infobar is not None:
            return
        message = '未检测到 Npcap，实时抓包不可用；仍可导入和分析本地日志。安装后再启动抓包。'
        self._capture_error = '未检测到 Npcap；仍可使用历史分析。'
        LOGGER.warning(message)
        self._npcap_infobar = InfoBar.warning(
            title="缺少 Npcap",
            content=message,
            duration=-1,
            position=InfoBarPosition.TOP,
            parent=self,
        )
        self._npcap_infobar.closedSignal.connect(lambda: setattr(self, '_npcap_infobar', None))

    def _sync_restart_required_infobar(self) -> None:
        if self.service_controller.lifecycle == CaptureLifecycle.RUNNING and self.current_state == ServiceState.WAITING_RESTART:
            self._show_restart_required_infobar()
            return
        self._clear_restart_required_infobar()

    def _ensure_npcap_ready(self) -> bool:
        if has_npcap():
            self._clear_npcap_infobar()
            return True
        self._show_npcap_infobar()
        return False

    def _choose_game_dir(self) -> None:
        start_dir = str(self.app_config.service.dll_dir) if self.app_config.service.dll_dir else str(ROOT)
        selected = QFileDialog.getExistingDirectory(self, "选择 Endfield Game 目录", start_dir)
        if not selected:
            return
        target = Path(selected).resolve()
        if not _is_valid_game_dir(target):
            QMessageBox.warning(self, "目录无效", "所选目录中没有找到 Endfield.exe 或 GameAssembly.dll。")
            self._show_game_dir_infobar()
            return
        self.app_config.service.dll_dir = target
        self.app_config.service.game_exe = "Endfield.exe"
        save_app_config(self.app_config, self.config_path)
        self._clear_game_dir_infobar()
        self._refresh_settings_page()
        self._update_service_status()

    def _ensure_game_directory_ready(self) -> None:
        # Defer the single automatic attempt until the window/event loop exists.
        # Prerequisite failure leaves history usable; no mandatory setup wizard.
        QTimer.singleShot(0, self._auto_start_service)

    def _apply_theme_mode(self, *_args) -> None:
        mode = self.settings_page.theme_mode()
        if mode != self.app_config.theme_mode:
            self.app_config.theme_mode = mode
            save_app_config(self.app_config, self.config_path)
        self._apply_gui_theme(mode)

    def _apply_overlay_hotkey(self, *_args) -> None:
        hotkey = self.settings_page.hotkey()
        if self._update_overlay_shortcut(hotkey):
            if hotkey != self.app_config.toggle_overlays_hotkey:
                self.app_config.toggle_overlays_hotkey = hotkey
                save_app_config(self.app_config, self.config_path)
            self.settings_page.hotkey_edit.blockSignals(True)
            self.settings_page.set_hotkey(self.app_config.toggle_overlays_hotkey)
            self.settings_page.hotkey_edit.blockSignals(False)
            return
        self.settings_page.hotkey_edit.blockSignals(True)
        self.settings_page.set_hotkey(self.app_config.toggle_overlays_hotkey)
        self.settings_page.hotkey_edit.blockSignals(False)

    def _update_overlay_shortcut(self, hotkey: str | None = None) -> bool:
        target_hotkey = hotkey or self.app_config.toggle_overlays_hotkey or "Ctrl+O"
        if sys.platform != "win32" or USER32 is None:
            self.settings_page.set_hotkey_status("当前平台不支持全局热键", is_error=True)
            return False
        native = _portable_hotkey_to_native(target_hotkey)
        if native is None:
            self.settings_page.set_hotkey_status("快捷键格式无效，请换一个组合键", is_error=True)
            return False
        hwnd = int(self.winId())
        previous_hotkey = self._registered_hotkey
        if self._global_hotkey_registered:
            USER32.UnregisterHotKey(hwnd, GLOBAL_HOTKEY_ID)
            self._global_hotkey_registered = False
        modifiers, vk = native
        if USER32.RegisterHotKey(hwnd, GLOBAL_HOTKEY_ID, modifiers | MOD_NOREPEAT, vk):
            self._global_hotkey_registered = True
            self._registered_hotkey = target_hotkey
            self.settings_page.set_hotkey_status(f"全局热键设定成功：{target_hotkey}")
            return True
        if previous_hotkey:
            previous_native = _portable_hotkey_to_native(previous_hotkey)
            if previous_native is not None:
                prev_modifiers, prev_vk = previous_native
                if USER32.RegisterHotKey(hwnd, GLOBAL_HOTKEY_ID, prev_modifiers | MOD_NOREPEAT, prev_vk):
                    self._global_hotkey_registered = True
                    self._registered_hotkey = previous_hotkey
        self.settings_page.set_hotkey_status(f"快捷键冲突：{target_hotkey}", is_error=True)
        return False

    def _unregister_overlay_hotkey(self) -> None:
        if sys.platform != "win32" or USER32 is None or not self._global_hotkey_registered:
            return
        USER32.UnregisterHotKey(int(self.winId()), GLOBAL_HOTKEY_ID)
        self._global_hotkey_registered = False

    def _toggle_overlay_visibility(self) -> None:
        shown = {entry.id for entry in self.app_config.overlays if entry.enabled and not entry.hidden}
        if shown:
            self.app_config.overlay_restore_ids = [entry.id for entry in self.app_config.overlays if entry.id in shown]
            self.app_config.overlays = [replace(entry, hidden=True) if entry.id in shown else entry
                                        for entry in self.app_config.overlays]
        else:
            restore = set(self.app_config.overlay_restore_ids)
            self.app_config.overlays = [replace(entry, hidden=False) if not restore or entry.id in restore else entry
                                        for entry in self.app_config.overlays]
            self.app_config.overlay_restore_ids = []
        self.overlay_manager.sync_entries(self.app_config.overlays)
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _apply_overlay_visible(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and entry.enabled:
            self._replace_overlay_entry(replace(entry, hidden=not bool(checked)))

    def _apply_gui_theme(self, mode: str | None = None) -> None:
        setTheme(_theme_from_mode(mode or self.app_config.theme_mode))
        self.setCustomBackgroundColor("#f3f3f3", "#202020")
        dark = isDarkTheme()
        page_qss = "background: transparent;"
        label_color = "#f5f5f5" if dark else "#202020"
        subtle_label_color = "#d0d0d0" if dark else "#606060"
        text_edit_qss = (
            "QPlainTextEdit { background: rgba(18, 18, 18, 0.94); color: #f5f5f5; border-radius: 8px; }"
            if dark
            else "QPlainTextEdit { background: rgba(255, 255, 255, 0.94); color: #202020; border-radius: 8px; }"
        )
        table_qss = (
            "QTableView { background: transparent; alternate-background-color: rgba(255,255,255,0.04); color: #f5f5f5; gridline-color: rgba(255,255,255,0.08); "
            "border: none; border-radius: 12px; selection-background-color: rgba(255,255,255,0.12); selection-color: #ffffff; } "
            "QHeaderView { background: transparent; } "
            "QHeaderView::section { background: rgba(42, 42, 42, 0.96); color: #f5f5f5; border: none; "
            "border-bottom: 1px solid rgba(255,255,255,0.08); padding: 6px 8px; } "
            "QHeaderView::section:first { border-top-left-radius: 12px; } "
            "QHeaderView::section:last { border-top-right-radius: 12px; } "
            "QTableCornerButton::section { background: rgba(42, 42, 42, 0.96); border: none; border-top-left-radius: 12px; }"
            if dark
            else "QTableView { background: transparent; alternate-background-color: rgba(0,0,0,0.03); color: #202020; gridline-color: rgba(0,0,0,0.08); "
            "border: none; border-radius: 12px; selection-background-color: rgba(0,0,0,0.08); selection-color: #202020; } "
            "QHeaderView { background: transparent; } "
            "QHeaderView::section { background: rgba(245, 245, 245, 0.96); color: #202020; border: none; "
            "border-bottom: 1px solid rgba(0,0,0,0.08); padding: 6px 8px; } "
            "QHeaderView::section:first { border-top-left-radius: 12px; } "
            "QHeaderView::section:last { border-top-right-radius: 12px; } "
            "QTableCornerButton::section { background: rgba(245, 245, 245, 0.96); border: none; border-top-left-radius: 12px; }"
        )
        table_shell_qss = (
            "QFrame#rankingTableShell { background: rgba(28, 28, 28, 0.92); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }"
            if dark
            else "QFrame#rankingTableShell { background: rgba(255, 255, 255, 0.92); border: 1px solid rgba(0,0,0,0.06); border-radius: 12px; }"
        )
        form_page_qss = (
            "QLabel { color: #f5f5f5; } "
            "QCheckBox { color: #f5f5f5; } "
            "QLineEdit, QComboBox, QKeySequenceEdit { color: #f5f5f5; background: rgba(28, 28, 28, 0.92); border-radius: 6px; }"
            if dark
            else "QLabel { color: #202020; } "
            "QCheckBox { color: #202020; } "
            "QLineEdit, QComboBox, QKeySequenceEdit { color: #202020; background: rgba(255, 255, 255, 0.92); border-radius: 6px; }"
        )
        metric_tile_qss = (
            "QFrame#battleMetricTile { background: rgba(34, 34, 34, 0.94); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; }"
            if dark
            else "QFrame#battleMetricTile { background: rgba(255, 255, 255, 0.82); border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 12px; }"
        )
        for page in (self.home_page, self.overlay_page, self.records_page, self.settings_page, self.logs_page):
            page.viewport().setStyleSheet(page_qss)
            page.container.setStyleSheet(page_qss)
            page.setStyleSheet(page_qss)
        self.overlay_page.container.setStyleSheet(form_page_qss)
        self.settings_page.container.setStyleSheet(form_page_qss)
        self.records_page.container.setStyleSheet(
            f"QLabel {{ color: {label_color}; }} "
            f"QTableView {{ color: {label_color}; }} "
            f"QHeaderView::section {{ color: {label_color}; }} "
            f"QLabel[description='true'] {{ color: {subtle_label_color}; }}"
        )
        self.logs_page.log_view.setStyleSheet(text_edit_qss)
        self.records_page.table.setStyleSheet(table_qss)
        self.records_page.table_shell.setStyleSheet(table_shell_qss)
        for tile in self.records_page.findChildren(QFrame, "battleMetricTile"):
            tile.setStyleSheet(metric_tile_qss)
        self.home_page.update()
        self.overlay_page.update()
        self.records_page.update()
        self.settings_page.update()
        self.logs_page.update()
        self.update()

    def nativeEvent(self, eventType, message):  # noqa: N802
        if sys.platform == "win32" and USER32 is not None:
            event_type = bytes(eventType).decode(errors="ignore")
            if event_type in {"windows_generic_MSG", "windows_dispatcher_MSG"}:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and int(msg.wParam) == GLOBAL_HOTKEY_ID:
                    self._toggle_overlay_visibility()
                    return True, 0
        return super().nativeEvent(eventType, message)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._closing = True
        self._history_cancel.set()
        self._history_generation += 1
        self._trace_import_generation += 1
        self._records_generation += 1
        self.queue_timer.stop()
        logging.getLogger().removeHandler(self.log_handler)
        self._unregister_overlay_hotkey()
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.close_all()
        self.service_controller.stop()
        self.service_controller.join(timeout=5.0)
        super().closeEvent(event)


def run_gui(
    config_path: Path | None = None,
    debug_enabled: bool = False,
    debug_dir: Path | None = None,
) -> int:
    target_path = config_path or default_config_path()
    app_config = load_app_config(target_path)
    app_config.service.debug_enabled = debug_enabled
    if debug_dir is not None:
        app_config.service.debug_dir = debug_dir.resolve()
    configure_logging(app_config.service.log_level)

    app = QApplication.instance() or QApplication([])
    app.setApplicationName(APP_NAME)
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
    return app.exec()

