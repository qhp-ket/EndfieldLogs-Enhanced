"""Visual CD configuration is optional; capture service never restores its old timer."""
import asyncio
import json
import endfield_pcap.settings as gui_config
import endfield_pcap.overlays.manager as overlay_host
from endfield_pcap.models import ServiceObserver
from app_test_support.ui.window import entry
from app_test_support.runtime.service import service_factory


def test_visual_combo_is_opt_in_and_preserves_existing_window_settings(tmp_path):
    assert not next(row for row in gui_config.default_overlay_entries() if row.source_value=='combo_skill').enabled
    path = tmp_path / 'settings.json'
    config = gui_config.AppConfig(service=gui_config.default_service_config(),
                                 overlays=[entry(), entry(id='retired', source_value='combo_skill', enabled=True)])
    gui_config.save_app_config(config, path)
    restored = gui_config.load_app_config(path)
    combo=next(row for row in restored.overlays if row.source_value=='combo_skill')
    assert combo.id=='retired' and combo.enabled
    defaults=gui_config.load_app_config(tmp_path/'new.json')
    assert not next(row for row in defaults.overlays if row.source_value=='combo_skill').enabled
    assert 'buff' not in {row.source_value for row in restored.overlays}


def test_retired_combo_has_no_service_analysis_input_queue_or_ws_frames(service_factory):
    async def run():
        callbacks = []
        service = service_factory(observer=ServiceObserver(on_combo_snapshot=callbacks.append))
        service.set_analysis_streams({'combo_snapshot'})
        assert not service._analysis_streams and not service._analysis_required('combo_snapshot')
        assert not hasattr(service, 'combo_publisher') and not hasattr(service, '_combo_inputs')
        class Socket:
            request_headers = {}
            path = '/ws'
            def __init__(self): self.frames = []
            async def send(self, text): self.frames.append(json.loads(text))
            async def wait_closed(self): pass
        socket = Socket()
        await service._ws_handler(socket)
        assert not callbacks
        assert [row['type'] for row in socket.frames] == ['hello', 'analysis_snapshot']
    asyncio.run(run())
