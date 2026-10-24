"""History file actions kept separate from indexing and analysis workers."""
from pathlib import Path
from PySide6.QtCore import QProcess, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog
from endfield_pcap.gui.config import save_app_config
from endfield_pcap.history.files import (
    custom_name,
    rename_log,
    relocate_key,
    relocate_record,
    record_label,
)
from endfield_pcap.history.index import record_key


class HistoryFileActions:
    def _history_files_busy(self):
        return self._records_pending or self._trace_import_pending or bool(self._history_pending_keys)

    def _rename_selected_history(self):
        records = self._selected_history_records()
        paths = {r.file_path for r in records}
        if len(paths) != 1 or self._history_files_busy():
            self.records_page.import_trace_status.setText('请选中同一个文件的记录，并等待当前索引或分析结束')
            return
        path = records[-1].file_path
        label, accepted = QInputDialog.getText(self, '重命名日志文件',
            '名称（保留原始前缀、日期和扩展名）\n同文件内的所有战斗一同改名；不会修改日志内容：',
            text=custom_name(path))
        if accepted:
            self._rename_history_file(path, label)

    def _rename_history_file(self, path, label):
        if self._history_files_busy():
            self.records_page.import_trace_status.setText('请等待当前索引或分析结束后重命名')
            return False
        controller = self.service_controller
        if controller.is_running():
            service = getattr(controller, '_service', None)
            bridge = getattr(service, 'trace_bridge', None)
            active = [getattr(service, 'current_log_path', None), getattr(bridge, 'trace_file', None),
                      getattr(getattr(service, 'config', None), 'trace_file', None)]
            if service is None or any(p and Path(p).resolve() == path.resolve() for p in active):
                self.records_page.import_trace_status.setText('该文件正在抓包写入，请先在首页停止服务再重命名')
                return False
        try:
            new = rename_log(path, label)
        except (ValueError, OSError) as exc:
            self.records_page.import_trace_status.setText(f'重命名失败：{exc}')
            return False
        if new == path:
            return True
        # All records, including hidden battles, share this physical file.
        records = [*self._raw_records, *(r for rows in self._trace_records.values() for r in rows),
                   *self.records, self._history_record]
        for record in records:
            if record is not None:
                relocate_record(record, path, new)
        if path in self._trace_records:
            self._trace_records[new] = self._trace_records.pop(path)
        if path in self._trace_signatures:
            self._trace_signatures[new] = self._trace_signatures.pop(path)
        self.app_config.imported_trace_files = [new if p == path else p for p in self.app_config.imported_trace_files]
        self.app_config.hidden_history_records = [relocate_key(k, path, new) for k in self.app_config.hidden_history_records]
        for attribute in ('_history_displayed_key', '_history_detail_key'):
            setattr(self, attribute, relocate_key(getattr(self, attribute), path, new))
        self._history_selection_order = [(str(new) if p == str(path) else p, i) for p, i in self._history_selection_order]
        listing = self.records_page.record_list
        for i in range(listing.count()):
            item = listing.item(i)
            p, index = item.data(Qt.ItemDataRole.UserRole)
            if p == str(path):
                item.setData(Qt.ItemDataRole.UserRole, (str(new), index))
        self._history_index.relocate(path, new)
        save_app_config(self.app_config, self.config_path)
        self._refresh_record_list()
        detail_record = next((r for r in records if r is not None and record_key(r) == self._history_detail_key), None)
        if detail_record is not None and self._history_detail_dialog is not None:
            self._history_detail_dialog.set_record_label(record_label(detail_record))
        if self._history_record is not None and self._history_record.file_path == new and self._history_displayed_key:
            label = record_label(self._history_record)
            self.records_page.overlay_source_status.setText(f'悬浮窗：历史 · {label}')
            if self._history_detail_snapshot is not None:
                self.overlay_manager.show_history(self._history_detail_snapshot, label)
        self.records_page.import_trace_status.setText(f'已重命名：{new.name}；日志内容与上传校验保持不变')
        return True

    def _open_history_folder(self):
        records = self._selected_history_records()
        path = records[-1].file_path if records else self.app_config.service.log_dir
        if path.is_file():
            result = QProcess.startDetached('explorer.exe', ['/select,', str(path)])
            ok = result[0] if isinstance(result, tuple) else result
        else:
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))
        if not ok:
            self.records_page.import_trace_status.setText(f'无法打开文件夹：{path.parent}')
