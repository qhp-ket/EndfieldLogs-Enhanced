from __future__ import annotations
import uuid
from dataclasses import replace
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox
from endfield_pcap.gui.config import save_app_config
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from endfield_pcap.overlays.templates import template_for, with_template_value
from endfield_pcap.gui.resources import ROOT


class OverlayActions:
    def _refresh_overlay_views(self) -> None:
        self.overlay_page.set_entries(self.app_config.overlays)
        self._sync_overlay_selection()
        self._update_service_status()

    def _selected_overlay(self) -> OverlayEntry | None:
        entry_id = self.overlay_page.selected_entry_id()
        if entry_id is None:
            return None
        for entry in self.app_config.overlays:
            if entry.id == entry_id:
                return entry
        return None

    def _sync_overlay_selection(self) -> None:
        entry = self._selected_overlay()
        self.overlay_page.show_entry(entry)

    def _replace_overlay_entry(self, updated: OverlayEntry) -> None:
        self.app_config.overlays = [updated if entry.id == updated.id else entry for entry in self.app_config.overlays]
        self.overlay_manager.apply_entry(updated)
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _handle_overlay_entry_changed(self, entry: OverlayEntry) -> None:
        self.app_config.overlays = [entry if item.id == entry.id else item for item in self.app_config.overlays]
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _add_url_overlay(self) -> None:
        url, ok = QInputDialog.getText(self, "新增 URL 悬浮窗", "请输入悬浮窗 URL：")
        if not ok or not url.strip():
            return
        entry = OverlayEntry(
            id=str(uuid.uuid4()),
            name="在线悬浮窗",
            source_type=OverlaySourceType.URL,
            source_value=url.strip(),
            enabled=True,
            locked=False,
            click_through=False,
            opacity=1.0,
            scale=1.0,
        )
        self.app_config.overlays.append(entry)
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.apply_entry(entry)
        self._refresh_overlay_views()

    def _add_file_overlay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择本地悬浮窗模板或 HTML", str(ROOT), "悬浮窗模板/HTML (*.json *.html *.htm)")
        if not path:
            return
        entry = OverlayEntry(
            id=str(uuid.uuid4()),
            name=Path(path).stem,
            source_type=OverlaySourceType.FILE,
            source_value=path,
            enabled=True,
            locked=False,
            click_through=False,
            opacity=1.0,
            scale=1.0,
        )
        template = template_for(entry)
        if template.error:
            QMessageBox.warning(self, "模板无效", template.error)
            return
        if 'combo_snapshot' in template.subscriptions:
            QMessageBox.information(self, '功能已停用', '连携 CD 显示已停用。')
            return
        if template.path:
            entry = replace(entry, name=template.name)
        self.app_config.overlays.append(entry)
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.apply_entry(entry)
        self._refresh_overlay_views()

    def _remove_selected_overlay(self) -> None:
        entry = self._selected_overlay()
        if entry is None or entry.source_type == OverlaySourceType.BUILTIN:
            return
        self.app_config.overlays = [item for item in self.app_config.overlays if item.id != entry.id]
        self.app_config.overlay_restore_ids = [key for key in self.app_config.overlay_restore_ids if key != entry.id]
        self.overlay_manager.remove_entry(entry.id)
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _enable_all_overlays(self) -> None:
        self.app_config.overlays = [replace(entry, enabled=True) for entry in self.app_config.overlays]
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.sync_entries(self.app_config.overlays)
        self._refresh_overlay_views()

    def _disable_all_overlays(self) -> None:
        self.app_config.overlays = [replace(entry, enabled=False) for entry in self.app_config.overlays]
        save_app_config(self.app_config, self.config_path)
        self.overlay_manager.sync_entries(self.app_config.overlays)
        self._refresh_overlay_views()

    def _apply_overlay_name(self) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None:
            return
        name = self.overlay_page.name_edit.text().strip() or entry.name
        if name != entry.name:
            self._replace_overlay_entry(replace(entry, name=name))

    def _apply_overlay_source_value(self) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None or entry.source_type != OverlaySourceType.URL:
            return
        value = self.overlay_page.source_value_edit.text().strip()
        if value and value != entry.source_value:
            self._replace_overlay_entry(replace(entry, source_value=value))

    def _apply_overlay_enabled(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and checked != entry.enabled:
            self._replace_overlay_entry(replace(entry, enabled=checked))

    def _apply_template_setting(self, key: str, value: object) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None:
            updated = with_template_value(entry, key, value)
            if updated != entry:
                self._replace_overlay_entry(updated)

    def _apply_overlay_locked(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and checked != entry.locked:
            self._replace_overlay_entry(replace(entry, locked=checked))

    def _apply_overlay_click_through(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and checked != entry.click_through:
            self._replace_overlay_entry(replace(entry, click_through=checked))

    def _apply_overlay_opacity(self, value: int) -> None:
        self.overlay_page.opacity_value.setText(f"{value}%")
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None:
            return
        opacity = max(0.1, min(1.0, value / 100.0))
        if abs(opacity - entry.opacity) > 0.0001:
            self._replace_overlay_entry(replace(entry, opacity=opacity))

    def _apply_overlay_font_size(self, value: int) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        factor = value / 100.0
        if entry is not None and abs(factor - entry.font_scale) > 0.0001:
            self._replace_overlay_entry(replace(entry, font_scale=factor, scale=1.0))

    def _reset_selected_overlay_layout(self) -> None:
        entry = self._selected_overlay()
        if entry is not None:
            self._replace_overlay_entry(replace(entry, geometry=None, font_scale=1.0, scale=1.0))

    def _apply_overlay_dimensions(self, *_args) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is None:
            return
        geometry = entry.geometry or OverlayGeometry(100, 100, 0, 0)
        updated = OverlayGeometry(geometry.x, geometry.y, self.overlay_page.width_edit.value(), self.overlay_page.height_edit.value())
        if updated != entry.geometry:
            self._replace_overlay_entry(replace(entry, geometry=updated))

    def _toggle_overlay_visibility(self) -> None:
        shown = {entry.id for entry in self.app_config.overlays if entry.enabled and not entry.hidden}
        if shown:
            self.app_config.overlay_restore_ids = [entry.id for entry in self.app_config.overlays if entry.id in shown]
            self.app_config.overlays = [replace(entry, hidden=True) if entry.id in shown else entry
                                        for entry in self.app_config.overlays]
        else:
            restore = set(self.app_config.overlay_restore_ids)
            self.app_config.overlays = [replace(entry, hidden=False) if not restore or entry.id in restore else entry
                                        for entry in self.app_config.overlays]
            self.app_config.overlay_restore_ids = []
        self.overlay_manager.sync_entries(self.app_config.overlays)
        save_app_config(self.app_config, self.config_path)
        self._refresh_overlay_views()

    def _apply_overlay_visible(self, checked: bool) -> None:
        if self.overlay_page._updating:
            return
        entry = self._selected_overlay()
        if entry is not None and entry.enabled:
            self._replace_overlay_entry(replace(entry, hidden=not bool(checked)))


    def _bind_overlay_events(self) -> None:
        self.overlay_page.status_card.visibility_button.clicked.connect(self._toggle_overlay_visibility)
        self.overlay_page.overlay_list.currentItemChanged.connect(self._sync_overlay_selection)
        self.overlay_page.add_url_btn.clicked.connect(self._add_url_overlay)
        self.overlay_page.add_file_btn.clicked.connect(self._add_file_overlay)
        self.overlay_page.remove_btn.clicked.connect(self._remove_selected_overlay)
        self.overlay_page.enable_all_btn.clicked.connect(self._enable_all_overlays)
        self.overlay_page.disable_all_btn.clicked.connect(self._disable_all_overlays)
        self.overlay_page.reset_layout_btn.clicked.connect(self._reset_selected_overlay_layout)
        self.overlay_page.name_edit.editingFinished.connect(self._apply_overlay_name)
        self.overlay_page.source_value_edit.editingFinished.connect(self._apply_overlay_source_value)
        self.overlay_page.setting_changed.connect(self._apply_template_setting)
        self.overlay_page.enabled_switch.checkedChanged.connect(self._apply_overlay_enabled)
        self.overlay_page.visible_switch.checkedChanged.connect(self._apply_overlay_visible)
        self.overlay_page.locked_switch.checkedChanged.connect(self._apply_overlay_locked)
        self.overlay_page.click_switch.checkedChanged.connect(self._apply_overlay_click_through)
        self.overlay_page.opacity_slider.valueChanged.connect(self._apply_overlay_opacity)
        self.overlay_page.font_size_edit.valueChanged.connect(self._apply_overlay_font_size)
        self.overlay_page.width_edit.valueChanged.connect(self._apply_overlay_dimensions)
        self.overlay_page.height_edit.valueChanged.connect(self._apply_overlay_dimensions)
