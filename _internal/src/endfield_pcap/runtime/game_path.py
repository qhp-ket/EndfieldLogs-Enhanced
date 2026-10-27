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
