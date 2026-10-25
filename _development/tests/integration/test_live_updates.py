"""Opt-in verification of the real public release API and GUI update worker."""
import os
import pytest
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.runtime.releases import VERSION
from endfield_pcap.gui import updates


@pytest.mark.skipif(os.environ.get('ENDFIELD_LIVE_UPDATE_TEST') != '1',
                    reason='opt-in real GitHub release query')
def test_public_latest_release_is_read_and_equal_version_is_not_an_update(main_window, app, monkeypatch):
    window = main_window
    monkeypatch.setattr(updates, '__version__', '0.0.0')
    window._check_updates(True)
    wait_for(lambda: window.settings_page.check_update_btn.isEnabled(), app, timeout=15000)
    result = window._update_release
    assert result is not None, window.settings_page.update_status.text()
    released_version = result['version']
    assert VERSION.fullmatch(released_version)
    assert result['published_at'] and 'EndfieldLogs-Enhanced/releases/tag/' in result['url']
    assert f'发现新版 {released_version}' in window.settings_page.update_status.text()
    assert window._update_bar is not None
    monkeypatch.setattr(updates, '__version__', released_version)
    window._check_updates(True)
    wait_for(lambda: window.settings_page.check_update_btn.isEnabled(), app, timeout=15000)
    assert window._update_release is None
    assert window.settings_page.update_status.text() == '未检测到新版'
    assert window._update_bar is None
