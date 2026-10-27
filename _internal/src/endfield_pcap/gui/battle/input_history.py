"""Input evidence controls; requests and display state are supplied by a presenter."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QTimer, Signal, QSignalBlocker
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QDialog,QFormLayout,QFileDialog,QMenu
from qfluentwidgets import CaptionLabel,PushButton,PrimaryPushButton,ComboBox,LineEdit,CheckBox
from endfield_pcap.gui.shared.spinboxes import ReadableDoubleSpinBox
from endfield_pcap.inputlog.history import battle_start_wall_ms
from endfield_pcap.application.input_evidence import InputEvidenceState


class InputHistoryBar(QWidget):
    bindingChosen = Signal(object)
    bindingRemoved = Signal()
    visibilityRequested = Signal(bool)
    settingsRequested = Signal(object)
    alignmentRequested = Signal(object)

    def __init__(self,dialog,*,compact=False):
        super().__init__(dialog)
        self.dialog=dialog
        self.state = InputEvidenceState()
        layout=(QVBoxLayout if compact else QHBoxLayout)(self)
        layout.setContentsMargins(12,10,12,10) if compact else layout.setContentsMargins(16,0,16,0)
        self.visible=CheckBox('显示输入',self);self.visible.setChecked(False)
        self.status=CaptionLabel('未绑定 input log',self);self.status.setWordWrap(True)
        self.attach=PushButton('绑定 input log',self);self.attach.clicked.connect(lambda:self.open_dialog(self.choose))
        self.detach=PushButton('解除绑定',self);self.detach.clicked.connect(self.unbind)
        self.align=PushButton('对齐 / 槽位',self);self.align.clicked.connect(lambda:self.open_dialog(self.alignment))
        self.options=PushButton('输入解释设置',self);self.options.clicked.connect(lambda:self.open_dialog(self.configure))
        if not compact:
            layout.addWidget(self.visible)
        layout.addWidget(self.status,1)
        for button in (self.attach,self.detach,self.align,self.options): layout.addWidget(button)
        self.visible.toggled.connect(self.visibilityRequested)
    @property
    def paths(self):
        return list(self.state.paths)

    @property
    def evidence(self):
        return self.state.evidence

    def set_state(self, state, text, tooltip):
        self.state = state
        with QSignalBlocker(self.visible):
            self.visible.setChecked(state.visible)
        self.status.setText(text)
        self.status.setToolTip(tooltip)

    def open_dialog(self,callback):
        # Release the popup's mouse/focus grab before entering a modal dialog.
        # The persistent battle window owns dialogs, never the menu widget.
        popup=self.window()
        if isinstance(popup,QMenu):
            popup.close()
            QTimer.singleShot(0,self.dialog,callback)
        else:
            callback()

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self.dialog,'绑定 input log（仅本地读取）',
                    str(self.state.trace_path.parent) if self.state.trace_path else '', '输入日志 (*.input.jsonl *.jsonl)')
        if path:
            self.bindingChosen.emit(Path(path))

    def unbind(self):
        self.bindingRemoved.emit()

    def configure(self):
        from endfield_pcap.gui.independent.input_settings import InputSettingsDialog
        dialog=InputSettingsDialog(self.state.settings,self.dialog)
        if dialog.exec():
            self.settingsRequested.emit(dialog.value())

    def alignment(self):
        dialog=QDialog(self.dialog);dialog.setWindowTitle('输入日志对齐与手动槽位')
        form=QFormLayout(dialog)
        note=CaptionLabel('只改变输入证据的显示；不补偿抓包延迟、不吸附技能点、不更改战斗结果。',dialog)
        note.setWordWrap(True);form.addRow(note)
        date=LineEdit(dialog)
        start=self.state.start_override
        try: original=datetime.fromtimestamp(battle_start_wall_ms(self.dialog.snapshot.get('battle') or {})/1000).isoformat(timespec='milliseconds')
        except ValueError: original=''
        date.setText(datetime.fromtimestamp(start/1000).isoformat(timespec='milliseconds') if start is not None else original)
        form.addRow('战斗起点（本地日期时间）',date)
        offset=ReadableDoubleSpinBox(dialog);offset.setRange(-86400000,86400000);offset.setDecimals(3);offset.setSuffix(' ms');offset.setValue(self.state.offset_ms)
        form.addRow('输入对齐偏移',offset)
        combos=[]
        for i in range(4):
            combo=ComboBox(dialog);combo.addItem('使用 trace LOADOUT；无证据则显示槽位',userData=None)
            for p in self.dialog.snapshot.get('participants',[]):
                combo.addItem(str(p.get('character_name') or p['character_key']),userData=p['character_key'])
            for n in range(combo.count()):
                if combo.itemData(n)==self.state.manual_slots.get(i): combo.setCurrentIndex(n)
            form.addRow(f'角色槽位 {i+1}',combo);combos.append(combo)
        save=PrimaryPushButton('应用',dialog);save.clicked.connect(dialog.accept);form.addRow(save)
        if dialog.exec():
            try:
                chosen=date.text().strip()
                start_override=datetime.fromisoformat(chosen).timestamp()*1000 if chosen and chosen!=original else None
                self.alignmentRequested.emit(dict(offset_ms=offset.value(), start_override=start_override,
                    manual_slots={i:c.currentData() for i,c in enumerate(combos) if c.currentData()}))
            except ValueError:
                self.status.setText('日期格式无效，例如 2026-10-25T17:30:00.000')
