"""Qt WGC worker: one latest QVideoFrame, bounded 20 Hz ROI processing."""
from __future__ import annotations
import os
import threading
import time
from PySide6.QtCore import QObject,Signal,Slot,QTimer,Qt
from endfield_pcap.vision.engine import VisionEngine


class CaptureWorker(QObject):
    result=Signal(object)
    preview=Signal(object)

    def __init__(self,config):
        super().__init__()
        self.config=config
        self.engine=VisionEngine(config)
        self.capture=self.session=self.sink=self.timer=None
        self.hwnd=None
        self.frame=None
        self.frame_id=0
        self.frame_lock=threading.Lock()
        self.received=0.
        self.processed=None
        self.preview_enabled=False
        self.last_preview=0.
        self.error=None

    @Slot()
    def start(self):
        # Explicit backend selection precedes loading Qt Multimedia.
        os.environ['QT_MEDIA_BACKEND']='ffmpeg'
        os.environ['QT_WINDOW_CAPTURE_BACKEND']='uwp'
        try:
            from PySide6.QtMultimedia import QWindowCapture,QMediaCaptureSession,QVideoSink
            self.capture=QWindowCapture(self)
            self.session=QMediaCaptureSession(self)
            self.sink=QVideoSink(self)
            self.session.setWindowCapture(self.capture)
            self.session.setVideoSink(self.sink)
            self.sink.videoFrameChanged.connect(self.receive,Qt.ConnectionType.DirectConnection)
            self.capture.errorOccurred.connect(self.failed)
        except Exception as exc:
            self.error=f'图像捕获不可用：{exc}'
        self.timer=QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def failed(self,error,message):
        self.error=f'图像捕获不可用：{message}'

    def receive(self,frame):
        from PySide6.QtMultimedia import QVideoFrame
        if not frame.isValid(): return
        with self.frame_lock:
            self.frame=QVideoFrame(frame)
            self.frame_id+=1
            self.received=time.perf_counter()

    @Slot(object)
    def target(self,value):
        if self.capture is None: return
        self.capture.setActive(False)
        self.hwnd=value[0] if value else None
        if self.timer:self.timer.setInterval(50 if value else 500)
        self.error=None
        self.engine=VisionEngine(self.config)
        with self.frame_lock:
            self.frame=None
            self.received=0
        if value:
            self.capture.setWindow(value[1])
            self.capture.setActive(True)

    @Slot(object)
    def configure(self,config):
        self.config=config
        self.engine=VisionEngine(config)

    @Slot(bool)
    def set_preview(self,value):
        self.preview_enabled=value

    @Slot()
    def tick(self):
        now=time.perf_counter()
        with self.frame_lock:
            frame,identity,received=self.frame,self.frame_id,self.received
        if self.error or not self.hwnd or frame is None or now-received>1:
            state=self.engine.invalid(now,self.error or ('等待游戏窗口' if not self.hwnd else '画面未更新'))
        elif self.processed==identity:
            return
        else:
            self.processed=identity
            try:
                state=self.analyze(frame,now,identity)
            except Exception as exc:
                state=self.engine.invalid(now,f'图像捕获不可用：{exc}')
        state['published_mono']=time.perf_counter()
        self.timer.setInterval(500 if not self.hwnd or self.error else 50 if state['frame_valid'] or self.preview_enabled else 100)
        state['target_hwnd']=self.hwnd
        state['capture_to_publish_ms']=(state['published_mono']-received)*1000 if received else None
        self.result.emit(state)

    def analyze(self,frame,now,identity):
        import numpy as np
        from PySide6.QtMultimedia import QVideoFrame,QVideoFrameFormat
        from endfield_pcap.runtime.game_window import GameWindows
        if frame.pixelFormat() not in {getattr(QVideoFrameFormat.PixelFormat,n) for n in
            ('Format_BGRA8888','Format_BGRX8888','Format_RGBA8888','Format_RGBX8888') if hasattr(QVideoFrameFormat.PixelFormat,n)}:
            raise RuntimeError(f'不支持的捕获像素格式：{frame.pixelFormat().name}')
        began=time.perf_counter()
        if not frame.map(QVideoFrame.MapMode.ReadOnly):
            raise RuntimeError('无法映射捕获帧')
        try:
            pixels=np.ndarray((frame.height(),frame.bytesPerLine(0)//4,4),dtype=np.uint8,
                              buffer=frame.bits(0))[:,:frame.width()]
            windows=GameWindows.__new__(GameWindows)
            import ctypes
            from ctypes import wintypes as w
            windows.user=ctypes.WinDLL('user32')
            windows.user.GetClientRect.argtypes=[w.HWND,ctypes.POINTER(w.RECT)]
            area=windows.client_in_frame(self.hwnd,frame.width(),frame.height())
            token=frame.startTime() if frame.startTime()>=0 else identity
            state=self.engine.analyze(pixels,area,now,token)
        finally:
            frame.unmap()
        state['processing_ms']=(time.perf_counter()-began)*1000
        if self.preview_enabled and now-self.last_preview>.25:
            image=frame.toImage()
            if state.get('game_area'):
                image=image.copy(*state['game_area'])
            self.preview.emit(image.scaled(960,540,Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
            self.last_preview=now
        return state

    @Slot()
    def stop(self):
        if self.timer: self.timer.stop()
        if self.capture: self.capture.setActive(False)
        if self.session:
            self.session.setVideoSink(None)
            self.session.setWindowCapture(None)
        with self.frame_lock: self.frame=None
        self.deleteLater()
        self.thread().quit()
