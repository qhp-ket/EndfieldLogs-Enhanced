from dataclasses import replace
import json
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
