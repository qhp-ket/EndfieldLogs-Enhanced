"""GUI-side lifecycle and real-time identity; independent of capture service readiness."""
from __future__ import annotations
import time
import uuid
import os
import logging
from PySide6.QtCore import QObject,QThread,QTimer,Signal
from PySide6.QtGui import QWindow
from endfield_pcap.vision.layout import normalize_config


class VisionController(QObject):
    targetRequested=Signal(object)
    configRequested=Signal(object)
    previewRequested=Signal(bool)
    stopRequested=Signal()
    previewReady=Signal(object)

    def __init__(self,game_exe,config=None,parent=None):
        super().__init__(parent)
        self.game_exe=game_exe
        self.config=normalize_config(config)
        self.thread=None
        self.worker=None
        self.hwnd=None
        self.foreign=None
        self.identity={}
        self.session=None
        self.state=dict(status='已停止',frame_valid=False,slots=[])
        self.sequence=0
        self.stream=uuid.uuid4().hex
        self.discovery=QTimer(self)
        self.discovery.setInterval(500)
        self.discovery.timeout.connect(self.discover)
        self._latest=None
        self._published=None
        self._windows=None
        self._diagnostic_at=0.
        self._enabled=False
        self._stopping=False
        self._stop_started=0.
        self._stop_warned=False
        self.stop_poll=QTimer(self)
        self.stop_poll.setInterval(50)
        self.stop_poll.timeout.connect(self._poll_stop)

    def set_enabled(self,enabled):
        self._enabled=bool(enabled)
        if enabled and self.thread is None and not self._stopping:
            try:
                from endfield_pcap.vision.capture import CaptureWorker
                self.stream=uuid.uuid4().hex
                self.sequence=0
                self._published=None
                self.thread=QThread(self)
                self.worker=CaptureWorker(self.config)
                self.worker.moveToThread(self.thread)
                self.thread.finished.connect(self.worker.deleteLater)
                self.thread.started.connect(self.worker.start)
                self.targetRequested.connect(self.worker.target)
                self.configRequested.connect(self.worker.configure)
                self.previewRequested.connect(self.worker.set_preview)
                self.stopRequested.connect(self.worker.stop)
                # Latest only; the GUI drain timer publishes at most one result.
                self.worker.result.connect(self.receive, __import__('PySide6.QtCore',fromlist=['Qt']).Qt.ConnectionType.DirectConnection)
                self.worker.preview.connect(self.previewReady)
                self.thread.start()
                self.state=dict(status='寻找游戏窗口',frame_valid=False,slots=[])
                self.discovery.start()
                self.discover()
            except Exception as exc:
                self.state=dict(status=f'图像捕获不可用：{exc}',frame_valid=False,slots=[])
        elif not enabled:
            self.stop()

    def receive(self,state):
        if not self._stopping:
            self._latest=state

    def discover(self):
        try:
            from endfield_pcap.runtime.game_window import GameWindows
            if self._windows is None or self._windows.executable!=os.path.normcase(os.path.abspath(str(self.game_exe))):
                self._windows=GameWindows(self.game_exe)
            windows=self._windows
            candidates=windows.windows()
            preferred=self.config['target_hwnd']
            target=preferred if preferred in candidates else (windows.foreground() or (candidates[0] if candidates else None))
            if target==self.hwnd: return
            self.hwnd=target
            self.identity={}
            self.foreign=QWindow.fromWinId(target) if target else None
            if self.foreign:
                from PySide6.QtMultimedia import QCapturableWindow
                self.targetRequested.emit((target,QCapturableWindow(self.foreign)))
            else:
                self.targetRequested.emit(None)
        except Exception as exc:
            self.state=dict(status=f'图像捕获不可用：{exc}',frame_valid=False,slots=[])

    def set_identity(self,members,session):
        self.session=session
        self.identity={m.squad_index:dict(character_key=m.templateid,display_name=m.display_name) for m in members}

    def configure(self,config):
        self.config=normalize_config(config)
        self.configRequested.emit(self.config)
        if self.thread: self.discover()

    def take_snapshot(self):
        if self._stopping:
            return None
        latest,self._latest=self._latest,None
        if latest is None:
            latest=self.state
            if latest.get('target_hwnd')!=self.hwnd:return None
        if latest.get('target_hwnd') != self.hwnd: return None
        self.state=latest
        now=time.monotonic()
        if now-self._diagnostic_at>=10:
            self._diagnostic_at=now
            logging.getLogger(__name__).info('连携视觉诊断 frame_valid=%s layout=%s slots=%s evidence=%s',
                latest.get('frame_valid'),latest.get('layout'),
                [(s['slot'],s['status'],s.get('progress'),s.get('held')) for s in latest['slots']],
                latest.get('diagnostics',{}))
        slots=[dict(row,**self.identity.get(row['slot'],{})) for row in latest['slots']]
        # Timings are diagnostics, not a reason to redraw an unchanged HUD.
        content={key:value for key,value in latest.items() if key not in
                 {'published_mono','processing_ms','capture_to_publish_ms','slots','diagnostics'}}
        content['slots']=[dict(row,progress=round(row['progress'],3) if row.get('progress') is not None else None,
                             estimated_remaining_ms=round(row['estimated_remaining_ms']/100)*100
                             if row.get('estimated_remaining_ms') is not None else None) for row in slots]
        if content==self._published:return None
        self._published=content
        self.sequence+=1
        return dict(type='combo_snapshot',schema_version=2,stream_id=self.stream,sequence=self.sequence,
                    snapshot={key:value for key,value in dict(latest,slots=slots).items() if key!='diagnostics'},source='vision')

    def stop(self):
        self._enabled=False
        self.discovery.stop()
        if self.thread and not self._stopping:
            self._stopping=True
            self._stop_started=time.monotonic()
            self._stop_warned=False
            self.stopRequested.emit()
            self.state=dict(status='正在停止图像捕获',frame_valid=False,slots=[])
            self.stop_poll.start()
        self._poll_stop()

    def is_running(self):
        return self.thread is not None and self.thread.isRunning()

    def _poll_stop(self):
        if self.thread is not None and self.thread.isRunning():
            if self._stopping and not self._stop_warned and time.monotonic()-self._stop_started>5:
                self._stop_warned=True
                logging.getLogger(__name__).error('图像捕获线程退出超时，继续等待原生资源释放')
                self.state=dict(status='图像捕获退出超时，请查看程序日志',frame_valid=False,slots=[])
            return
        self.stop_poll.stop()
        if self.thread is not None:
            self.thread.deleteLater()
            self.thread=self.worker=None
        self._stopping=False
        self.hwnd=self.foreign=None
        self._latest=None
        self._published=None
        self.identity={}
        self.state=dict(status='已停止',frame_valid=False,slots=[])
        if self._enabled:
            self.set_enabled(True)
