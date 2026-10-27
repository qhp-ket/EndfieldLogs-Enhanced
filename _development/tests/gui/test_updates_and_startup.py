"""Opt-in capture and background, stable-release-only version notices."""
import threading
from urllib.error import HTTPError
import pytest
from PySide6.QtCore import QTimer
from app_test_support.ui.window import main_window
from app_test_support.scenarios.trace import wait_for
from endfield_pcap.settings import load_app_config
from endfield_pcap.runtime import releases
import endfield_pcap.gui.updates as updates


def release(**changes):
    return dict(tag_name='v0.2.0', published_at='2026-10-25T01:00:00Z',
                draft=False, prerelease=False, **changes)


@pytest.mark.parametrize('change', [dict(draft=True), dict(prerelease=True),
    dict(tag_name='v0.2.0-dev.1'), dict(tag_name='uploader-3.0.12'),
    dict(tag_name='v0.0.1'), dict(published_at=None), dict(published_at='2026-10-25')])
def test_only_stable_application_versions_and_dated_releases(change):
    payload = release()
    payload.update(change)
    assert releases.release_update(payload, '0.1.0-dev.7') is None


def test_versions_ignore_and_trusted_download_destination():
    payload = release()
    payload['html_url'] = 'https://untrusted.invalid/'
    result = releases.release_update(payload, '0.1.0-dev.7')
    assert result == dict(version='0.2.0', published_at='2026-10-25T01:00:00+00:00',
        url='https://github.com/qhp-ket/EndfieldLogs-Enhanced/releases/tag/v0.2.0')
    assert releases.release_update(payload, '0.2.0') is None
    assert releases.release_update(payload, '0.2.0-dev.7')
    assert releases.release_update(payload, '0.1.0', 'v0.2.0') is None
    payload['tag_name'] = 'v0.2.1'
    assert releases.release_update(payload, '0.1.0', '0.2.0')


def test_patch_release_updates_old_installation_but_not_same_or_newer_version():
    payload = release()
    payload['tag_name'] = 'v0.1.1'
    assert releases.release_update(payload, '0.1.0')['version'] == '0.1.1'
    assert releases.release_update(payload, '0.1.1') is None
    payload['tag_name'] = 'v0.1.0'
    assert releases.release_update(payload, '0.1.1') is None


def test_no_stable_release_is_normal_and_requests_are_bounded(monkeypatch):
    def missing(request, timeout):
        assert request.full_url == releases.API and timeout == 8
        raise HTTPError(releases.API, 404, 'not found', {}, None)
    monkeypatch.setattr(releases, 'urlopen', missing)
    assert releases.check_update('0.1.0') is None


def test_default_capture_stays_stopped_and_settings_persist(main_window, monkeypatch):
    window = main_window
    assert not window.app_config.start_capture_on_launch
    assert window.app_config.check_updates_on_start
    monkeypatch.setattr(window, '_start_service_if_needed', lambda: pytest.fail('must stay stopped'))
    window._auto_start_service()
    assert not window._auto_start_attempted
    page = window.settings_page
    assert not page.start_capture_switch.isChecked() and page.auto_update_switch.isChecked()
    page.start_capture_switch.setChecked(True)
    page.auto_update_switch.setChecked(False)
    saved = load_app_config(window.config_path)
    assert saved.start_capture_on_launch and not saved.check_updates_on_start
    page.start_capture_switch.setChecked(False)
    assert not load_app_config(window.config_path).start_capture_on_launch


def test_input_launch_option_is_independent_of_manual_recording_and_legacy_state(main_window):
    window=main_window
    assert not window.app_config.start_input_recording_on_launch
    assert not window.settings_page.start_input_switch.isChecked()
    window.settings_page.start_input_switch.setChecked(True)
    saved=load_app_config(window.config_path)
    assert saved.start_input_recording_on_launch
    assert not window.input_controller.running
    assert not saved.input_recording_enabled
    window.settings_page.start_input_switch.setChecked(False)
    assert not load_app_config(window.config_path).start_input_recording_on_launch


def test_legacy_input_running_state_is_not_restored(tmp_path):
    import json
    path=tmp_path/'settings.json'
    path.write_text(json.dumps(dict(input_recording_enabled=True)),encoding='utf8')
    config=load_app_config(path)
    assert not config.input_recording_enabled and not config.start_input_recording_on_launch


def test_default_order_and_custom_order_survive_restart(tmp_path):
    from endfield_pcap.settings import default_overlay_entries,save_app_config
    assert [e.source_value for e in default_overlay_entries()]==['damage','combo_skill','uid_mask']
    path=tmp_path/'settings.json'
    config=load_app_config(path)
    config.overlays.reverse()
    save_app_config(config,path)
    assert [e.id for e in load_app_config(path).overlays]==[e.id for e in config.overlays]


def test_retired_input_and_buff_entries_do_not_reappear_or_disable_recording(tmp_path):
    import json
    path=tmp_path/'settings.json'
    template=tmp_path/'template.json'
    (tmp_path/'index.html').write_text('<html></html>',encoding='utf8')
    template.write_text(json.dumps(dict(schema_version=1,name='Old input',entry='index.html',
                                       subscriptions=['input_snapshot'])),encoding='utf8')
    path.write_text(json.dumps(dict(start_input_recording_on_launch=True,overlays=[
        dict(id='old-input',source_type='builtin',source_value='input',enabled=True),
        dict(id='old-buff',source_type='builtin',source_value='buff',enabled=True),
        dict(id='old-custom',source_type='file',source_value=str(template),enabled=True)])),encoding='utf8')
    config=load_app_config(path)
    assert [e.source_value for e in config.overlays]==['damage','combo_skill','uid_mask']
    assert config.start_input_recording_on_launch


def test_update_request_does_not_block_gui_and_failure_is_silent_until_manual(main_window, app, monkeypatch):
    window = main_window
    entered, finish = threading.Event(), threading.Event()
    def request(*args):
        entered.set()
        assert finish.wait(5)
        raise OSError('synthetic network failure')
    monkeypatch.setattr(updates, 'check_update', request)
    window._check_updates(False)
    assert entered.wait(2)
    assert not window.settings_page.check_update_btn.isEnabled()
    events = []
    QTimer.singleShot(0, lambda: events.append(True))
    wait_for(lambda: bool(events), app)
    finish.set()
    wait_for(lambda: window.settings_page.check_update_btn.isEnabled(), app)
    assert window.settings_page.update_status.text() == '未检测到新版'
    assert window._update_bar is None
    window._check_updates(True)
    wait_for(lambda: window.settings_page.check_update_btn.isEnabled(), app)
    assert 'synthetic network failure' in window.settings_page.update_status.text()


def test_update_notice_download_and_ignore_version(main_window, monkeypatch):
    window = main_window
    result = releases.release_update(release(), '0.1.0')
    window._complete_update_check(result, None, False)
    assert '0.2.0' in window.settings_page.update_status.text()
    assert '2026-10-25' in window.settings_page.update_status.text()
    assert window._update_bar is not None
    opened = []
    monkeypatch.setattr(updates.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()))
    window.settings_page.download_update_btn.click()
    assert opened == [result['url']]
    window.settings_page.ignore_update_btn.click()
    assert load_app_config(window.config_path).ignored_update_version == '0.2.0'
    assert window.settings_page.update_status.text() == '未检测到新版'
    assert window._update_bar is None
