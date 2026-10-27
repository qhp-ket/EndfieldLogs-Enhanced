"""Coordinate input, visual identity and capture subscriptions on one owner thread."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import threading

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IndependentServiceState:
    input_status: dict
    input_running: bool
    visual_status: str
    combo_snapshot: dict | None


class IndependentServiceController:
    def __init__(self, input_controller, vision_controller, set_capture_streams, settings):
        self.input = input_controller
        self.vision = vision_controller
        self.settings = settings
        self._set_capture_streams = set_capture_streams
        self._owner = threading.get_ident()
        self._subscriptions = frozenset()
        self._preview = False
        self._session = None
        self._input_error = None
        self._closed = False

    def _assert_owner(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('独立服务只能由所属线程协调')

    def game_executable(self):
        service = self.settings.current.service
        return service.dll_dir / service.game_exe

    def set_requirements(self, subscriptions):
        self._assert_owner()
        if self._closed:
            return
        self._subscriptions = frozenset(subscriptions)
        self._set_capture_streams(self._subscriptions & {'analysis_snapshot', 'analysis_summary'})
        self._update_vision()

    def _update_vision(self):
        self.vision.game_exe = self.game_executable()
        self.vision.set_enabled('combo_snapshot' in self._subscriptions or self._preview)

    def set_preview(self, active):
        self._assert_owner()
        if not self._closed:
            self._preview = bool(active)
            self._update_vision()

    def start_input(self):
        self._assert_owner()
        if self._closed:
            return
        try:
            self.input.start(self.game_executable(), self.settings.current.service.log_dir, elevated=True)
        except Exception:
            self.settings.current.input_recording_enabled = False
            raise

    def toggle_input(self):
        self._assert_owner()
        if self._closed:
            return
        if self.input.running:
            self.input.stop()
        else:
            self.start_input()
        self.settings.set_input_recording_enabled(self.input.running)

    def set_session(self, session):
        self._assert_owner()
        if not self._closed and session != self._session:
            self._session = session
            self.vision.set_identity([], session)

    def set_members(self, members):
        self._assert_owner()
        if not self._closed:
            self.vision.set_identity(members, self._session)

    def set_trace(self, path):
        self._assert_owner()
        if not self._closed:
            self.input.set_trace(path)

    def capture_stopped(self):
        self._assert_owner()
        if not self._closed:
            self.input.set_trace(None)
            self._session = None
            self.vision.set_identity([], None)

    def poll(self):
        self._assert_owner()
        state = self.input.snapshot()
        failure = state.get('error') if state.get('status') == 'error' else None
        if failure and failure != self._input_error:
            LOGGER.error('输入记录故障：%s', failure)
        self._input_error = failure
        visual = self.vision.take_snapshot()
        return IndependentServiceState(state, self.input.running,
            self.vision.state['status'], visual)

    def configure_vision(self, value):
        self._assert_owner()
        self.vision.configure(value)
        self.settings.set_vision_settings(value)

    def close(self):
        self._assert_owner()
        self._closed = True
        self._preview = False
        self._subscriptions = frozenset()
