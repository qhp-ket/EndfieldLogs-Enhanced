"""File dialogs and Explorer integration for the history presenter."""
from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QInputDialog
from endfield_pcap.history.files import custom_name


def request_rename(presenter):
    records = presenter.controller.selected_records
    if len({record.file_path for record in records}) != 1 or presenter.controller.busy:
        presenter.page.import_trace_status.setText('请选中同一个文件的记录，并等待当前索引或分析结束')
        return
    path = records[-1].file_path
    label, accepted = QInputDialog.getText(presenter.parent(), '重命名日志文件',
        '名称（保留原始前缀、日期和扩展名）\n同文件内的所有战斗一同改名，日志内容保持不变：', text=custom_name(path))
    if accepted:
        presenter.rename(path, label)


def open_folder(presenter):
    records = presenter.controller.selected_records
    path = records[-1].file_path if records else presenter.settings.current.service.log_dir
    if path.is_file():
        result = QProcess.startDetached('explorer.exe', ['/select,', str(path)])
        ok = result[0] if isinstance(result, tuple) else result
    else:
        ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path if path.is_dir() else path.parent)))
    if not ok:
        presenter.page.import_trace_status.setText(f'无法打开文件夹：{path.parent}')
