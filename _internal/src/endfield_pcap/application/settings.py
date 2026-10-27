"""Own persisted settings and expose explicit battle display preferences."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import threading

from endfield_pcap.analysis.battle.lane_config import normalize_lane_configs
from endfield_pcap.settings import AppConfig, save_app_config


@dataclass(frozen=True, slots=True)
class BattleDisplaySettings:
    show_character_avatars: bool = True
    character_avatar_percent: int = 100
    gui_font_percent: int = 115
    battle_lane_configs: dict = field(default_factory=dict)
    battle_table_widths: dict = field(default_factory=dict)


class SettingsStore:
    def __init__(self, config: AppConfig, path: Path):
        self.current = config
        self.path = Path(path)
        self._owner = threading.get_ident()

    def _assert_owner(self):
        if threading.get_ident() != self._owner:
            raise RuntimeError('设置只能在所属线程提交')

    def save(self):
        self._assert_owner()
        save_app_config(self.current, self.path)

    def battle_display(self):
        config = self.current
        return BattleDisplaySettings(config.show_character_avatars,
            config.character_avatar_percent, config.gui_font_percent,
            deepcopy(config.battle_lane_configs), deepcopy(config.battle_table_widths))

    def set_character_avatars(self, visible):
        self._assert_owner()
        self.current.show_character_avatars = bool(visible)
        self.save()

    def set_avatar_percent(self, percent):
        self._assert_owner()
        self.current.character_avatar_percent = max(50, min(300, int(percent)))
        self.save()

    def set_character_lanes(self, owner, rows):
        self._assert_owner()
        # Merge a single character, so another open report keeps its preferences.
        values = normalize_lane_configs({owner: rows})
        if owner in values:
            self.current.battle_lane_configs[owner] = values[owner]
            self.save()

    def set_table_widths(self, key, widths):
        self._assert_owner()
        self.current.battle_table_widths[key] = list(widths)
        self.save()

    def set_input_binding(self, key, value):
        self._assert_owner()
        self.current.input_log_bindings[key] = deepcopy(value)
        self.save()

    def set_input_settings(self, value):
        self._assert_owner()
        self.current.input_settings = deepcopy(value)
        self.save()

    def set_input_recording_enabled(self, enabled):
        self._assert_owner()
        self.current.input_recording_enabled = bool(enabled)
        self.save()

    def set_vision_settings(self, value):
        self._assert_owner()
        self.current.vision_settings = deepcopy(value)
        self.save()
