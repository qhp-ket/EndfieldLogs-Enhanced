from __future__ import annotations
import logging
from PySide6.QtCore import QTimer
from qfluentwidgets import InfoBar, InfoBarPosition, PrimaryPushButton
from endfield_pcap.models import ServiceState
from endfield_pcap.capture.npcap import has_npcap
from endfield_pcap.gui.service import CaptureLifecycle
from endfield_pcap.gui.pages.settings.paths import _is_valid_game_dir


LOGGER = logging.getLogger(__name__)


class CaptureActions:
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

    def _ensure_game_directory_ready(self) -> None:
        # Defer the single automatic attempt until the window/event loop exists.
        # Prerequisite failure leaves history usable; no mandatory setup wizard.
        QTimer.singleShot(0, self._auto_start_service)


    def _bind_home_events(self) -> None:
        self.home_page.start_service_btn.clicked.connect(self._toggle_capture)
