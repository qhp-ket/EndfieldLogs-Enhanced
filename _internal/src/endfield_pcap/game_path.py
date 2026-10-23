from __future__ import annotations

from pathlib import Path


GAME_EXE_NAME = "Endfield.exe"
GAME_DLL_NAME = "GameAssembly.dll"
LAUNCHER_DIR_NAME = "Hypergryph Launcher"
GAME_DIR_FROM_LAUNCHER = Path("games") / "Endfield Game"


def is_valid_game_dir(path: Path | str | None) -> bool:
    if path is None:
        return False
    target = Path(path)
    return (target / GAME_EXE_NAME).exists() and (target / GAME_DLL_NAME).exists()


def normalize_game_dir_selection(raw_path: str | Path | None) -> Path | None:
    if raw_path is None or str(raw_path).strip() == "":
        return None
    try:
        target = Path(raw_path).expanduser().resolve()
    except OSError:
        return None
    if target.is_file():
        target = target.parent
    for candidate in _game_dir_candidates_from_selection(target):
        if is_valid_game_dir(candidate):
            return candidate.resolve()
    return target


def _game_dir_candidates_from_selection(target: Path) -> list[Path]:
    return [
        target,
        target / GAME_DIR_FROM_LAUNCHER,
        target / "Endfield Game",
    ]


def _iter_drive_roots() -> list[Path]:
    roots: list[Path] = []
    for drive_ord in range(ord("C"), ord("Z") + 1):
        root = Path(f"{chr(drive_ord)}:/")
        if root.exists():
            roots.append(root)
    return roots


def _preferred_launcher_start_dir(fallback: Path | None = None) -> Path:
    if fallback is not None:
        try:
            resolved_fallback = fallback.resolve()
        except OSError:
            resolved_fallback = fallback
        if resolved_fallback.exists():
            if resolved_fallback.is_file():
                return resolved_fallback.parent
            if resolved_fallback.name == "Endfield Game" and resolved_fallback.parent.name == "games":
                launcher_dir = resolved_fallback.parent.parent
                if launcher_dir.exists():
                    return launcher_dir
            return resolved_fallback

    for root in _iter_drive_roots():
        for candidate in (
            root / LAUNCHER_DIR_NAME,
            root / "shi" / LAUNCHER_DIR_NAME,
        ):
            if candidate.exists():
                return candidate.resolve()
    return Path.cwd().resolve()


def prompt_for_game_dir_tk(start_dir: Path | None = None) -> Path | None:
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    try:
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass

        current_dir = str(_preferred_launcher_start_dir(start_dir))
        while True:
            messagebox.showinfo(
                "首次设置游戏路径",
                "请选择 Hypergryph Launcher 目录、Endfield Game 目录或 Endfield.exe。\n\n"
                "客户端会保存这个路径，后续启动不会自动扫描磁盘。",
                parent=root,
            )
            select_exe = messagebox.askyesnocancel(
                "选择方式",
                "选择 Endfield.exe 吗？\n\n是：选择 Endfield.exe\n否：选择 Hypergryph Launcher 或游戏目录\n取消：退出",
                parent=root,
            )
            if select_exe is None:
                return None
            if select_exe:
                selected = filedialog.askopenfilename(
                    title="选择 Endfield.exe",
                    initialdir=current_dir,
                    filetypes=[("Endfield.exe", "Endfield.exe"), ("Executable Files", "*.exe"), ("All Files", "*.*")],
                    parent=root,
                )
            else:
                selected = filedialog.askdirectory(
                    title="选择 Hypergryph Launcher 或 Endfield Game 目录",
                    initialdir=current_dir,
                    parent=root,
                )
            candidate = normalize_game_dir_selection(selected)
            if candidate is None:
                continue
            current_dir = str(candidate)
            if is_valid_game_dir(candidate):
                return candidate
            messagebox.showwarning(
                "目录无效",
                "所选位置没有找到 Hypergryph Launcher\\games\\Endfield Game，"
                "也没有同时找到 Endfield.exe 和 GameAssembly.dll，请重新选择。",
                parent=root,
            )
    finally:
        root.destroy()


def ensure_configured_game_dir_interactive(config_path: Path | None = None) -> Path | None:
    from .gui_config import load_app_config, save_app_config

    app_config = load_app_config(config_path)
    if is_valid_game_dir(app_config.service.dll_dir):
        return app_config.service.dll_dir.resolve()

    selected = prompt_for_game_dir_tk(app_config.service.dll_dir)
    if selected is None:
        return None

    app_config.service.dll_dir = selected
    app_config.service.game_exe = GAME_EXE_NAME
    save_app_config(app_config, config_path)
    return selected
