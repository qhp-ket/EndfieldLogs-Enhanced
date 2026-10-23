"""History list and detail widgets, independent of capture lifecycle."""
from datetime import datetime
from PySide6.QtCore import Qt, QItemSelectionModel, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter, QFrame, QHeaderView, QTableWidgetItem, QAbstractItemView, QLayout
from qfluentwidgets import HeaderCardWidget, PrimaryPushButton, PushButton, CaptionLabel, ListWidget, StrongBodyLabel, TableWidget, setFont
from .gui_widgets import InterfacePage, _format_duration
from .record_parser import CombatRecord
from .history_files import record_label


class _HistoryHint(CaptionLabel):
    """Let wrapped instructions contribute their full height to page scrolling."""
    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        return QSize(hint.width(), max(hint.height(), self.heightForWidth(max(1, self.width()))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.updateGeometry()


class BattleLogPage(InterfacePage):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("battleLogInterface", "战斗日志", "查看历史战斗的聚合统计信息。", parent)

        self.content_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        summary_row = QHBoxLayout()
        summary_row.setSpacing(16)
        self.content_layout.addLayout(summary_row)
        splitter = self.records_splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)
        self.content_layout.addWidget(splitter)

        master_card = self.actions_card = HeaderCardWidget(splitter)
        master_card.setTitle("记录操作")
        list_card = self.list_card = HeaderCardWidget(splitter)
        list_card.setTitle("记录列表")
        splitter.addWidget(master_card)
        splitter.addWidget(list_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 7)
        list_wrapper = QWidget(list_card)
        list_card.viewLayout.addWidget(list_wrapper)
        list_layout = QVBoxLayout(list_wrapper)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(12)

        master_wrapper = QWidget(master_card)
        master_card.viewLayout.addWidget(master_wrapper)
        master_layout = QVBoxLayout(master_wrapper)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.setSpacing(12)

        action_row = QWidget(list_wrapper)
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.reload_btn = PrimaryPushButton("刷新记录", action_row)
        self.record_count = CaptionLabel("共 0 条", action_row)
        action_layout.addWidget(self.reload_btn)
        action_layout.addStretch()
        action_layout.addWidget(self.record_count)
        list_layout.addWidget(action_row)

        self.record_list = ListWidget(list_wrapper)
        self.record_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.record_list.itemSelectionChanged.connect(self.record_list.updateSelectedRows)
        self.record_list.setMinimumSize(340, 400)
        list_layout.addWidget(self.record_list, 1)
        self.load_overlay_btn = PrimaryPushButton("加载选中记录", master_wrapper)
        self.analysis_detail_btn = PushButton("战斗时间轴 / 技能构成…", master_wrapper)
        self.analysis_detail_btn.setEnabled(False)
        self.analysis_detail_btn.setToolTip("按需分析最后选中的一场记录；已加载的当前战斗直接打开")
        self.select_all_btn = PushButton("全选", action_row)
        self.select_all_btn.clicked.connect(self.record_list.selectAll)
        action_layout.insertWidget(1, self.select_all_btn)
        self.import_trace_btn = PushButton("导入 trace 日志…", master_wrapper)
        self.import_trace_status = _HistoryHint("引用原文件，不复制；完整统计在点击加载后计算", master_wrapper)
        self.import_trace_status.setWordWrap(True)
        self.load_overlay_btn.setEnabled(False)
        self.return_live_btn = PushButton("返回实时日志", master_wrapper)
        self.overlay_source_status = _HistoryHint("悬浮窗：实时日志", master_wrapper)
        self.overlay_source_status.setWordWrap(True)
        master_layout.addWidget(self.load_overlay_btn)
        master_layout.addWidget(self.analysis_detail_btn)
        self.rename_record_btn = PushButton('重命名文件…', master_wrapper)
        self.rename_record_btn.setEnabled(False)
        self.rename_record_btn.setToolTip('修改实际日志文件名；同文件内所有战斗一起改名，内容保持不变')
        self.open_folder_btn = PushButton('打开所在文件夹', master_wrapper)
        master_layout.addWidget(self.rename_record_btn)
        master_layout.addWidget(self.open_folder_btn)
        master_layout.addWidget(self.import_trace_btn)
        master_layout.addWidget(self.import_trace_status)
        self.remove_record_btn = PushButton("从列表移除选中记录", master_wrapper)
        self.remove_record_btn.setEnabled(False)
        self.remove_record_hint = _HistoryHint("Ctrl / Shift 多选；加载后仅展示最后选中项。移除不会删除原始日志文件，重新导入 trace 可恢复。", master_wrapper)
        self.remove_record_hint.setWordWrap(True)
        master_layout.addWidget(self.remove_record_btn)
        master_layout.addWidget(self.remove_record_hint)
        master_layout.addWidget(self.return_live_btn)
        master_layout.addWidget(self.overlay_source_status)
        master_layout.addStretch()

        metrics_card = self.metrics_card = HeaderCardWidget(self.container)
        metrics_card.setTitle("核心数据")
        summary_row.addWidget(metrics_card, 4)
        metrics_wrapper = QWidget(metrics_card)
        metrics_card.viewLayout.addWidget(metrics_wrapper)
        metrics_grid = QGridLayout(metrics_wrapper)
        metrics_grid.setContentsMargins(0, 0, 0, 0)
        metrics_grid.setHorizontalSpacing(12)
        metrics_grid.setVerticalSpacing(12)

        total_tile, self.summary_total = self._create_metric_tile("总伤害", "0.00", metrics_wrapper)
        dps_tile, self.summary_dps = self._create_metric_tile("DPS", "0.00", metrics_wrapper)
        duration_tile, self.summary_duration = self._create_metric_tile("战斗时长", "0.00 秒", metrics_wrapper)
        players_tile, self.summary_players = self._create_metric_tile("MVP", "-", metrics_wrapper)
        metrics_grid.addWidget(total_tile, 0, 0)
        metrics_grid.addWidget(dps_tile, 0, 1)
        metrics_grid.addWidget(duration_tile, 1, 0)
        metrics_grid.addWidget(players_tile, 1, 1)

        ranking_card = self.ranking_card = HeaderCardWidget(self.container)
        ranking_card.setTitle("伤害统计")
        summary_row.addWidget(ranking_card, 6)
        ranking_wrapper = QWidget(ranking_card)
        ranking_card.viewLayout.addWidget(ranking_wrapper)
        ranking_layout = QVBoxLayout(ranking_wrapper)
        ranking_layout.setContentsMargins(12, 12, 12, 12)
        ranking_layout.setSpacing(10)
        self.table_shell = QFrame(ranking_wrapper)
        self.table_shell.setObjectName("rankingTableShell")
        table_shell_layout = QVBoxLayout(self.table_shell)
        table_shell_layout.setContentsMargins(0, 0, 0, 0)
        table_shell_layout.setSpacing(0)
        self.table = TableWidget(self.table_shell)
        self.table.setMinimumSize(400, 260)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["排名", "角色", "总伤害", "占比", "暴击率", "最大伤害"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(self.table.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(self.table.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        table_shell_layout.addWidget(self.table, 1)
        ranking_layout.addWidget(self.table_shell, 1)

    def _create_metric_tile(self, title: str, value: str, parent: QWidget) -> tuple[QFrame, StrongBodyLabel]:
        frame = QFrame(parent)
        frame.setObjectName("battleMetricTile")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        title_label = CaptionLabel(title, frame)
        value_label = StrongBodyLabel(value, frame)
        setFont(value_label, 22, QFont.Weight.DemiBold)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addStretch()
        return frame, value_label

    def set_records(self, records: list[CombatRecord]) -> None:
        self.record_count.setText(f"共 {len(records)} 条")
        selected_key = None
        current = self.record_list.currentItem()
        selected_keys = [item.data(Qt.ItemDataRole.UserRole) for item in self.record_list.selectedItems()]
        if current is not None:
            selected_key = current.data(Qt.ItemDataRole.UserRole)
        self.record_list.blockSignals(True)
        self.record_list.clear()
        for record in records:
            item_text = (
                f"{record_label(record)}\n"
                + (f"伤害 {record.total_damage:.2f}  DPS {record.dps:.2f}  时长 {_format_duration(record.duration_ms)}"
                   if record.analysis_loaded else "待加载 · 点击加载后分析所选战斗")
            )
            self.record_list.addItem(item_text)
            item = self.record_list.item(self.record_list.count() - 1)
            item.setData(Qt.ItemDataRole.UserRole, (str(record.file_path), record.record_index))
            item.setToolTip(f"{record.label}\n{record.file_path.name}")
            item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selected_keys)
            if item.data(Qt.ItemDataRole.UserRole) == selected_key:
                self.record_list.setCurrentItem(item, QItemSelectionModel.SelectionFlag.NoUpdate)
        if self.record_list.currentItem() is None and self.record_list.count() > 0:
            self.record_list.setCurrentRow(0)
        self.record_list.blockSignals(False)
        self.record_list.updateSelectedRows()

    def show_record(self, record: CombatRecord | None) -> None:
        if record is None:
            self.summary_total.setText("0.00")
            self.summary_dps.setText("0.00")
            self.summary_duration.setText("0.00 秒")
            self.summary_players.setText("-")
            self.table.setRowCount(0)
            return

        started_at = datetime.fromtimestamp(record.started_at_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
        self.summary_total.setText(f"{record.total_damage:.2f}" if record.analysis_loaded else "待加载")
        self.summary_dps.setText(f"{record.dps:.2f}" if record.analysis_loaded else "待加载")
        self.summary_duration.setText(_format_duration(record.duration_ms) if record.analysis_loaded else "待加载")
        self.summary_players.setText(
            max(record.players, key=lambda player: player.total_damage).display_name if record.players else "-"
        )
        self.table.setRowCount(len(record.players))
        for row, player in enumerate(record.players):
            percent = 0.0 if record.total_damage <= 0 else (player.total_damage / record.total_damage) * 100.0
            values = [
                str(row + 1),
                player.display_name,
                f"{player.total_damage:.2f}",
                f"{percent:.2f}%",
                f"{player.crit_rate:.2f}%",
                f"{player.max_damage:.2f}",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)

