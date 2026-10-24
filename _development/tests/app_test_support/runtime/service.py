from app_test_support.paths import ROOT
import pytest
import endfield_pcap.service.runtime.server as service_module
from endfield_pcap.service.runtime.server import DamageLogService
from endfield_pcap.service.config import ServiceConfig
from endfield_pcap.analysis.live.publisher import SnapshotPublisher

FIXTURE = (ROOT / "_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log").read_text(encoding="utf-8")

class FakeCapture:
    def start(self):
        self.started = True
    def stop(self):
        self.stopped = True
    def restore_default_filters(self):
        pass
    def device_snapshot(self):
        return []

@pytest.fixture
def service_factory(tmp_path, monkeypatch):
    # A real service constructor with capture, crypto and resource dependencies
    # replaced. No key, account, DLL, game process or capture session is opened.
    # Process isolation is exercised separately with the real parser/IPC.
    monkeypatch.setattr(service_module, "SnapshotPublisher", lambda **kwargs: SnapshotPublisher(summary=kwargs.get('summary', False)))
    monkeypatch.setattr(service_module, "MessageRegistry", lambda path: object())
    monkeypatch.setattr(service_module, "load_name_index", lambda path: {})
    monkeypatch.setattr(service_module, "_load_multi_phase_dungeon_map", lambda path: {})
    monkeypatch.setattr(service_module, "load_private_key_from_txt", lambda path: object())
    monkeypatch.setattr(service_module, "SRSABridge", lambda path: object())
    monkeypatch.setattr(service_module.CaptureManager, "create", lambda *args: FakeCapture())
    def create(*, trace_enabled=False, observer=None, status_file=None):
        config = ServiceConfig(
            ws_port=0, log_dir=tmp_path / "logs", log_level="INFO", game_exe="unused.exe",
            npcap_device="unused", dll_dir=tmp_path / "unused-dll",
            debug_enabled=False, debug_dir=tmp_path / "unused-debug",
            rsa_key_txt=tmp_path / "never-read-key", name_index_path=tmp_path / "unused-index",
            trace_file=tmp_path / "trace" / "trace_20261022-100000.log", trace_enabled=trace_enabled,
            status_file=status_file,
        )
        return DamageLogService(config, observer)
    return create
