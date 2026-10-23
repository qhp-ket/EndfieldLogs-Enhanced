"""Offline WebEngine host for the optional website-style history analysis."""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                    QWebEngineSettings, QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import isDarkTheme

from .battle_web_data import WebBattleModel

ASSETS = Path(__file__).with_name('battle_analysis_assets').resolve()
LOGGER = logging.getLogger(__name__)


class _LocalAssetsOnly(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        url = info.requestUrl()
        if url.scheme() == 'qrc' and url.path() == '/qtwebchannel/qwebchannel.js':
            return
        if url.isLocalFile():
            try:
                Path(url.toLocalFile()).resolve().relative_to(ASSETS)
                return
            except ValueError:
                pass
        info.block(True)


class _AnalysisPage(QWebEnginePage):
    def __init__(self, profile, parent):
        super().__init__(profile, parent)
        self.console_errors = []

    def javaScriptConsoleMessage(self, level, message, line, source):
        if level == QWebEnginePage.JavaScriptConsoleMessageLevel.ErrorMessageLevel:
            self.console_errors.append(message)
            LOGGER.error('Analysis page %s:%s: %s', source, line, message)


class AnalysisBridge(QObject):
    environmentChanged = Signal(str, float)
    labelChanged = Signal(str)
    stateChanged = Signal(str)
    stateEdited = Signal(str)

    def __init__(self, model, parent):
        super().__init__(parent)
        self.model = model
        self.ready = False
        self.theme = 'dark' if isDarkTheme() else 'light'
        self.font_scale = 1.15
        self.state_json = '{}'

    @Slot(result=str)
    def payload(self):
        return self.model.json()

    @Slot(int, result=str)
    def blockDetails(self, index):
        return self.model.block_details(index)

    @Slot(result=str)
    def initialState(self):
        return self.state_json

    @Slot()
    def pageReady(self):
        self.ready = True
        self.environmentChanged.emit(self.theme, self.font_scale)

    @Slot(str)
    def saveState(self, state):
        import json
        try:
            if not isinstance(json.loads(state), dict):
                return
        except (ValueError, TypeError):
            return
        self.state_json = state
        self.stateEdited.emit(state)

    @Slot(str, int, float, str, result=str)
    def hover(self, kind, index, stamp, unit):
        return self.model.hover(kind, index, stamp, unit)


class WebBattleView(QWidget):
    def __init__(self, snapshot, label, parent=None):
        super().__init__(parent)
        self.bridge = AnalysisBridge(WebBattleModel(snapshot, label), self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web = QWebEngineView(self)
        layout.addWidget(self.web)
        # An off-the-record profile and an asset allowlist keep logs entirely local.
        self.profile = QWebEngineProfile(self)
        self.interceptor = _LocalAssetsOnly(self.profile)
        self.profile.setUrlRequestInterceptor(self.interceptor)
        self.page = _AnalysisPage(self.profile, self.web)
        self.web.setPage(self.page)
        self.channel = QWebChannel(self.page)
        self.channel.registerObject('analysis', self.bridge)
        self.page.setWebChannel(self.channel)
        settings = self.page.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
        self.set_environment()
        self.web.load(QUrl.fromLocalFile(str(ASSETS / 'index.html')))

    def set_environment(self, *args):
        self.bridge.theme = 'dark' if isDarkTheme() else 'light'
        self.page.setBackgroundColor(QColor('#0c1016' if isDarkTheme() else '#f1f4f8'))
        self.bridge.environmentChanged.emit(self.bridge.theme, self.bridge.font_scale)

    def set_gui_font_scale(self, scale):
        self.bridge.font_scale = scale
        self.set_environment()

    def set_record_label(self, label):
        self.bridge.model.label = label
        self.bridge.labelChanged.emit(label)

    def set_view_state(self, state):
        import json
        self.bridge.state_json = json.dumps(state)
        self.bridge.stateChanged.emit(self.bridge.state_json)
