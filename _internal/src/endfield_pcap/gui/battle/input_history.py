"""One history selection's optional input evidence, loaded off the GUI thread."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import queue
import threading
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget,QHBoxLayout,QVBoxLayout,QDialog,QFormLayout,QFileDialog
from qfluentwidgets import CaptionLabel,PushButton,PrimaryPushButton,ComboBox,LineEdit,CheckBox
from endfield_pcap.gui.shared.spinboxes import ReadableDoubleSpinBox
from endfield_pcap.inputlog.history import discover,load_evidence,battle_start_wall_ms
from endfield_pcap.inputlog.interpret import normalize_settings
from endfield_pcap.inputlog.bindings import read_binding,write_binding
from endfield_pcap.history.index import record_key


class InputHistoryBar(QWidget):
    def __init__(self,dialog):
        super().__init__(dialog)
        self.dialog=dialog
        self.record=None
        self.paths=[]
        self.offset=0.
        self.start_override=None
        self.manual_slots={}
        self.manual=False
        self.generation=0
        self.results=queue.SimpleQueue()
        self.evidence=dict(actions=[],raw=[],warnings=[])
        parent=dialog.parentWidget()
        self.settings=normalize_settings(getattr(getattr(parent,'app_config',None),'input_settings',{}))
        layout=QHBoxLayout(self);layout.setContentsMargins(16,0,16,0)
        self.visible=CheckBox('显示输入',self);self.visible.setChecked(False)
        self.status=CaptionLabel('未绑定 input log',self);self.status.setWordWrap(True)
        self.attach=PushButton('绑定 input log',self);self.attach.clicked.connect(self.choose)
        self.detach=PushButton('解除绑定',self);self.detach.clicked.connect(self.unbind)
        self.align=PushButton('对齐 / 槽位',self);self.align.clicked.connect(self.alignment)
        self.options=PushButton('输入解释设置',self);self.options.clicked.connect(self.configure)
        layout.addWidget(self.visible);layout.addWidget(self.status,1)
        for button in (self.attach,self.detach,self.align,self.options): layout.addWidget(button)
        self.visible.toggled.connect(self.visibility_changed)
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.drain)

    def set_record(self,record):
        self.record=record
        parent=self.dialog.parentWidget()
        bindings=getattr(getattr(parent,'app_config',None),'input_log_bindings',{})
        saved=read_binding(bindings.get(record_key(record)),record.file_path)
        if record_key(record) in bindings:
            self.paths=[saved['path']] if saved['path'] else []
        else:
            self.paths=discover(record.file_path)[:1]
        self.offset=saved['offset_ms']
        self.start_override=saved['start_override']
        self.manual_slots=saved['manual_slots']
        self.manual=saved['manual']
        self.visible.blockSignals(True)
        self.visible.setChecked(saved['visible'])
        self.visible.blockSignals(False)
        self.reload()

    def choose(self):
        path,_=QFileDialog.getOpenFileName(self,'绑定 input log（仅本地读取）',
                    str(self.record.file_path.parent) if self.record else '', '输入日志 (*.input.jsonl *.jsonl)')
        if path:
            self.paths=[Path(path)]
            self.manual=True
            self.offset=0.
            self.start_override=None
            self.manual_slots={}
            self.save_binding()
            self.reload()

    def unbind(self):
        self.paths=[]
        self.manual=False
        self.save_binding()
        self.reload()

    def save_binding(self):
        parent=self.dialog.parentWidget()
        if self.record and hasattr(parent,'app_config'):
            from endfield_pcap.gui.config import save_app_config
            parent.app_config.input_log_bindings[record_key(self.record)]=write_binding(
                self.record.file_path,self.paths[0] if self.paths else None,
                visible=self.visible.isChecked(),offset_ms=self.offset,start_override=self.start_override,
                manual_slots=self.manual_slots,manual=self.manual)
            save_app_config(parent.app_config,parent.config_path)

    def visibility_changed(self,*_):
        self.save_binding()
        self.publish()

    def configure(self):
        from endfield_pcap.gui.independent.input_settings import InputSettingsDialog
        dialog=InputSettingsDialog(self.settings,self)
        if dialog.exec():
            self.settings=dialog.value()
            parent=self.dialog.parentWidget()
            if hasattr(parent,'app_config'):
                from endfield_pcap.gui.config import save_app_config
                parent.app_config.input_settings=self.settings
                save_app_config(parent.app_config,parent.config_path)
            self.reload()

    def alignment(self):
        dialog=QDialog(self);dialog.setWindowTitle('输入日志对齐与手动槽位')
        form=QFormLayout(dialog)
        note=CaptionLabel('只改变输入证据的显示；不补偿抓包延迟、不吸附技能点、不更改战斗结果。',dialog)
        note.setWordWrap(True);form.addRow(note)
        date=LineEdit(dialog)
        start=self.start_override
        try: original=datetime.fromtimestamp(battle_start_wall_ms(self.dialog.snapshot.get('battle') or {})/1000).isoformat(timespec='milliseconds')
        except ValueError: original=''
        date.setText(datetime.fromtimestamp(start/1000).isoformat(timespec='milliseconds') if start is not None else original)
        form.addRow('战斗起点（本地日期时间）',date)
        offset=ReadableDoubleSpinBox(dialog);offset.setRange(-86400000,86400000);offset.setDecimals(3);offset.setSuffix(' ms');offset.setValue(self.offset)
        form.addRow('输入对齐偏移',offset)
        combos=[]
        for i in range(4):
            combo=ComboBox(dialog);combo.addItem('使用 trace LOADOUT；无证据则显示槽位',userData=None)
            for p in self.dialog.snapshot.get('participants',[]):
                combo.addItem(str(p.get('character_name') or p['character_key']),userData=p['character_key'])
            for n in range(combo.count()):
                if combo.itemData(n)==self.manual_slots.get(i): combo.setCurrentIndex(n)
            form.addRow(f'角色槽位 {i+1}',combo);combos.append(combo)
        save=PrimaryPushButton('应用',dialog);save.clicked.connect(dialog.accept);form.addRow(save)
        if dialog.exec():
            try:
                chosen=date.text().strip()
                self.start_override=datetime.fromisoformat(chosen).timestamp()*1000 if chosen and chosen!=original else None
                self.offset=offset.value()
                self.manual_slots={i:c.currentData() for i,c in enumerate(combos) if c.currentData()}
                self.manual=True
                self.save_binding()
                self.reload()
            except ValueError:
                self.status.setText('日期格式无效，例如 2026-10-25T17:30:00.000')

    def reload(self):
        self.generation+=1
        self.evidence=dict(actions=[],raw=[],warnings=[])
        self.publish()
        if not self.record or not self.paths:
            self.timer.stop()
            self.status.setText('未绑定 input log')
            return
        self.status.setText('正在后台索引输入证据…')
        self.timer.start()
        generation=self.generation
        args=(list(self.paths),self.record.file_path,deepcopy(self.dialog.snapshot.get('battle') or {}),deepcopy(self.settings))
        kwargs=dict(offset_ms=self.offset,manual_slots=dict(self.manual_slots),start_override=self.start_override,verify=not self.manual)
        results=self.results
        def load():
            try: result=load_evidence(*args,**kwargs)
            except Exception as exc: result=exc
            results.put((generation,result))
        threading.Thread(target=load,name='input-history',daemon=True).start()

    def drain(self):
        while not self.results.empty():
            generation,value=self.results.get()
            if generation!=self.generation: continue
            self.timer.stop()
            if isinstance(value,Exception):
                self.status.setText(f'输入日志不可用：{value}')
                continue
            self.evidence=value
            notes=value['warnings']
            count=sum(value.get('input_counts',{}).values())
            self.status.setText(f'已绑定 {self.paths[0].name} · 本场 {count} 条输入记录 / {len(value["actions"])} 条输入意图'+(' · 手动对齐' if value['manual_alignment'] else '')
                                +(' · 战斗时间范围内未录到输入，请核对录制与对齐' if not count else '')
                                +(' · '+notes[0] if notes else ''))
            self.status.setToolTip('\n'.join(value['paths']+
                [f'本场输入分类：{value.get("input_counts",{})}',f'整个输入文件分类：{value.get("recording_counts",{})}']+notes))
            self.publish()

    def publish(self,*_):
        evidence=self.evidence if self.visible.isChecked() else dict(actions=[],raw=[],warnings=[])
        self.dialog.timeline.set_input_evidence(evidence)
        if self.dialog.web_analysis is not None:
            self.dialog.web_analysis.set_input_evidence(evidence)
