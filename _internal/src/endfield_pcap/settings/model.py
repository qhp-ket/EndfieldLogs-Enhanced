"""Application configuration values, independent of product windows."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from endfield_pcap.models import OverlayEntry
from endfield_pcap.service.config import ServiceConfig


@dataclass(slots=True)
class AppConfig:
    service: ServiceConfig
    overlays: list[OverlayEntry] = field(default_factory=list)
    theme_mode: str = "system"
    gui_font_percent: int = 115
    toggle_overlays_hotkey: str = "Ctrl+O"
    toggle_gui_hotkey: str = "Ctrl+Shift+O"
    imported_trace_files: list[Path] = field(default_factory=list)
    hidden_history_records: list[str] = field(default_factory=list)
    overlay_migration_count: int = 0
    battle_table_widths: dict = field(default_factory=dict)
    battle_lane_configs: dict = field(default_factory=dict)
    overlay_restore_ids: list[str] = field(default_factory=list)
    start_capture_on_launch: bool = False
    check_updates_on_start: bool = True
    ignored_update_version: str = ''
    show_character_avatars: bool = True
    character_avatar_percent: int = 100
    input_recording_enabled: bool = False
    start_input_recording_on_launch: bool = False
    input_settings: dict = field(default_factory=dict)
    input_log_bindings: dict = field(default_factory=dict)
    vision_settings: dict = field(default_factory=dict)
