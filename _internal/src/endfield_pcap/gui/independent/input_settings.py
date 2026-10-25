from __future__ import annotations
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QTableWidgetItem,QHeaderView
from qfluentwidgets import CaptionLabel,PushButton,PrimaryPushButton,TableWidget,ComboBox,LineEdit,CheckBox
from endfield_pcap.gui.shared.spinboxes import ReadableSpinBox
from endfield_pcap.inputlog.interpret import normalize_settings,default_bindings

ACTIONS={'skill':'战技','ultimate':'终结技','combo':'连携','switch':'切换角色','other':'其他'}


class InputSettingsDialog(QDialog):
    def __init__(self,settings,parent=None):
        super().__init__(parent)
        self.setWindowTitle('输入记录与解释设置')
        self.resize(850,640)
        layout=QVBoxLayout(self)
        tip=CaptionLabel('仅记录配置游戏进程的前台输入；原始输入不按绑定过滤。解释结果表示意图，不代表技能成功释放。\nK:49–52 = 数字1–4；K:ALT / CTRL / SHIFT；K:69 = E；P:LB / RB / WEST / NORTH / EAST / SOUTH。组合用 + 分隔。',self)
        tip.setWordWrap(True)
        layout.addWidget(tip)
        row=QHBoxLayout()
        row.addWidget(CaptionLabel('长按阈值（参考值，非官方阈值）',self))
        self.hold=ReadableSpinBox(self)
        self.hold.setRange(1,10000)
        self.hold.setSuffix(' ms')
        row.addWidget(self.hold)
        row.addStretch()
        layout.addLayout(row)
        self.table=TableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['动作','角色槽位','原始组合','判定方式'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table,1)
        filters=QHBoxLayout()
        self.other=CheckBox('显示其他输入轨道',self)
        self.motion=CheckBox('显示鼠标移动',self)
        self.axes=CheckBox('显示手柄模拟量',self)
        for w in (self.other,self.motion,self.axes): filters.addWidget(w)
        filters.addStretch()
        layout.addLayout(filters)
        buttons=QHBoxLayout()
        for name,callback in (('增加绑定',self.add),('删除选中',self.remove),('恢复默认',lambda:self.load({}))):
            button=PushButton(name,self);button.clicked.connect(callback);buttons.addWidget(button)
        buttons.addStretch()
        cancel=PushButton('取消',self);cancel.clicked.connect(self.reject)
        save=PrimaryPushButton('保存',self);save.clicked.connect(self.accept)
        buttons.addWidget(cancel);buttons.addWidget(save)
        layout.addLayout(buttons)
        self.load(settings)

    def load(self,settings):
        settings=normalize_settings(settings)
        self.hold.setValue(settings['hold_ms'])
        self.table.setRowCount(0)
        for binding in settings['bindings']: self.add(binding)
        self.other.setChecked(settings['show_other'])
        self.motion.setChecked(settings['show_motion'])
        self.axes.setChecked(settings['show_axes'])

    def add(self,binding=None):
        binding=binding if isinstance(binding,dict) else dict(action='skill',slot=0,keys=['K:49'],gesture='tap_hold')
        row=self.table.rowCount();self.table.insertRow(row)
        action,slot,gesture=ComboBox(self),ComboBox(self),ComboBox(self)
        for key,name in ACTIONS.items(): action.addItem(name,userData=key)
        action.setCurrentIndex(list(ACTIONS).index(binding['action']))
        slot.addItem('全局',userData=None)
        for i in range(4): slot.addItem(str(i+1),userData=i)
        slot.setCurrentIndex(binding['slot']+1 if binding['slot'] is not None else 0)
        gesture.addItem('按下 / 组合成立',userData='press');gesture.addItem('短按战技 / 长按终结技',userData='tap_hold')
        gesture.setCurrentIndex(1 if binding['gesture']=='tap_hold' else 0)
        keys=LineEdit(self);keys.setText(' + '.join(binding['keys']))
        for i,w in enumerate((action,slot,keys,gesture)): self.table.setCellWidget(row,i,w)

    def remove(self):
        for row in sorted({i.row() for i in self.table.selectedIndexes()},reverse=True): self.table.removeRow(row)

    def value(self):
        rows=[]
        for row in range(self.table.rowCount()):
            action,slot,keys,gesture=(self.table.cellWidget(row,col) for col in range(4))
            rows.append(dict(action=action.currentData(),slot=slot.currentData(),
                             keys=[k.strip().upper() for k in keys.text().split('+') if k.strip()],gesture=gesture.currentData()))
        return normalize_settings(dict(hold_ms=self.hold.value(),bindings=rows,show_other=self.other.isChecked(),
                                       show_motion=self.motion.isChecked(),show_axes=self.axes.isChecked()))
