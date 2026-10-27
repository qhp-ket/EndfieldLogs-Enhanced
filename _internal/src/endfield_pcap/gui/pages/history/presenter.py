"""Map history requests/results to widgets, overlays and explicit detail windows."""
from dataclasses import replace
from pathlib import Path
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QFileDialog
from endfield_pcap.application.history import HistoryBatch, HistoryListing, TraceImport
from endfield_pcap.application.records import BattleRecordInfo
from endfield_pcap.gui.battle.presenter import BattleDetailPresenter
from endfield_pcap.gui.pages.history.files import request_rename, open_folder
from endfield_pcap.history.files import record_label, relocate_key
from endfield_pcap.history.index import record_key
from endfield_pcap.models import OverlaySourceType


class HistoryPresenter(QObject):
    def __init__(self, page, controller, settings, overlays, replace_overlay, refresh_settings, parent):
        super().__init__(parent)
        self.page, self.controller, self.settings = page, controller, settings
        self.overlays = overlays
        self._replace_overlay, self._refresh_settings = replace_overlay, refresh_settings
        self.dialog = None
        page.reload_btn.clicked.connect(self.refresh)
        page.import_trace_btn.clicked.connect(self.import_dialog)
        page.remove_record_btn.clicked.connect(self.remove_selected)
        page.rename_record_btn.clicked.connect(lambda: request_rename(self))
        page.open_folder_btn.clicked.connect(lambda: open_folder(self))
        page.load_overlay_btn.clicked.connect(self.load_selected)
        page.analysis_detail_btn.clicked.connect(self.inspect_selected)
        page.return_live_btn.clicked.connect(self.return_live)
        page.record_list.currentItemChanged.connect(self.sync_selection)
        page.record_list.itemSelectionChanged.connect(self.sync_selection)

    def sync_selection(self, *_):
        listing = self.page.record_list
        keys = [item.data(Qt.ItemDataRole.UserRole) for item in listing.selectedItems()]
        current = listing.currentItem()
        self.controller.select(keys, current.data(Qt.ItemDataRole.UserRole) if current else None)
        selected = self.controller.selected_records
        record = selected[-1] if selected else None
        self.page.record_count.setText(f'共 {len(self.controller.records)} 条 · 已选 {len(selected)} 条'
            + (' · 正在更新索引…' if self.controller.records_pending else ''))
        for button in (self.page.load_overlay_btn, self.page.remove_record_btn, self.page.analysis_detail_btn):
            button.setEnabled(record is not None)
        self.page.rename_record_btn.setEnabled(bool(selected)
            and len({item.file_path for item in selected}) == 1 and not self.controller.busy)
        self.page.import_trace_btn.setEnabled(not self.controller.import_pending)
        self.page.show_record(record)

    def _refresh_list(self):
        self.page.set_records(self.controller.records)
        self.sync_selection()

    def refresh(self):
        if self.controller.refresh():
            self._refresh_settings()
        self._refresh_list()

    def import_dialog(self):
        names, _ = QFileDialog.getOpenFileNames(self.parent(), '导入 trace 日志',
            str(self.settings.current.service.log_dir), 'Trace 日志 (*.log)')
        if names:
            self.import_files([Path(name).resolve() for name in names])

    def import_files(self, paths, *, restore_removed=True):
        if self.controller.import_files(paths, restore_removed=restore_removed):
            self.page.import_trace_status.setText(f'正在建立 {len(paths)} 份 trace 的列表索引（按需计算完整统计）…')
            self.sync_selection()

    def load_selected(self):
        self._load(self.controller.selected_records)

    def _load(self, records, *, open_details=False):
        if self.controller.load([record_key(record) for record in records], open_details=open_details):
            self.page.overlay_source_status.setText(f'正在加载 {len(records)} 场；最终显示：{records[-1].label}')
            self.sync_selection()

    def inspect_selected(self):
        selected = self.controller.selected_records
        if not selected:
            return
        record = selected[-1]
        if self.dialog is not None and self.dialog.record_info == BattleRecordInfo.from_record(record, record_label(record)):
            self.dialog.showNormal()
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        snapshot = self.controller.cached_snapshot(record)
        if snapshot is None:
            self._load([record], open_details=True)
        elif self.dialog is not None and self.dialog.snapshot is snapshot:
            self.dialog.showNormal()
            self.dialog.raise_()
            self.dialog.activateWindow()
        else:
            self._show_detail(snapshot, record)

    def _show_detail(self, snapshot, record):
        previous, self.dialog = self.dialog, None
        if previous is not None:
            previous.close()
        dialog = BattleDetailPresenter.create(snapshot, record_label(record), self.settings,
                                              record=record, parent=self.parent())
        self.dialog = dialog
        dialog.finished.connect(lambda: self._forget_dialog(dialog))
        dialog.show()

    def _forget_dialog(self, dialog):
        if self.dialog is dialog:
            self.dialog = None
            self.controller.release_cache()

    def _show_history(self, snapshot, record):
        label = record_label(record)
        self.overlays.show_history(snapshot, label)
        for entry in list(self.settings.current.overlays):
            if entry.source_type == OverlaySourceType.BUILTIN and entry.source_value == 'damage' and not entry.enabled:
                self._replace_overlay(replace(entry, enabled=True))
        self.page.overlay_source_status.setText(f'悬浮窗：历史 · {label}')

    def drain(self):
        for result in self.controller.drain():
            if isinstance(result, HistoryBatch):
                last = result.results[-1]
                errors = [item.error for item in result.results if item.error is not None]
                if last.error is not None:
                    self.page.overlay_source_status.setText(f'加载失败：{last.error}')
                else:
                    self._show_history(last.snapshot, self.controller.record)
                    if result.open_details:
                        self._show_detail(last.snapshot, self.controller.record)
                    if errors:
                        self.page.overlay_source_status.setText(self.page.overlay_source_status.text()
                            + f'（{len(errors)} 场加载失败，详情见提示）')
                self.page.overlay_source_status.setToolTip('；'.join(errors))
            elif isinstance(result, HistoryListing):
                self.page.record_count.setToolTip('；'.join(result.errors))
            elif isinstance(result, TraceImport):
                count = sum(len(records) for _, _, records in result.results)
                self.page.import_trace_status.setText(f'已索引 {len(result.results)} 份 trace，共 {count} 场战斗\n引用原文件；点击加载后分析'
                    + (f'（{len(result.errors)} 份读取失败，详情见提示）' if result.errors else ''))
                self.page.import_trace_status.setToolTip('；'.join(result.errors))
            self._refresh_list()

    def return_live(self):
        self.controller.return_live()
        self.overlays.return_live()
        self.page.overlay_source_status.setText('悬浮窗：实时日志')
        self.sync_selection()

    def remove_selected(self):
        keys = [record_key(record) for record in self.controller.selected_records]
        if not keys:
            return
        close_detail = self.dialog is not None and self.dialog.record_info is not None and self.dialog.record_info.key in keys
        if self.controller.remove(keys):
            self.overlays.return_live()
            self.page.overlay_source_status.setText('悬浮窗：实时日志')
        if close_detail:
            self.dialog.close()
        self._refresh_list()

    def rename(self, path, label):
        try:
            new = self.controller.rename(path, label)
        except (ValueError, OSError) as exc:
            self.page.import_trace_status.setText(f'重命名失败：{exc}')
            return False
        listing = self.page.record_list
        for index in range(listing.count()):
            item = listing.item(index)
            item.setData(Qt.ItemDataRole.UserRole, relocate_key(item.data(Qt.ItemDataRole.UserRole), path, new))
        self._refresh_list()
        if self.dialog is not None and self.dialog.record_info.file_path == path:
            info = self.dialog.record_info
            key = relocate_key(info.key, path, new)
            row = next((record for record in self.controller.records if record_key(record) == key), None)
            self.dialog.record_info = replace(info, key=key, file_path=new,
                label=record_label(row) if row else info.label.replace(path.name, new.name))
            self.dialog.set_record_label(self.dialog.record_info.label)
            self.dialog.presenter.relocate_record(path, new)
        record = next((record for record in self.controller.records if record_key(record) == self.controller.detail_key), None)
        if record is not None:
            if self.controller.displayed_key and self.controller.detail_snapshot is not None:
                self._show_history(self.controller.detail_snapshot, record)
        self.page.import_trace_status.setText(f'已重命名：{new.name}；日志内容与上传校验保持不变')
        return True

    def close(self):
        self.controller.close()
        if self.dialog is not None:
            self.dialog.close()
