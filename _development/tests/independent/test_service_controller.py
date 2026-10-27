"""Optional service demand and capture associations have separate lifetimes."""
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

from endfield_pcap.application.independent import IndependentServiceController
from endfield_pcap.application.settings import SettingsStore
from endfield_pcap.settings import AppConfig, default_service_config, load_app_config


class Input:
    def __init__(self):
        self.running = False
        self.calls = []

    def start(self, game, folder, *, elevated):
        self.running = True
        self.calls.append(('start', game, folder, elevated))

    def stop(self, wait=False):
        self.running = False
        self.calls.append(('stop', wait))

    def set_trace(self, path):
        self.calls.append(('trace', path))

    def snapshot(self):
        return {'status': 'waiting_game', 'count': 0, 'lost': 0}


class Vision:
    def __init__(self):
        self.enabled = False
        self.identities = []
        self.state = {'status': 'waiting'}

    def set_enabled(self, value):
        self.enabled = value

    def set_identity(self, members, session):
        self.identities.append((list(members), session))

    def take_snapshot(self):
        return None

    def configure(self, config):
        self.config = config


@pytest.fixture
def controller(tmp_path):
    config = AppConfig(default_service_config())
    config.service.dll_dir = tmp_path / 'game'
    config.service.log_dir = tmp_path / 'logs'
    settings = SettingsStore(config, tmp_path / 'settings.json')
    streams = []
    value = IndependentServiceController(Input(), Vision(), streams.append, settings)
    return value, streams


def test_capture_stop_clears_associations_and_keeps_recording_and_visual_demand(controller):
    value, streams = controller
    value.start_input()
    value.set_requirements({'analysis_summary', 'combo_snapshot'})
    assert streams == [frozenset({'analysis_summary'})]
    assert value.vision.enabled
    assert value.input.calls[0] == ('start', value.game_executable(), value.settings.current.service.log_dir, True)
    value.set_session('session-a')
    members = [SimpleNamespace(templateid='character')]
    value.set_members(members)
    value.set_session('session-a')
    assert value.vision.identities[-1] == (members, 'session-a')
    value.set_trace(Path('trace-a.log'))
    value.capture_stopped()
    assert value.vision.identities[-1] == ([], None)
    assert value.input.calls[-1] == ('trace', None)
    assert value.input.running and value.vision.enabled
    value.set_session('session-b')
    assert value.vision.identities[-1] == ([], 'session-b')


def test_preview_and_overlay_each_keep_vision_enabled(controller):
    value, streams = controller
    value.set_requirements({'combo_snapshot'})
    value.set_preview(True)
    value.set_requirements(set())
    assert value.vision.enabled
    value.set_preview(False)
    assert not value.vision.enabled
    value.set_preview(True)
    value.set_requirements({'combo_snapshot'})
    value.set_preview(False)
    assert value.vision.enabled
    assert all(not stream for stream in streams)


def test_closed_controller_rejects_late_ui_requests_and_owner_thread_changes(controller):
    value, streams = controller
    failures = []
    def change():
        try:
            value.set_requirements({'combo_snapshot'})
        except RuntimeError as error:
            failures.append(error)
    thread = threading.Thread(target=change)
    thread.start(); thread.join(2)
    assert len(failures) == 1 and not streams
    value.close()
    value.set_preview(True)
    value.set_requirements({'combo_snapshot'})
    value.start_input()
    value.set_session('late')
    value.set_trace('late.log')
    assert not value.input.calls and not value.vision.enabled and not value.vision.identities


def test_toggle_persists_launch_preferences_without_restoring_runtime_state(controller):
    value, _ = controller
    value.settings.current.start_input_recording_on_launch = True
    value.toggle_input()
    assert value.input.running
    saved = load_app_config(value.settings.path)
    assert saved.start_input_recording_on_launch and not saved.input_recording_enabled
    value.toggle_input()
    assert not value.input.running
