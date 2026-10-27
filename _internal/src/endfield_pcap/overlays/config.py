from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from endfield_pcap.overlays.templates import template_for


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
    if entry.source_type == OverlaySourceType.BUILTIN and builtin_key in {"combo_skill"}:
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
