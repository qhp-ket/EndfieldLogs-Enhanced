"""Fluent Overlay settings widgets; template manifests supply individual options."""
from __future__ import annotations
import json
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QGridLayout, QHBoxLayout, QSplitter, QAbstractItemView
from qfluentwidgets import (
    CaptionLabel,
    CheckBox,
    ComboBox,
    HeaderCardWidget,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    Slider,
)
from endfield_pcap.gui.shared.widgets import (
    InterfacePage,
    OverlayNumberEdit,
    FluentSwitchButton as SwitchButton,
)
from endfield_pcap.models import OverlayEntry, OverlaySourceType
from endfield_pcap.overlays.config import _window_defaults
from endfield_pcap.overlays.templates import template_for, template_values
from endfield_pcap.gui.pages.overlays.status import OverlayStatusCard


def _overlay_source_type_label(source_type: OverlaySourceType) -> str:
    if source_type == OverlaySourceType.BUILTIN:
        return "内置悬浮窗"
    if source_type == OverlaySourceType.FILE:
        return "原生皮肤"
    return source_type.value


class OverlayPage(InterfacePage):
    setting_changed = Signal(str, object)
    order_changed = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("overlayInterface", "悬浮窗", "管理内置浮窗与 JSON 原生皮肤。", parent)

        actions = QWidget(self)
        self.add_actions = actions
        actions_layout = QGridLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        self.add_file_btn = PrimaryPushButton("导入原生皮肤", actions)
        self.remove_btn = PushButton("删除选中", actions)
        for index, button in enumerate((self.add_file_btn, self.remove_btn)):
            actions_layout.addWidget(button, 0, index)
        actions_layout.setColumnStretch(3, 1)
        self.content_layout.addWidget(actions,alignment=Qt.AlignmentFlag.AlignTop)

        self.status_card = OverlayStatusCard(self)
        self.enable_all_btn = self.status_card.enable_all_btn
        self.disable_all_btn = self.status_card.disable_all_btn
        self.content_layout.addWidget(self.status_card)
        self.vision_settings_btn = PushButton('连携识别设置（图像识别，无需 Npcap）',self)
        self.content_layout.addWidget(self.vision_settings_btn)

        card = HeaderCardWidget("悬浮窗配置", self)
        self.reset_layout_btn = PushButton("重置布局", card)
        self.reset_layout_btn.setToolTip("恢复当前浮窗的模板默认尺寸、100% 字体和默认位置")
        self.content_layout.addWidget(card,1)
        self.content_layout.addStretch()
        splitter = QSplitter(card)
        self.splitter = splitter
        card.viewLayout.addWidget(splitter,1)

        self.overlay_list = ListWidget(splitter)
        self.overlay_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.overlay_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.overlay_list.setDragEnabled(True)
        self.overlay_list.setDropIndicatorShown(True)
        self.overlay_list.setToolTip('拖动条目调整顺序，自动保存')
        self.overlay_list.model().rowsMoved.connect(self._emit_order)
        self.overlay_list.setMinimumWidth(120)
        splitter.addWidget(self.overlay_list)

        details = QWidget(splitter)
        splitter.addWidget(details)
        splitter.setSizes([100,400])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        form = QFormLayout(details)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.name_edit = LineEdit(details)
        self.source_type_label = CaptionLabel("-", details)
        self.source_value_edit = LineEdit(details)
        self.template_label = CaptionLabel("-", details)
        self.template_label.setWordWrap(True)
        self.subscription_label = CaptionLabel("-", details)
        self.subscription_label.setWordWrap(True)
        self.details_form = form
        self._template_row_count = 0
        self.setting_widgets = {}
        self._template_signature = None
        self.enabled_switch = SwitchButton(details)
        self.enabled_switch.setOnText("开")
        self.enabled_switch.setOffText("关")
        self.enabled_switch.setToolTip("控制此浮窗订阅的分析；启用且显示浮窗开启时显示。共享分析在仍有其他消费者时继续运行。")
        self.visible_switch = SwitchButton(details)
        self.visible_switch.setOnText("开")
        self.visible_switch.setOffText("关")
        self.visible_switch.setToolTip("控制桌面显示；关闭后保持绘制，OBS 的 Windows 10 窗口采集可继续更新。右上角 × 会关闭此项。")
        self.locked_switch = SwitchButton(details)
        self.locked_switch.setOnText("开")
        self.locked_switch.setOffText("关")
        self.click_switch = SwitchButton(details)
        self.click_switch.setOnText("开")
        self.click_switch.setOffText("关")
        def paired_controls(label, first, next_label, second):
            row = QWidget(details)
            layout = QGridLayout(row)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setHorizontalSpacing(12)
            # Use the form's label/field columns so the first switch starts at
            # the same x as the name input and all other fields below it.
            first_label = CaptionLabel(label, details)
            first_label.setObjectName('firstControlLabel')
            second_group = QWidget(row)
            second_layout = QHBoxLayout(second_group)
            second_layout.setContentsMargins(0, 0, 0, 0)
            second_layout.setSpacing(12)
            second_label = CaptionLabel(next_label, second_group)
            second_label.setObjectName('secondControlLabel')
            second_layout.addWidget(second_label)
            second_layout.addWidget(second)
            second_layout.addStretch()
            layout.addWidget(first, 0, 0, Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(second_group, 0, 1)
            layout.setColumnMinimumWidth(0, first.sizeHint().width() + 112)
            layout.setColumnStretch(0, 1)
            layout.setColumnStretch(1, 1)
            return first_label, row
        state_row = paired_controls("启用", self.enabled_switch, "显示浮窗", self.visible_switch)
        mouse_row = paired_controls("锁定位置", self.locked_switch, "鼠标穿透", self.click_switch)
        self.opacity_slider = Slider(Qt.Orientation.Horizontal, details)
        self.opacity_slider.setRange(10, 100)
        self.opacity_value = CaptionLabel("100%", details)
        opacity_row = QWidget(details)
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.addWidget(self.opacity_slider, 1)
        opacity_layout.addWidget(self.opacity_value)
        self.font_size_slider = Slider(Qt.Orientation.Horizontal, details)
        self.font_size_slider.setRange(50, 300)
        self.font_size_slider.setValue(100)
        self.font_size_slider.setToolTip("窗口尺寸自动缩放文字和头像；此比例单独调整文字，不改变头像比例。100% 为自动适配大小")
        self.font_size_value = CaptionLabel("100%", details)
        self.font_size_value.setMinimumWidth(50)
        self.font_size_slider.valueChanged.connect(lambda value: self.font_size_value.setText(f"{value}%"))
        font_row = QWidget(details)
        font_layout = QHBoxLayout(font_row)
        font_layout.setContentsMargins(0, 0, 0, 0)
        font_layout.addWidget(self.font_size_slider, 1)
        font_layout.addWidget(self.font_size_value)
        self.width_edit = OverlayNumberEdit(details)
        self.height_edit = OverlayNumberEdit(details)
        dimensions_row = QWidget(details)
        dimensions_layout = QHBoxLayout(dimensions_row)
        dimensions_layout.setContentsMargins(0, 0, 0, 0)
        for label, spin in (("宽", self.width_edit), ("高", self.height_edit)):
            spin.setRange(1, 16384)
            spin.setFixedWidth(100)
            dimensions_layout.addWidget(CaptionLabel(label, dimensions_row))
            dimensions_layout.addWidget(spin)
        dimensions_layout.addStretch()
        self.geometry_label = CaptionLabel("-", details)
        position_row = QWidget(details)
        position_layout = QHBoxLayout(position_row)
        position_layout.setContentsMargins(0, 0, 0, 0)
        position_layout.addWidget(self.geometry_label, 1)
        position_layout.addWidget(self.reset_layout_btn)
        form.addRow(*state_row)
        form.addRow("名称", self.name_edit)
        self._template_start_row = form.rowCount()
        form.addRow("窗口尺寸 (px)", dimensions_row)
        form.addRow("字体大小", font_row)
        form.addRow("位置", position_row)
        form.addRow("透明度", opacity_row)
        form.addRow(*mouse_row)
        form.addRow("来源类型", self.source_type_label)
        form.addRow("渲染入口", self.source_value_edit)
        form.addRow("模板", self.template_label)
        form.addRow("数据订阅", self.subscription_label)
        form.setSpacing(15)
        self._updating = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'splitter'):
            return
        # Keep names readable at the default GUI width. Wider windows retain
        # the resizable side-by-side list and form.
        orientation = Qt.Orientation.Horizontal if self.viewport().width() >= 780 else Qt.Orientation.Vertical
        if self.splitter.orientation() != orientation:
            self.splitter.setOrientation(orientation)
            narrow = orientation == Qt.Orientation.Vertical
            self.overlay_list.setMinimumHeight(110 if narrow else 0)
            self.overlay_list.setMaximumHeight(120 if narrow else 16777215)
            self.splitter.setSizes([110, 800] if narrow else [180, 600])

    def _emit_order(self, *_) -> None:
        self.order_changed.emit([str(self.overlay_list.item(i).data(Qt.ItemDataRole.UserRole))
                                 for i in range(self.overlay_list.count())])

    def selected_entry_id(self) -> str | None:
        item = self.overlay_list.currentItem()
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def set_entries(self, entries: list[OverlayEntry]) -> None:
        selected = self.selected_entry_id()
        self.overlay_list.clear()
        for entry in entries:
            item = self.overlay_list.addItem(entry.name)
            real_item = self.overlay_list.item(self.overlay_list.count() - 1)
            real_item.setData(Qt.ItemDataRole.UserRole, entry.id)
            if entry.id == selected:
                self.overlay_list.setCurrentItem(real_item)
        if self.overlay_list.currentItem() is None and self.overlay_list.count() > 0:
            self.overlay_list.setCurrentRow(0)

    def show_entry(self, entry: OverlayEntry | None) -> None:
        self._updating = True
        try:
            if entry is None:
                self.name_edit.clear()
                self.source_type_label.setText("-")
                self.source_value_edit.clear()
                self.enabled_switch.setChecked(False)
                self.visible_switch.setChecked(False)
                self.visible_switch.setEnabled(False)
                self.locked_switch.setChecked(False)
                self.click_switch.setChecked(False)
                self.opacity_slider.setValue(100)
                self.opacity_value.setText("100%")
                self.font_size_slider.setValue(100)
                self.geometry_label.setText("-")
                self.remove_btn.setEnabled(False)
                self.source_value_edit.setReadOnly(True)
                for widget in self.setting_widgets.values():
                    for child in (widget.values() if isinstance(widget, dict) else [widget]):
                        child.setEnabled(False)
                self.width_edit.setEnabled(False)
                self.height_edit.setEnabled(False)
                self.font_size_slider.setEnabled(False)
                self.reset_layout_btn.setEnabled(False)
                return
            self.name_edit.setText(entry.name)
            self.source_type_label.setText(_overlay_source_type_label(entry.source_type))
            self.source_value_edit.setText(entry.source_value)
            self.source_value_edit.setReadOnly(True)
            self._show_template(entry)
            self.width_edit.setEnabled(True)
            self.height_edit.setEnabled(True)
            self.font_size_slider.setEnabled(True)
            self.reset_layout_btn.setEnabled(True)
            self.enabled_switch.setChecked(entry.enabled)
            self.visible_switch.setEnabled(entry.enabled)
            self.visible_switch.setChecked(not entry.hidden)
            self.locked_switch.setChecked(entry.locked)
            self.click_switch.setChecked(entry.click_through)
            self.opacity_slider.setValue(int(round(entry.opacity * 100)))
            self.opacity_value.setText(f"{int(round(entry.opacity * 100))}%")
            self.font_size_slider.setValue(int(round(entry.font_scale * 100)))
            geometry = entry.geometry
            defaults = _window_defaults(entry)
            self.width_edit.setMinimum(defaults["min_width"])
            self.height_edit.setMinimum(defaults["min_height"])
            self.width_edit.setValue(geometry.width if geometry else defaults["default_width"])
            self.height_edit.setValue(geometry.height if geometry else defaults["default_height"])
            self.geometry_label.setText("默认位置" if geometry is None else f"x={geometry.x}, y={geometry.y}")
            self.remove_btn.setEnabled(entry.source_type != OverlaySourceType.BUILTIN)
        finally:
            self._updating = False

    def _show_template(self, entry: OverlayEntry) -> None:
        template = template_for(entry)
        self.template_label.setText(template.error or template.name)
        labels = {"analysis_summary": "????????? / ?????", "combo_snapshot": "?? CD???????? Npcap????????"}
        self.subscription_label.setText(" / ".join(labels[key] for key in template.subscriptions) or "????????????")
        if entry.source_type == OverlaySourceType.BUILTIN and entry.source_value == "uid_mask":
            self.subscription_label.setText("无需战斗数据（本地遮挡）")
        self.subscription_label.setToolTip(" / ".join(template.subscriptions))
        signature = (str(template.path), json.dumps(template.settings, sort_keys=True))
        if signature != self._template_signature:
            for _ in range(self._template_row_count):
                self.details_form.removeRow(self._template_start_row)
            self._template_row_count = len(template.settings)
            self.setting_widgets = {}
            for item in template.settings:
                key = item["key"]
                if item["type"] == "select":
                    widget = ComboBox(self.name_edit.parentWidget())
                    for option in item["options"]:
                        widget.addItem(option.get("label", option["value"]), userData=option["value"])
                    widget.currentIndexChanged.connect(lambda _, k=key: self._emit_setting(k))
                    self.setting_widgets[key] = widget
                elif item["type"] == "slider":
                    widget = QWidget(self.name_edit.parentWidget())
                    layout = QHBoxLayout(widget)
                    layout.setContentsMargins(0, 0, 0, 0)
                    slider = Slider(Qt.Orientation.Horizontal, widget)
                    slider.setRange(item["min"], item["max"])
                    caption = CaptionLabel(f"{slider.value()}%", widget)
                    caption.setMinimumWidth(50)
                    slider.valueChanged.connect(lambda value, label=caption: label.setText(f"{value}%"))
                    slider.valueChanged.connect(lambda _, k=key: self._emit_setting(k))
                    layout.addWidget(slider, 1)
                    layout.addWidget(caption)
                    self.setting_widgets[key] = slider
                else:
                    widget = QWidget(self.name_edit.parentWidget())
                    layout = QGridLayout(widget)
                    layout.setContentsMargins(0, 0, 0, 0)
                    checks = {}
                    for index, option in enumerate(item["options"]):
                        check = CheckBox(option.get("label", option["value"]), widget)
                        layout.addWidget(check, index // 2, index % 2)
                        check.stateChanged.connect(lambda _, k=key: self._emit_setting(k))
                        checks[option["value"]] = check
                    self.setting_widgets[key] = checks
                self.details_form.insertRow(self._template_start_row + len(self.setting_widgets) - 1, item.get("label", key), widget)
            self._template_signature = signature
        for key, value in template_values(entry, template).items():
            widget = self.setting_widgets[key]
            if isinstance(widget, dict):
                for option, check in widget.items():
                    check.setEnabled(True)
                    check.setChecked(option in value)
            elif isinstance(widget, Slider):
                widget.setEnabled(True)
                widget.setValue(value)
            else:
                widget.setEnabled(True)
                widget.setCurrentIndex(widget.findData(value))

    def _emit_setting(self, key: str) -> None:
        if self._updating:
            return
        widget = self.setting_widgets[key]
        if isinstance(widget, dict):
            value = [k for k, check in widget.items() if check.isChecked()]
        else:
            value = widget.value() if isinstance(widget, Slider) else widget.currentData()
        self.setting_changed.emit(key, value)
