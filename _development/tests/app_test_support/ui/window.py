from dataclasses import replace
import pytest
from PySide6.QtCore import QCoreApplication, QEvent
import endfield_pcap.settings as gui_config
import endfield_pcap.gui.main as gui_main
from endfield_pcap.models import OverlayEntry
from endfield_pcap.models import OverlaySourceType

def entry(**changes):
    return replace(OverlayEntry("controls", "damage", OverlaySourceType.BUILTIN, "damage", False, False, False), **changes)

@pytest.fixture
def main_window(app, monkeypatch, tmp_path):
    config = gui_config.AppConfig(service=gui_config.default_service_config(),
        overlays=[entry(), entry(id="buff", name="extra", source_value="damage")])
    config.service.log_dir = tmp_path
    config.theme_mode = "dark"
    monkeypatch.setattr(gui_main.MainWindow, "_ensure_game_directory_ready", lambda self: True)
    monkeypatch.setattr(gui_main.MainWindow, "_update_overlay_shortcut", lambda self: None)
    monkeypatch.setattr(gui_main.MainWindow, "_update_gui_shortcut", lambda self,*args: None)
    monkeypatch.setattr(gui_main.MainWindow, '_schedule_update_check', lambda self: None)
    gui_main.setTheme(gui_main._theme_from_mode(config.theme_mode))
    window = gui_main.MainWindow(config, tmp_path / "settings.json")
    window.setMicaEffectEnabled(False)
    window.show()
    yield window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
