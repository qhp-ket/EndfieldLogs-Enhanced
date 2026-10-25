"""Opt-in preview and normalized region calibration; no screenshots are persisted."""
from __future__ import annotations
from copy import deepcopy
from PySide6.QtCore import Qt,QRectF,Signal,QTimer
from PySide6.QtGui import QPainter,QColor,QPen
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QWidget
from qfluentwidgets import CaptionLabel,ComboBox,PushButton,PrimaryPushButton
from endfield_pcap.vision.layout import presets,normalize_config


class Preview(QWidget):
    selected=Signal(object)
    def __init__(self,parent=None):
        super().__init__(parent)
        self.image=None
        self.rectangles=[]
        self.drag=None
        self.setMinimumSize(560,315)
        self.setMouseTracking(True)

    def image_rect(self):
        if self.image is None or self.image.isNull(): return QRectF()
        size=self.image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())

    def paintEvent(self,event):
        painter=QPainter(self)
        painter.fillRect(self.rect(),QColor('#181b21'))
        area=self.image_rect()
        if area.isEmpty():
            painter.setPen(QColor('white'))
            painter.drawText(self.rect(),Qt.AlignmentFlag.AlignCenter,'等待游戏画面；预览仅在此窗口打开时生成')
            return
        painter.drawImage(area,self.image)
        painter.setPen(QPen(QColor('#54e6cb'),1.5))
        for row in self.rectangles:
            for x,y,w,h in row.values():
                painter.drawRect(QRectF(area.x()+x*area.width(),area.y()+y*area.height(),w*area.width(),h*area.height()))
        if self.drag:
            painter.setPen(QPen(QColor('#ffc25c'),2))
            painter.drawRect(QRectF(self.drag[0],self.drag[1]).normalized())

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton and self.image_rect().contains(event.position()):
            self.drag=[event.position(),event.position()]

    def mouseMoveEvent(self,event):
        if self.drag: self.drag[1]=event.position();self.update()

    def mouseReleaseEvent(self,event):
        if not self.drag: return
        area=self.image_rect()
        rect=QRectF(self.drag[0],event.position()).normalized().intersected(area)
        self.drag=None
        if rect.width()>=2 and rect.height()>=1:
            self.selected.emit([(rect.x()-area.x())/area.width(),(rect.y()-area.y())/area.height(),
                                rect.width()/area.width(),rect.height()/area.height()])
        self.update()


class VisionSettingsDialog(QDialog):
    def __init__(self,controller,settings,parent=None):
        super().__init__(parent)
        self.controller=controller
        self.settings=normalize_config(settings)
        self.regions=deepcopy(self.settings['regions'] or presets()['keyboard'])
        self.setWindowTitle('连携 CD 图像识别设置')
        self.resize(960,680)
        layout=QVBoxLayout(self)
        note=CaptionLabel('识别游戏窗口画面，无需 Npcap。CD 就绪不代表满足连携触发条件。自动识别不可靠时，按槽位分别框选冷却条、血条和阵亡图标区域。',self)
        note.setWordWrap(True);layout.addWidget(note)
        row=QHBoxLayout()
        self.target=ComboBox(self);self.target.addItem('自动选择（优先前台游戏窗口）',userData=0)
        try:
            from endfield_pcap.runtime.game_window import GameWindows
            for hwnd in GameWindows(controller.game_exe).windows(): self.target.addItem(f'游戏窗口 0x{hwnd:x}',userData=hwnd)
        except OSError: pass
        for i in range(self.target.count()):
            if self.target.itemData(i)==self.settings['target_hwnd']: self.target.setCurrentIndex(i)
        self.mode=ComboBox(self)
        modes={'auto':'自动布局','keyboard':'键鼠','gamepad':'手柄','gamepad_expanded':'手柄组合键按住','custom':'手动校准'}
        for key,name in modes.items(): self.mode.addItem(name,userData=key)
        self.mode.setCurrentIndex(list(modes).index(self.settings['layout']))
        row.addWidget(self.target,1);row.addWidget(self.mode)
        reset=PushButton('恢复自动定位',self);reset.clicked.connect(lambda:self.mode.setCurrentIndex(0));row.addWidget(reset)
        layout.addLayout(row)
        self.preview=Preview(self);layout.addWidget(self.preview,1)
        self.status=CaptionLabel('',self);self.status.setWordWrap(True);layout.addWidget(self.status)
        calibration=QHBoxLayout()
        self.slot=ComboBox(self)
        for i in range(4): self.slot.addItem(f'槽位 {i+1}',userData=i)
        self.region=ComboBox(self)
        for key,name in (('energy','冷却条'),('hp','血条'),('portrait','阵亡图标')): self.region.addItem(name,userData=key)
        calibration.addWidget(CaptionLabel('框选目标',self));calibration.addWidget(self.slot);calibration.addWidget(self.region)
        calibration.addStretch()
        close=PushButton('取消',self);close.clicked.connect(self.reject)
        save=PrimaryPushButton('保存',self);save.clicked.connect(self.accept)
        calibration.addWidget(close);calibration.addWidget(save);layout.addLayout(calibration)
        self.preview.selected.connect(self.select_region)
        self.mode.currentIndexChanged.connect(self.apply_preview)
        self.target.currentIndexChanged.connect(self.apply_preview)
        self.controller.previewReady.connect(self.update_image)
        self.controller.previewRequested.emit(True)
        self.timer=QTimer(self);self.timer.setInterval(300);self.timer.timeout.connect(self.refresh);self.timer.start()
        self.apply_preview()

    def select_region(self,rect):
        self.regions[self.slot.currentData()][self.region.currentData()]=rect
        self.mode.setCurrentIndex(4)
        self.apply_preview()

    def update_image(self,image):
        self.preview.image=image
        self.preview.update()

    def refresh(self):
        state=self.controller.state
        if self.mode.currentData()!='custom':
            self.preview.rectangles=state.get('regions',[])
            self.preview.update()
        self.status.setText(state['status']+' · '+str(state.get('layout') or '布局未确认')+'\n画面只用于识别，不保存或上传。')

    def apply_preview(self):
        self.controller.configure(self.value())
        self.preview.rectangles=self.regions if self.mode.currentData()=='custom' else presets().get(self.mode.currentData(),[])
        self.preview.update()

    def value(self):
        return normalize_config(dict(layout=self.mode.currentData(),regions=self.regions if self.mode.currentData()=='custom' else [],
                                     target_hwnd=self.target.currentData()))

    def done(self,result):
        self.timer.stop()
        self.controller.previewRequested.emit(False)
        self.controller.previewReady.disconnect(self.update_image)
        if not result: self.controller.configure(self.settings)
        super().done(result)
