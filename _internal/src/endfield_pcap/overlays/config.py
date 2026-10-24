from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from endfield_pcap.overlays.templates import ASSETS, BUILTIN_DIRECTORIES, template_for
from endfield_pcap.runtime.paths import bundle_root


@dataclass(slots=True)
class OverlayWindowConfig:
    entry: OverlayEntry
    ws_port: int
    min_width: int = 640
    min_height: int = 320
    default_width: int = 980
    default_height: int = 492
    margin_top: int = 56
    margin_right: int = 56
    resize_margin: int = 10
    on_geometry_changed: Callable[[str, OverlayGeometry], None] | None = None
    on_closed: Callable[[str], None] | None = None
    use_in_process_snapshots: bool = False
    desktop_visible: bool = True
    hide_on_close: bool = False
    ws_browser_token: str = ''


def _window_defaults(entry: OverlayEntry) -> dict[str, int]:
    template = template_for(entry)
    if template.window:
        return {"min_width": 100, "min_height": 40, "default_width": 700, "default_height": 350, **template.window}
    builtin_key = (entry.source_value or "damage").strip().lower()
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key == "uid_mask":
        return {
            "min_width": 100,
            "min_height": 20,
            "default_width": 100,
            "default_height": 20,
        }
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key in {"combo_skill", "buff"}:
        return {
            "min_width": 180,
            "min_height": 1,
            "default_width": 300,
            "default_height": 200,
        }
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key == "damage":
        return {
            "min_width": 320,
            "min_height": 160,
            "default_width": 800,
            "default_height": 380,
        }
    return {
        "min_width": 100,
        "min_height": 40,
        "default_width": 700,
        "default_height": 350,
    }


def _builtin_overlay_index(source_value: str) -> Path:
    package_asset_dir = ASSETS
    repo_root = bundle_root()
    builtin_key = (source_value or "damage").strip().lower()
    if builtin_key == "damage":
        # This renderer consumes the versioned canonical snapshot contract.
        return package_asset_dir / "damage/index.html"
    if builtin_key == "combo_skill":
        return package_asset_dir / "combo/index.html"
    builtin_paths = {
        "damage": repo_root / "overlay" / "dist" / "index.html",
        "combo_skill": repo_root / "overlay_comboskill" / "dist" / "index.html",
        "buff": repo_root / "overlay_buff" / "dist" / "index.html",
        "uid_mask": repo_root / "overlay_uid" / "dist" / "index.html",
    }
    target = builtin_paths.get(builtin_key)
    if target is not None and target.exists():
        return target
    directory = BUILTIN_DIRECTORIES.get(
        builtin_key, builtin_key if builtin_key in {"buff", "uid_mask"} else "damage",
    )
    return package_asset_dir / directory / "index.html"
