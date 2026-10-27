"""Background version checks and optional, nonblocking update notice."""
from __future__ import annotations

from datetime import datetime
import threading
from PySide6.QtCore import QObject, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from endfield_pcap._version import __version__
from endfield_pcap.settings import save_app_config
from endfield_pcap.runtime.releases import check_update
from qfluentwidgets import InfoBar, InfoBarPosition, PushButton


class UpdateCheck(QObject):
    finished = Signal(object, object, bool)

    def start(self, ignored, manual):
        def run():
            result, error = None, None
            try:
                result = check_update(__version__, ignored)
            except Exception as exc:
                error = str(exc).splitlines()[0][:160] or '网络请求失败'
            try:
                self.finished.emit(result, error, manual)
            except RuntimeError:  # Window closed while the request was pending.
                pass
        threading.Thread(target=run, name='release-check', daemon=True).start()


class UpdateActions:
    def _init_update_check(self):
        self._update_release = None
        self._update_bar = None
        self._update_checker = UpdateCheck(self)
        self._update_checker.finished.connect(self._complete_update_check)
        page = self.settings_page
        page.check_update_btn.clicked.connect(lambda: self._check_updates(True))
        page.download_update_btn.clicked.connect(self._open_update_release)
        page.ignore_update_btn.clicked.connect(self._ignore_update)
        page.auto_update_switch.checkedChanged.connect(self._set_auto_update_check)
        self._schedule_update_check()

    def _schedule_update_check(self):
        if self.app_config.check_updates_on_start:
            QTimer.singleShot(1200, self, lambda:
                self._check_updates(False) if self.app_config.check_updates_on_start else None)

    def _check_updates(self, manual=False):
        if self._closing or not self.settings_page.check_update_btn.isEnabled():
            return
        self.settings_page.check_update_btn.setEnabled(False)
        if manual:
            self.settings_page.update_status.setText('正在检查更新…')
        self._update_checker.start(self.app_config.ignored_update_version, manual)

    def _complete_update_check(self, release, error, manual):
        if self._closing:
            return
        if release and release['version'] == self.app_config.ignored_update_version.lstrip('v'):
            release = None
        page = self.settings_page
        page.check_update_btn.setEnabled(True)
        if error:
            if manual:
                page.update_status.setText(f'检查失败：{error}')
            return
        self._update_release = release
        for button in (page.download_update_btn, page.ignore_update_btn):
            button.setVisible(bool(release))
        if release:
            date = datetime.fromisoformat(release['published_at']).astimezone().strftime('%Y-%m-%d')
            page.update_status.setText(f"发现新版 {release['version']} · 发布日期 {date}")
            if self._update_bar is not None:
                self._update_bar.close()
            self._update_bar = InfoBar.info(title='发现新版', content=f"{release['version']} · {date}",
                duration=-1, position=InfoBarPosition.TOP, parent=self)
            bar = self._update_bar
            bar.closedSignal.connect(lambda: self._clear_update_bar(bar))
            for label, action in (('前往下载', self._open_update_release), ('忽略此版本', self._ignore_update)):
                button = PushButton(label, self._update_bar)
                button.clicked.connect(action)
                self._update_bar.addWidget(button)
        else:
            page.update_status.setText('未检测到新版')
            if self._update_bar is not None:
                self._update_bar.close()
                self._update_bar = None

    def _open_update_release(self):
        if self._update_release:
            QDesktopServices.openUrl(QUrl(self._update_release['url']))

    def _clear_update_bar(self, bar):
        if self._update_bar is bar:
            self._update_bar = None

    def _ignore_update(self):
        if self._update_release:
            self.app_config.ignored_update_version = self._update_release['version']
            save_app_config(self.app_config, self.config_path)
            self._complete_update_check(None, None, False)

    def _set_auto_update_check(self, enabled):
        self.app_config.check_updates_on_start = bool(enabled)
        save_app_config(self.app_config, self.config_path)
