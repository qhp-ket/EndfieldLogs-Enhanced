from __future__ import annotations
from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget
from endfield_pcap.gui.config import AppConfig, save_app_config
from endfield_pcap.gui.resources import ROOT
from endfield_pcap.gui.shared.typography import apply_fonts


def _is_valid_game_dir(path: Path | None) -> bool:
    if path is None:
        return False
    target = Path(path)
    return (target / "GameAssembly.dll").is_file() and (target / "Endfield.exe").is_file()

def _normalize_game_dir_selection(raw_path: str) -> Path | None:
    if not raw_path:
        return None
    try:
        target = Path(raw_path).expanduser().resolve()
    except OSError:
        return None
    if target.is_file():
        target = target.parent
    return target

def _select_game_directory_from_dialog(parent: QWidget | None, start_dir: Path, *, select_exe: bool) -> Path | None:
    if select_exe:
        selected, _ = QFileDialog.getOpenFileName(
            parent,
            "选择 Endfield.exe",
            str(start_dir),
            "Endfield.exe (Endfield.exe);;Executable Files (*.exe);;All Files (*)",
        )
        if selected and Path(selected).name.lower() != "endfield.exe":
            QMessageBox.warning(parent, "文件无效", "请选择游戏本体 Endfield.exe。")
            return None
    else:
        selected = QFileDialog.getExistingDirectory(parent, "选择 Endfield Game 目录", str(start_dir))
    return _normalize_game_dir_selection(selected)

def _run_game_directory_wizard(app_config: AppConfig, config_path: Path, parent: QWidget | None = None) -> bool:
    start_dir = app_config.service.dll_dir if app_config.service.dll_dir else ROOT
    while True:
        box = QMessageBox(parent)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("未找到终末地，请指定游戏路径")
        box.setText("没有在当前路径找到游戏，请手动选择 Endfield Game 目录或 Endfield.exe。")
        box.setInformativeText(
            f"当前路径：{start_dir}\n选择后会保存；也可以暂不设置，继续使用历史分析，稍后在设置中修改。")
        exe_button = box.addButton("选择 Endfield.exe", QMessageBox.ButtonRole.AcceptRole)
        dir_button = box.addButton("选择游戏目录", QMessageBox.ButtonRole.ActionRole)
        cancel_button = box.addButton("暂不设置", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(exe_button)
        box.setEscapeButton(cancel_button)
        # Size the modal using its final fonts, before QMessageBox fixes its
        # layout. The main window's deferred typography pass is otherwise late.
        typography = getattr(parent, 'gui_typography', None)
        if typography is not None:
            apply_fonts(box, typography.scale)
        box.exec()

        clicked = box.clickedButton()
        if clicked not in (exe_button, dir_button):
            return False

        selected_dir = _select_game_directory_from_dialog(
            parent,
            start_dir,
            select_exe=clicked == exe_button,
        )
        if selected_dir is None:
            continue
        start_dir = selected_dir
        if not _is_valid_game_dir(selected_dir):
            QMessageBox.warning(
                parent,
                "目录无效",
                "所选位置没有同时找到 Endfield.exe 和 GameAssembly.dll，请重新选择游戏根目录。",
            )
            continue

        app_config.service.dll_dir = selected_dir
        app_config.service.game_exe = "Endfield.exe"
        save_app_config(app_config, config_path)
        return True
