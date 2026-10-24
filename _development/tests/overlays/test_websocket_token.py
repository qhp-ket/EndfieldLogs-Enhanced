from types import SimpleNamespace
import pytest
from PySide6.QtCore import QUrlQuery
from app_test_support.ui.window import entry
from endfield_pcap.models import OverlaySourceType
from endfield_pcap.overlays.config import OverlayWindowConfig
from endfield_pcap.overlays.window import OverlayWindow


@pytest.mark.parametrize('remote,in_process', [(False, False), (False, True), (True, False), (True, True)])
def test_only_local_ws_template_url_receives_browser_capability(remote, in_process):
    selected = entry(source_type=OverlaySourceType.URL, source_value='https://outside.invalid/overlay') if remote else entry()
    token = 'A' * 43
    urls = []
    window = SimpleNamespace(entry=selected,
        config=OverlayWindowConfig(entry=selected, ws_port=29325, ws_browser_token=token,
                                   use_in_process_snapshots=in_process),
        webview=SimpleNamespace(setUrl=urls.append))
    OverlayWindow._load_overlay(window)
    assert len(urls) == 1
    assert QUrlQuery(urls[0]).queryItemValue('wsToken') == (token if not remote and not in_process else '')
    if remote or in_process:
        assert token not in urls[0].toString()
