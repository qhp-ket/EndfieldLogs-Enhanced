from urllib.parse import parse_qs, urlsplit
from dataclasses import replace
import json
from PySide6.QtWidgets import QLineEdit
from app_test_support.ui.window import main_window
from endfield_pcap.gui.config import load_app_config, save_app_config


def test_browser_token_migrates_persists_and_is_not_in_config_repr(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{"service":{}}', encoding='utf8')
    config = load_app_config(path)
    token = config.service.ws_browser_token
    assert len(token) == 43 and token not in repr(config.service)
    assert load_app_config(path).service.ws_browser_token != token
    save_app_config(config, path)
    assert load_app_config(path).service.ws_browser_token == token
    assert replace(config.service).ws_browser_token == token
    payload = json.loads(path.read_text(encoding='utf8'))
    payload['service']['ws_browser_token'] = 'too-short'
    path.write_text(json.dumps(payload), encoding='utf8')
    assert len(load_app_config(path).service.ws_browser_token) == 43


def test_settings_url_uses_saved_port_and_masks_capability(main_window, app):
    window = main_window
    page = window.settings_page
    assert page.browser_ws_edit.echoMode() == QLineEdit.EchoMode.Password
    assert page.browser_ws_edit.isReadOnly()
    window._apply_service_port(31234)
    url = urlsplit(page.browser_ws_edit.text())
    assert url.hostname == '127.0.0.1' and url.port == 31234
    assert parse_qs(url.query) == {'analysis': ['summary'],
        'access_token': [window.app_config.service.ws_browser_token]}
    previous = app.clipboard().text()
    try:
        page.copy_browser_ws_btn.click()
        assert app.clipboard().text() == page.browser_ws_edit.text()
    finally:
        app.clipboard().setText(previous)
