from __future__ import annotations
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from endfield_pcap.models import OverlayEntry, OverlayGeometry, OverlaySourceType
from endfield_pcap.runtime.paths import app_root, bundle_root
from endfield_pcap.service.config import ServiceConfig


_LEGACY_BUILTIN_NAMES = {
    "",
    "悬浮窗",
    "内置悬浮窗",
    "伤害统计",
}
_BUILTIN_DAMAGE_NAME = "伤害统计"
_BUILTIN_COMBO_NAME = "连携cd监控"
_BUILTIN_UID_MASK_NAME = "UID遮挡"


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
    battle_analysis_view: str = 'native'
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


def default_config_path() -> Path:
    appdata_root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".endfield-pcap")
    return appdata_root / "EndfieldPCAP" / "settings.json"


def _legacy_config_paths() -> list[Path]:
    return [app_root() / "endfield_pcap.gui.json"]


def default_service_config() -> ServiceConfig:
    bundle = bundle_root()
    app = app_root()
    return ServiceConfig(
        ws_port=29325,
        log_dir=(app / "logs").resolve(),
        log_level="INFO",
        game_exe="Endfield.exe",
        npcap_device="auto",
        dll_dir=Path(r"C:\Program Files\Hypergryph Launcher\games\Endfield Game"),
        debug_enabled=False,
        debug_dir=(app / "debug").resolve(),
        rsa_key_txt=(app / "secrets" / "client_privkey.pem").resolve(),
        name_index_path=(bundle / "jsondata" / "CharacterNameIndex.json").resolve(),
        merge_multi_phase_enemy_battles=False,
    )


def default_overlay_entries() -> list[OverlayEntry]:
    return [
        OverlayEntry(
            id=str(uuid.uuid4()),
            name=_BUILTIN_DAMAGE_NAME,
            source_type=OverlaySourceType.BUILTIN,
            source_value="damage",
            enabled=True,
            locked=False,
            click_through=False,
            opacity=1.0,
            scale=1.0,
            geometry=None,
        ),
        _optional_overlay('combo_skill','连携 CD（图像识别）'),
        OverlayEntry(
            id=str(uuid.uuid4()),
            name=_BUILTIN_UID_MASK_NAME,
            source_type=OverlaySourceType.BUILTIN,
            source_value="uid_mask",
            enabled=True,
            locked=False,
            click_through=False,
            opacity=1.0,
            scale=1.0,
            geometry=None,
        ),
    ]


def load_app_config(path: Path | None = None) -> AppConfig:
    target = path or default_config_path()
    if not target.exists():
        for legacy_path in _legacy_config_paths():
            if legacy_path.exists():
                return load_app_config(legacy_path)
        return AppConfig(service=default_service_config(), overlays=_ensure_builtin_entries(default_overlay_entries()))
    payload = json.loads(target.read_text(encoding="utf-8"))
    service_default = default_service_config()
    service_payload = payload.get("service", {})
    overlays_payload = payload.get("overlays", [])
    imported_paths = payload.get("imported_trace_files")
    if not isinstance(imported_paths, list):
        imported_paths = []
    config = AppConfig(
        service=ServiceConfig(
            ws_port=int(service_payload.get("ws_port", service_default.ws_port)),
            ws_browser_token=(service_payload['ws_browser_token']
                if isinstance(service_payload.get('ws_browser_token'), str)
                and re.fullmatch(r'[A-Za-z0-9_-]{43,128}', service_payload['ws_browser_token'])
                else service_default.ws_browser_token),
            log_dir=Path(service_payload.get("log_dir", str(service_default.log_dir))).resolve(),
            log_level=str(service_payload.get("log_level", service_default.log_level)),
            game_exe=str(service_payload.get("game_exe", service_default.game_exe)),
            npcap_device=str(service_payload.get("npcap_device", service_default.npcap_device)),
            dll_dir=Path(service_payload.get("dll_dir", str(service_default.dll_dir))).resolve(),
            debug_enabled=bool(service_payload.get("debug_enabled", service_default.debug_enabled)),
            debug_dir=Path(service_payload.get("debug_dir", str(service_default.debug_dir))).resolve(),
            rsa_key_txt=Path(service_payload.get("rsa_key_txt", str(service_default.rsa_key_txt))).resolve(),
            name_index_path=Path(service_payload.get("name_index_path", str(service_default.name_index_path))).resolve(),
            merge_multi_phase_enemy_battles=bool(
                service_payload.get(
                    "merge_multi_phase_enemy_battles",
                    service_default.merge_multi_phase_enemy_battles,
                )
            ),
        ),
        overlays=[_overlay_entry_from_dict(item) for item in overlays_payload] or default_overlay_entries(),
        theme_mode=_normalize_theme_mode(payload.get("theme_mode")),
        gui_font_percent=_normalize_font_percent(payload.get('gui_font_percent', 115)),
        start_capture_on_launch=payload.get('start_capture_on_launch') is True,
        check_updates_on_start=payload.get('check_updates_on_start', True) is True,
        ignored_update_version=str(payload.get('ignored_update_version') or ''),
        show_character_avatars=payload.get('show_character_avatars', True) is True,
        character_avatar_percent=_normalize_avatar_percent(payload.get('character_avatar_percent', 100)),
        start_input_recording_on_launch=payload.get('start_input_recording_on_launch') is True,
        input_settings=payload.get('input_settings') if isinstance(payload.get('input_settings'),dict) else {},
        input_log_bindings=payload.get('input_log_bindings') if isinstance(payload.get('input_log_bindings'),dict) else {},
        vision_settings=payload.get('vision_settings') if isinstance(payload.get('vision_settings'),dict) else {},
        battle_analysis_view='web' if payload.get('battle_analysis_view') == 'web' else 'native',
        toggle_overlays_hotkey=_normalize_hotkey(payload.get("toggle_overlays_hotkey")),
        toggle_gui_hotkey=str(payload.get('toggle_gui_hotkey') or 'Ctrl+Shift+O'),
        imported_trace_files=list(dict.fromkeys(Path(value).resolve() for value in imported_paths
            if isinstance(value, str) and value.strip())),
        hidden_history_records=[value for value in payload.get('hidden_history_records', []) if isinstance(value, str)]
            if isinstance(payload.get('hidden_history_records', []), list) else [],
    )
    if getattr(sys, "frozen", False):
        app = app_root().resolve()
        bundle = bundle_root().resolve()
        if not config.service.log_dir.exists():
            config.service.log_dir = (app / "logs").resolve()
        if not config.service.debug_dir.exists():
            config.service.debug_dir = (app / "debug").resolve()
        if not config.service.rsa_key_txt.exists():
            config.service.rsa_key_txt = (app / "secrets" / "client_privkey.pem").resolve()
        if not config.service.name_index_path.exists():
            config.service.name_index_path = (bundle / "jsondata" / "CharacterNameIndex.json").resolve()
    config.overlays = _ensure_builtin_entries(config.overlays)
    valid_ids = {entry.id for entry in config.overlays}
    restore_ids = payload.get('overlay_restore_ids', [])
    if isinstance(restore_ids, list):
        config.overlay_restore_ids = list(dict.fromkeys(
            value for value in restore_ids if isinstance(value, str) and value in valid_ids))
    # Read the former global visibility gate once; new saves use per-entry state.
    if 'overlay_restore_ids' not in payload and payload.get('overlays_visible') is False:
        config.overlay_restore_ids = [entry.id for entry in config.overlays if not entry.hidden]
        config.overlays = [replace(entry, hidden=True) for entry in config.overlays]
    return config


def save_app_config(config: AppConfig, path: Path | None = None) -> None:
    target = path or default_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "service": {
                    "ws_port": config.service.ws_port,
                    "ws_browser_token": config.service.ws_browser_token,
                    "log_dir": str(config.service.log_dir),
                    "log_level": config.service.log_level,
                    "game_exe": config.service.game_exe,
                    "npcap_device": config.service.npcap_device,
                    "dll_dir": str(config.service.dll_dir),
                    "debug_enabled": config.service.debug_enabled,
                    "debug_dir": str(config.service.debug_dir),
                    "rsa_key_txt": str(config.service.rsa_key_txt),
                    "name_index_path": str(config.service.name_index_path),
                    "merge_multi_phase_enemy_battles": config.service.merge_multi_phase_enemy_battles,
                },
                "overlays": [_overlay_entry_to_dict(entry) for entry in config.overlays],
                'overlay_restore_ids': config.overlay_restore_ids,
                "theme_mode": _normalize_theme_mode(config.theme_mode),
                "gui_font_percent": _normalize_font_percent(config.gui_font_percent),
                "start_capture_on_launch": config.start_capture_on_launch,
                "check_updates_on_start": config.check_updates_on_start,
                "ignored_update_version": config.ignored_update_version,
                "show_character_avatars": config.show_character_avatars,
                "character_avatar_percent": _normalize_avatar_percent(config.character_avatar_percent),
                "start_input_recording_on_launch": config.start_input_recording_on_launch,
                "input_settings": config.input_settings,
                "input_log_bindings": config.input_log_bindings,
                "vision_settings": config.vision_settings,
                "battle_analysis_view": 'web' if config.battle_analysis_view == 'web' else 'native',
                "toggle_overlays_hotkey": _normalize_hotkey(config.toggle_overlays_hotkey),
                "toggle_gui_hotkey": config.toggle_gui_hotkey,
                "imported_trace_files": [str(path) for path in config.imported_trace_files],
                "hidden_history_records": config.hidden_history_records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _overlay_entry_from_dict(payload: dict[str, object]) -> OverlayEntry:
    geometry_payload = payload.get("geometry")
    geometry = None
    if isinstance(geometry_payload, dict):
        geometry = OverlayGeometry(
            x=int(geometry_payload.get("x", 0)),
            y=int(geometry_payload.get("y", 0)),
            width=int(geometry_payload.get("width", 980)),
            height=int(geometry_payload.get("height", 492)),
        )

    source_type = OverlaySourceType(str(payload.get("source_type", OverlaySourceType.BUILTIN.value)))
    source_value = str(payload.get("source_value") or "").strip()
    raw_name = str(payload.get("name") or "").strip()

    if source_type == OverlaySourceType.BUILTIN and not source_value:
        source_value = "damage"

    if source_type == OverlaySourceType.BUILTIN and source_value == "damage":
        name = _BUILTIN_DAMAGE_NAME if raw_name in _LEGACY_BUILTIN_NAMES else (raw_name or _BUILTIN_DAMAGE_NAME)
    elif source_type == OverlaySourceType.BUILTIN and source_value == "combo_skill":
        name = raw_name or _BUILTIN_COMBO_NAME
    elif source_type == OverlaySourceType.BUILTIN and source_value == "buff":
        name = raw_name or "BUFF"
    elif source_type == OverlaySourceType.BUILTIN and source_value == "uid_mask":
        name = raw_name or _BUILTIN_UID_MASK_NAME
    else:
        name = raw_name or "悬浮窗"

    return OverlayEntry(
        id=str(payload.get("id") or uuid.uuid4()),
        name=name,
        source_type=source_type,
        source_value=source_value,
        enabled=bool(payload.get("enabled", True)),
        hidden=bool(payload.get("hidden", False)),
        locked=bool(payload.get("locked", False)),
        click_through=bool(payload.get("click_through", False)),
        opacity=max(0.1, min(1.0, float(payload.get("opacity", 1.0) or 1.0))),
        scale=max(0.5, min(3.0, float(payload.get("scale", 1.0) or 1.0))),
        geometry=geometry,
        font_scale=max(0.5, min(3.0, float(payload.get("font_scale", payload.get("scale", 1.0)) or 1.0))),
        template_settings=payload.get("template_settings", {}) if isinstance(payload.get("template_settings"), dict) else {},
        bar_mode="rdps" if payload.get("bar_mode") == "rdps" else "dps",
        visible_columns=tuple(key for key in ("damage", "damage_rate", "rdamage", "rdamage_rate")
                              if key in payload.get("visible_columns", ("damage", "damage_rate", "rdamage", "rdamage_rate")))
        if isinstance(payload.get("visible_columns", []), (list, tuple)) else ("damage", "damage_rate", "rdamage", "rdamage_rate"),
        overlay_theme=payload.get("overlay_theme") if payload.get("overlay_theme") in ("dark", "transparent") else "light",
    )


def _ensure_builtin_entries(entries: list[OverlayEntry]) -> list[OverlayEntry]:
    normalized: list[OverlayEntry] = []
    damage_present = False
    uid_mask_present = False
    combo_present = False
    for entry in entries:
        if entry.source_type != OverlaySourceType.BUILTIN:
            from endfield_pcap.overlays.templates import template_for
            if {'input_snapshot', 'buff_snapshot'} & set(template_for(entry).subscriptions):
                continue
            normalized.append(entry)
            continue
        source_value = (entry.source_value or "damage").strip().lower()
        if source_value == "damage":
            damage_present = True
            normalized.append(replace(entry, source_value="damage", name=_BUILTIN_DAMAGE_NAME))
            continue
        if source_value == "combo_skill":
            combo_present = True
            normalized.append(entry)
            continue
        if source_value in {"buff", "input"}:
            continue
        if source_value == "uid_mask":
            uid_mask_present = True
            normalized.append(replace(entry, source_value="uid_mask", name=entry.name or _BUILTIN_UID_MASK_NAME))
            continue
        normalized.append(entry)
    defaults = default_overlay_entries()
    if not damage_present:
        normalized.insert(0, defaults[0])
    if not uid_mask_present:
        normalized.append(defaults[-1])
    if not combo_present:
        index=next((i for i,e in enumerate(normalized) if e.source_value in ('input','uid_mask')),len(normalized))
        normalized.insert(index,_optional_overlay('combo_skill','连携 CD（图像识别）'))
    return normalized


def _optional_overlay(source, name):
    return OverlayEntry(id=str(uuid.uuid4()),name=name,source_type=OverlaySourceType.BUILTIN,
                        source_value=source,enabled=False,locked=False,click_through=False,opacity=1.,scale=1.)


def _overlay_entry_to_dict(entry: OverlayEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "name": entry.name,
        "source_type": entry.source_type.value,
        "source_value": entry.source_value,
        "enabled": entry.enabled,
        "hidden": entry.hidden,
        "locked": entry.locked,
        "click_through": entry.click_through,
        "opacity": entry.opacity,
        "scale": entry.scale,
        "font_scale": entry.font_scale,
        "template_settings": entry.template_settings,
        "bar_mode": entry.bar_mode,
        "visible_columns": list(entry.visible_columns),
        "overlay_theme": entry.overlay_theme,
        "geometry": None
        if entry.geometry is None
        else {
            "x": entry.geometry.x,
            "y": entry.geometry.y,
            "width": entry.geometry.width,
            "height": entry.geometry.height,
        },
    }


def _normalize_theme_mode(value: object) -> str:
    mode = str(value or "system").strip().lower()
    if mode in {"light", "dark", "system"}:
        return mode
    return "system"


def _normalize_hotkey(value: object) -> str:
    hotkey = str(value or "Ctrl+O").strip()
    return hotkey or "Ctrl+O"


def _normalize_font_percent(value) -> int:
    try:
        return max(80, min(180, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 115


def _normalize_avatar_percent(value) -> int:
    return max(50, min(300, value)) if type(value) is int else 100
