"""History actions: lazy indexing, batch analysis, source selection and removal."""
from __future__ import annotations
import logging
import threading
from pathlib import Path
from dataclasses import replace
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog
from endfield_pcap.gui.config import save_app_config
from endfield_pcap.history.index import record_key, _resolve_log_dir
from endfield_pcap.history.analysis import load_record_snapshot
from endfield_pcap.history.importer import apply_snapshot_summary
from endfield_pcap.history.records import CombatRecord
from endfield_pcap.models import OverlaySourceType
from endfield_pcap.gui.pages.history.files import HistoryFileActions
from endfield_pcap.history.files import record_label


LOGGER = logging.getLogger(__name__)

class HistoryActions(HistoryFileActions):
    def _load_selected_history(self) -> None:
        records = self._selected_history_records()
        self._start_history_analysis(records)

    @staticmethod
    def _record_signature(record):
        try:
            stat = record.file_path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _inspect_selected_history(self) -> None:
        records = self._selected_history_records()
        if not records:
            return
        record = records[-1]
        if (self._history_detail_snapshot is not None and self._history_detail_key == record_key(record)
                and self._history_detail_signature == self._record_signature(record)):
            self._show_history_detail(self._history_detail_snapshot, record_label(record))
        else:
            self._start_history_analysis([record], open_details=True)

    def _show_history_detail(self, snapshot, label) -> None:
        from endfield_pcap.gui.battle.detail import BattleDetailDialog
        if self._history_detail_dialog is not None:
            self._history_detail_dialog.close()
        dialog = BattleDetailDialog(snapshot, label, self)
        self._history_detail_dialog = dialog
        dialog.finished.connect(lambda: self._forget_history_dialog(dialog))
        dialog.show()

    def _forget_history_dialog(self, dialog) -> None:
        if self._history_detail_dialog is dialog:
            self._history_detail_dialog = None

    def _start_history_analysis(self, records, *, open_details=False) -> None:
        if not records:
            return
        record = records[-1]
        self._history_cancel.set()
        self._history_cancel = threading.Event()
        cancel = self._history_cancel
        self._history_generation += 1
        generation = self._history_generation
        self._history_inspect_generation = generation if open_details else None
        self._history_record = record
        self._history_pending_keys = {record_key(item) for item in records}
        self.records_page.rename_record_btn.setEnabled(False)
        self.records_page.overlay_source_status.setText(f"正在加载 {len(records)} 场；最终显示：{record.label}")
        sink = self.service_controller.queue
        def analyze() -> None:
            results = []
            for item in records:
                if cancel.is_set():
                    return
                try:
                    results.append((item, load_record_snapshot(item), None))
                except Exception as exc:
                    LOGGER.exception("history snapshot analysis failed")
                    results.append((item, None, str(exc)))
            sink.put(("history_batch", (generation, results)))
        threading.Thread(target=analyze, name="history-analysis", daemon=True).start()


    def _complete_history_batch(self, payload) -> None:
        generation, results = payload
        if generation != self._history_generation:
            return
        self._history_pending_keys.clear()
        errors = []
        for record, snapshot, error in results:
            if error:
                errors.append(f'{record.label}: {error}')
            else:
                apply_snapshot_summary(record, snapshot)
        self._refresh_record_list()
        record, snapshot, error = results[-1]
        self._history_record = record
        self._complete_history_load((generation, record_label(record), snapshot, error))
        self.records_page.overlay_source_status.setToolTip('；'.join(errors))
        if errors and not error:
            self.records_page.overlay_source_status.setText(
                self.records_page.overlay_source_status.text() + f'（{len(errors)} 场加载失败，详情见提示）')


    def _complete_history_load(self, payload) -> None:
        generation, label, snapshot, error = payload
        if generation != self._history_generation:
            return
        if error:
            self.records_page.overlay_source_status.setText(f"加载失败：{error}")
            return
        record = self._history_record
        if record is not None:
            apply_snapshot_summary(record, snapshot)
            self._history_displayed_key = record_key(record)
            self._refresh_record_list()
            # Retain one already requested report, never eagerly analyze the
            # list or persist full timeline data into the lightweight index.
            self._history_detail_snapshot = snapshot
            self._history_detail_key = record_key(record)
            self._history_detail_signature = self._record_signature(record)
        self.overlay_manager.show_history(snapshot, label)
        for entry in list(self.app_config.overlays):
            if entry.source_type == OverlaySourceType.BUILTIN and entry.source_value == "damage" and not entry.enabled:
                self._replace_overlay_entry(replace(entry, enabled=True))
        self.records_page.overlay_source_status.setText(f"悬浮窗：历史 · {label}")
        if self._history_inspect_generation == generation:
            self._history_inspect_generation = None
            self._show_history_detail(snapshot, label)


    def _return_live_overlay(self) -> None:
        self._history_generation += 1  # Invalidate any pending history worker.
        self._history_displayed_key = None
        self._history_record = None
        self._history_pending_keys = set()
        self._history_inspect_generation = None
        if hasattr(self, '_history_cancel'):
            self._history_cancel.set()
        self.overlay_manager.return_live()
        self.records_page.overlay_source_status.setText("悬浮窗：实时日志")
        self._sync_record_selection()


    def _import_trace_logs(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, "导入 trace 日志", str(self.app_config.service.log_dir), "Trace 日志 (*.log)")
        if names:
            self._queue_trace_import([Path(name).resolve() for name in names])


    def _queue_trace_import(self, paths: list[Path], *, restore_removed: bool = True) -> None:
        if self._trace_import_pending or not paths:
            return
        self._trace_import_pending = True
        self.records_page.rename_record_btn.setEnabled(False)
        generation = self._trace_import_generation
        self._trace_restore_keys = set(self.app_config.hidden_history_records) if restore_removed else set()
        self.records_page.import_trace_btn.setEnabled(False)
        self.records_page.import_trace_status.setText(f"正在建立 {len(paths)} 份 trace 的列表索引（不计算完整统计）…")
        sink = self.service_controller.queue
        index = self._history_index
        def read() -> None:
            results, errors = [], []
            for path in dict.fromkeys(paths):
                try:
                    stat = path.stat()
                    records = index.records(path, trace=True)
                    results.append((path, (stat.st_mtime_ns, stat.st_size), records))
                except Exception as exc:
                    LOGGER.exception("trace import failed: %s", path)
                    errors.append(f"{path.name}: {exc}")
            sink.put(("trace_import", (generation, results, errors)))
        threading.Thread(target=read, name="trace-import", daemon=True).start()


    def _complete_trace_import(self, payload) -> None:
        generation, results, errors = payload
        if generation != self._trace_import_generation:
            return
        self._trace_import_pending = False
        self.records_page.import_trace_btn.setEnabled(True)
        restored_keys = {record_key(record) for _, _, records in results for record in records} & self._trace_restore_keys
        self.app_config.hidden_history_records = [key for key in self.app_config.hidden_history_records if key not in restored_keys]
        for path, signature, records in results:
            self._trace_records[path] = records
            self._trace_signatures[path] = signature
            if path not in self.app_config.imported_trace_files:
                self.app_config.imported_trace_files.append(path)
        if results:
            save_app_config(self.app_config, self.config_path)
            self._refresh_record_list()
        count = sum(len(records) for _, _, records in results)
        message = f"已索引 {len(results)} 份 trace，共 {count} 场战斗；引用原文件，点击加载后分析"
        if errors:
            message += "；读取失败：" + "；".join(errors)
        self.records_page.import_trace_status.setText(
            f"已索引 {len(results)} 份 trace，共 {count} 场战斗\n引用原文件；点击加载后分析"
            + (f"（{len(errors)} 份读取失败，详情见提示）" if errors else ''))
        self.records_page.import_trace_status.setToolTip(message)
        self._sync_record_selection()


    def _refresh_record_list(self) -> None:
        records = list(self._raw_records)
        records.extend(record for imported in self._trace_records.values() for record in imported)
        hidden = set(self.app_config.hidden_history_records)
        records = [record for record in records if record_key(record) not in hidden]
        self.records = sorted(records, key=lambda record: record.started_at_ms, reverse=True)
        self.records_page.set_records(self.records)
        self._sync_record_selection()


    def _load_records(self) -> None:
        resolved_log_dir = _resolve_log_dir(self.app_config.service.log_dir)
        if resolved_log_dir != self.app_config.service.log_dir:
            self.app_config.service.log_dir = resolved_log_dir
            save_app_config(self.app_config, self.config_path)
            self._refresh_settings_page()
        self._refresh_record_list()
        if self._records_log_dir != self.app_config.service.log_dir:
            self._records_generation += 1
            self._records_pending = False
            self._raw_records = []
            self._records_log_dir = self.app_config.service.log_dir
            self._refresh_record_list()
        if not self._records_pending:
            self._records_pending = True
            self.records_page.rename_record_btn.setEnabled(False)
            self._records_generation += 1
            generation = self._records_generation
            index = self._history_index
            log_dir = self.app_config.service.log_dir
            sink = self.service_controller.queue
            self.records_page.record_count.setText(f"共 {len(self.records)} 条 · 正在更新索引…")
            def scan() -> None:
                records, errors = [], []
                try:
                    for path in sorted(log_dir.rglob('session_*.ndjson'), reverse=True):
                        try:
                            records.extend(index.records(path))
                        except Exception as exc:
                            errors.append(f'{path.name}: {exc}')
                except OSError as exc:
                    errors.append(str(exc))
                sink.put(('history_index', (generation, records, errors)))
            threading.Thread(target=scan, name='history-index', daemon=True).start()
        changed = []
        for path in self.app_config.imported_trace_files:
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
            if self._trace_signatures.get(path) != signature:
                changed.append(path)
        self._queue_trace_import(changed, restore_removed=False)


    def _complete_record_index(self, payload) -> None:
        generation, records, errors = payload
        if generation != self._records_generation:
            return
        self._records_pending = False
        self._raw_records = records
        self._refresh_record_list()
        self.records_page.record_count.setToolTip('；'.join(errors))


    def _remove_selected_history(self) -> None:
        records = self._selected_history_records()
        if not records:
            return
        keys = {record_key(record) for record in records}
        if self._history_detail_key in keys:
            self._history_detail_snapshot = None
            self._history_detail_key = None
            self._history_detail_signature = None
            if self._history_detail_dialog is not None:
                self._history_detail_dialog.close()
        self.app_config.hidden_history_records.extend(sorted(keys - set(self.app_config.hidden_history_records)))
        # A late analysis/import/index result must not restore a removed row.
        pending_key = record_key(self._history_record) if self._history_record is not None else None
        if self._history_displayed_key in keys or pending_key in keys or self._history_pending_keys & keys:
            self._return_live_overlay()
        save_app_config(self.app_config, self.config_path)
        self._refresh_record_list()


    def _sync_record_selection(self) -> None:
        selected_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.records_page.record_list.selectedItems()]
        self._history_selection_order = [key for key in self._history_selection_order if key in selected_keys]
        self._history_selection_order.extend(key for key in selected_keys if key not in self._history_selection_order)
        item = self.records_page.record_list.currentItem()
        if item is not None:
            key = item.data(Qt.ItemDataRole.UserRole)
            if key in self._history_selection_order:
                self._history_selection_order.remove(key)
                self._history_selection_order.append(key)
        selected_records = self._selected_history_records()
        self.records_page.record_count.setText(f"共 {len(self.records)} 条 · 已选 {len(selected_records)} 条")
        selected = selected_records[-1] if selected_records else None
        self._selected_record = selected
        self.records_page.load_overlay_btn.setEnabled(selected is not None)
        self.records_page.remove_record_btn.setEnabled(selected is not None)
        self.records_page.analysis_detail_btn.setEnabled(selected is not None)
        self.records_page.rename_record_btn.setEnabled(
            bool(selected_records) and len({r.file_path for r in selected_records}) == 1 and not self._history_files_busy())
        self.records_page.show_record(selected)


    def _selected_history_records(self) -> list[CombatRecord]:
        indexed = {(str(record.file_path), record.record_index): record for record in self.records}
        return [indexed[key] for key in self._history_selection_order if key in indexed]


    def _handle_current_interface_changed(self, index: int) -> None:
        stacked = getattr(self, "stackedWidget", None)
        if stacked is None:
            return
        if stacked.widget(index) is self.records_page:
            self._load_records()


    def _bind_records_events(self) -> None:
        self.records_page.reload_btn.clicked.connect(self._load_records)
        self.records_page.import_trace_btn.clicked.connect(self._import_trace_logs)
        self.records_page.remove_record_btn.clicked.connect(self._remove_selected_history)
        self.records_page.rename_record_btn.clicked.connect(self._rename_selected_history)
        self.records_page.open_folder_btn.clicked.connect(self._open_history_folder)
        self.records_page.load_overlay_btn.clicked.connect(self._load_selected_history)
        self.records_page.analysis_detail_btn.clicked.connect(self._inspect_selected_history)
        self.records_page.return_live_btn.clicked.connect(self._return_live_overlay)
        self.records_page.record_list.currentItemChanged.connect(self._sync_record_selection)
        self.records_page.record_list.itemSelectionChanged.connect(self._sync_record_selection)
