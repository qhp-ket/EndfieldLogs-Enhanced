"""The retired CD display cannot be re-enabled by saved settings or WS."""
import asyncio
import json

from endfield_pcap import gui_config, overlay_host
from endfield_pcap.models import ServiceObserver
from test_overlay_controls import entry
from test_live_snapshot_publisher import service_factory


def test_config_removes_retired_combo_and_never_adds_it_back(tmp_path):
    assert 'combo_skill' not in {row.source_value for row in gui_config.default_overlay_entries()}
    path = tmp_path / 'settings.json'
    config = gui_config.AppConfig(service=gui_config.default_service_config(),
                                 overlays=[entry(), entry(id='retired', source_value='combo_skill', enabled=True)])
    gui_config.save_app_config(config, path)
    restored = gui_config.load_app_config(path)
    assert 'combo_skill' not in {row.source_value for row in restored.overlays}
    manager = overlay_host.OverlayManager(1, visible=False)
    manager.apply_entry(entry(id='retired', source_value='combo_skill', enabled=True))
    assert not manager._entries and not manager.opened_window_count()


def test_retired_combo_has_no_service_analysis_input_queue_or_ws_frames(service_factory):
    async def run():
        callbacks = []
        service = service_factory(observer=ServiceObserver(on_combo_snapshot=callbacks.append))
        service.set_analysis_streams({'combo_snapshot'})
        assert not service._analysis_streams and not service._analysis_required('combo_snapshot')
        assert not hasattr(service, 'combo_publisher') and not hasattr(service, '_combo_inputs')
        class Socket:
            def __init__(self): self.frames = []
            async def send(self, text): self.frames.append(json.loads(text))
            async def wait_closed(self): pass
        socket = Socket()
        await service._ws_handler(socket)
        assert not callbacks
        assert [row['type'] for row in socket.frames] == ['hello', 'analysis_snapshot', 'buff_snapshot']
    asyncio.run(run())
