"""Runtime log display, independent of capture and page visibility."""
import logging
import queue
from collections import deque
from pathlib import Path
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QPlainTextEdit
from qfluentwidgets import CaptionLabel, PushButton
from endfield_pcap.gui.shared.widgets import InterfacePage


class RuntimeLogPage(InterfacePage):
    def __init__(self, log_directory: Path, parent=None):
        super().__init__('runtimeLogInterface', '运行日志', '', parent)
        self.log_directory = Path(log_directory)
        self._lines=deque(maxlen=800)
        self._dirty=False
        actions = QHBoxLayout()
        self.copy_btn = PushButton('复制', self)
        self.clear_btn = PushButton('清空显示', self)
        self.open_folder_btn = PushButton('打开日志文件夹', self)
        self.clear_btn.setToolTip('只清空当前显示，不删除磁盘日志；后续日志继续收集')
        for button in (self.copy_btn, self.clear_btn, self.open_folder_btn):
            actions.addWidget(button)
        actions.addStretch()
        self.content_layout.addLayout(actions)
        self.path_label = CaptionLabel(str(self.log_directory), self)
        self.path_label.setWordWrap(True)
        self.content_layout.addWidget(self.path_label)
        self.log_view = QPlainTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(800)
        self.log_view.setMinimumHeight(160)
        self.content_layout.addWidget(self.log_view, 1)
        self.copy_btn.clicked.connect(self.copy_logs)
        self.clear_btn.clicked.connect(self.clear_display)
        self.open_folder_btn.clicked.connect(self.open_log_folder)

    def append_log(self, line):
        pending=self._dirty
        self._lines.extend(str(line).splitlines() or [''])
        self._dirty=True
        if self.isVisible():
            if pending:self.flush_display()
            else:
                self.log_view.appendPlainText(str(line))
                self._dirty=False

    def flush_display(self):
        if self._dirty:
            self.log_view.setPlainText('\n'.join(self._lines))
            self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())
            self._dirty=False

    def clear_display(self):
        self._lines.clear()
        self.log_view.clear()
        self._dirty=False

    def showEvent(self,event):
        super().showEvent(event)
        self.flush_display()

    def copy_logs(self):
        selected = self.log_view.textCursor().selectedText().replace('\u2029', '\n')
        QApplication.clipboard().setText(selected or '\n'.join(self._lines))

    def open_log_folder(self):
        self.log_directory.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.log_directory.resolve())))


class QtLogHandler(logging.Handler):
    def __init__(self, sink: "queue.Queue[tuple[str, object]]") -> None:
        super().__init__()
        self.sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.sink.put_nowait(("log", self.format(record)))
        except Exception:
            return
