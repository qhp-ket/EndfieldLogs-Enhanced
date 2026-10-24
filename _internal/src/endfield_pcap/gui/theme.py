from __future__ import annotations

from qfluentwidgets import Theme, isDarkTheme, setTheme
from PySide6.QtWidgets import QFrame


def _theme_from_mode(mode: str) -> Theme:
    normalized = str(mode or "system").strip().lower()
    if normalized == "light":
        return Theme.LIGHT
    if normalized == "dark":
        return Theme.DARK
    return Theme.AUTO


class WindowTheme:
    def _apply_gui_theme(self, mode: str | None = None) -> None:
        setTheme(_theme_from_mode(mode or self.app_config.theme_mode))
        self.setCustomBackgroundColor("#f3f3f3", "#202020")
        dark = isDarkTheme()
        page_qss = "background: transparent;"
        label_color = "#f5f5f5" if dark else "#202020"
        subtle_label_color = "#d0d0d0" if dark else "#606060"
        text_edit_qss = (
            "QPlainTextEdit { background: rgba(18, 18, 18, 0.94); color: #f5f5f5; border-radius: 8px; }"
            if dark
            else "QPlainTextEdit { background: rgba(255, 255, 255, 0.94); color: #202020; border-radius: 8px; }"
        )
        table_qss = (
            "QTableView { background: transparent; alternate-background-color: rgba(255,255,255,0.04); color: #f5f5f5; gridline-color: rgba(255,255,255,0.08); "
            "border: none; border-radius: 12px; selection-background-color: rgba(255,255,255,0.12); selection-color: #ffffff; } "
            "QHeaderView { background: transparent; } "
            "QHeaderView::section { background: rgba(42, 42, 42, 0.96); color: #f5f5f5; border: none; "
            "border-bottom: 1px solid rgba(255,255,255,0.08); padding: 6px 8px; } "
            "QHeaderView::section:first { border-top-left-radius: 12px; } "
            "QHeaderView::section:last { border-top-right-radius: 12px; } "
            "QTableCornerButton::section { background: rgba(42, 42, 42, 0.96); border: none; border-top-left-radius: 12px; }"
            if dark
            else "QTableView { background: transparent; alternate-background-color: rgba(0,0,0,0.03); color: #202020; gridline-color: rgba(0,0,0,0.08); "
            "border: none; border-radius: 12px; selection-background-color: rgba(0,0,0,0.08); selection-color: #202020; } "
            "QHeaderView { background: transparent; } "
            "QHeaderView::section { background: rgba(245, 245, 245, 0.96); color: #202020; border: none; "
            "border-bottom: 1px solid rgba(0,0,0,0.08); padding: 6px 8px; } "
            "QHeaderView::section:first { border-top-left-radius: 12px; } "
            "QHeaderView::section:last { border-top-right-radius: 12px; } "
            "QTableCornerButton::section { background: rgba(245, 245, 245, 0.96); border: none; border-top-left-radius: 12px; }"
        )
        table_shell_qss = (
            "QFrame#rankingTableShell { background: rgba(28, 28, 28, 0.92); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; }"
            if dark
            else "QFrame#rankingTableShell { background: rgba(255, 255, 255, 0.92); border: 1px solid rgba(0,0,0,0.06); border-radius: 12px; }"
        )
        form_page_qss = (
            "QLabel { color: #f5f5f5; } "
            "QCheckBox { color: #f5f5f5; } "
            "QLineEdit, QComboBox, QKeySequenceEdit { color: #f5f5f5; background: rgba(28, 28, 28, 0.92); border-radius: 6px; }"
            if dark
            else "QLabel { color: #202020; } "
            "QCheckBox { color: #202020; } "
            "QLineEdit, QComboBox, QKeySequenceEdit { color: #202020; background: rgba(255, 255, 255, 0.92); border-radius: 6px; }"
        )
        metric_tile_qss = (
            "QFrame#battleMetricTile { background: rgba(34, 34, 34, 0.94); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; }"
            if dark
            else "QFrame#battleMetricTile { background: rgba(255, 255, 255, 0.82); border: 1px solid rgba(0, 0, 0, 0.06); border-radius: 12px; }"
        )
        for page in (self.home_page, self.overlay_page, self.records_page, self.settings_page, self.logs_page):
            page.viewport().setStyleSheet(page_qss)
            page.container.setStyleSheet(page_qss)
            page.setStyleSheet(page_qss)
        self.overlay_page.container.setStyleSheet(form_page_qss)
        self.settings_page.container.setStyleSheet(form_page_qss)
        self.records_page.container.setStyleSheet(
            f"QLabel {{ color: {label_color}; }} "
            f"QTableView {{ color: {label_color}; }} "
            f"QHeaderView::section {{ color: {label_color}; }} "
            f"QLabel[description='true'] {{ color: {subtle_label_color}; }}"
        )
        self.logs_page.log_view.setStyleSheet(text_edit_qss)
        self.records_page.table.setStyleSheet(table_qss)
        self.records_page.table_shell.setStyleSheet(table_shell_qss)
        for tile in self.records_page.findChildren(QFrame, "battleMetricTile"):
            tile.setStyleSheet(metric_tile_qss)
        self.home_page.update()
        self.overlay_page.update()
        self.records_page.update()
        self.settings_page.update()
        self.logs_page.update()
        self.update()
