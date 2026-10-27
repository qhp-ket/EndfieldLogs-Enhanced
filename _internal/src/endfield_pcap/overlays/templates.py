"""Local renderer declarations. No battle calculation belongs in this module."""
from __future__ import annotations
import copy
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from functools import lru_cache
import math
import re
from endfield_pcap.models import OverlayEntry, OverlaySourceType


ASSETS = Path(__file__).resolve().parent / "assets"
BUILTIN_DIRECTORIES = {"combo_skill": "combo"}
MODULE_SUBSCRIPTIONS = {'damage': ('analysis_summary',), 'combo_skill': ('combo_snapshot',), 'uid_mask': ()}
MODULE_SETTINGS = {
    'damage': {'bar_mode', 'columns', 'theme', 'show_character_avatars', 'avatar_size_percent'},
    'combo_skill': {'display_style', 'theme', 'show_character_avatars', 'avatar_size_percent'},
    'uid_mask': {'shape'},
}

MODULE_OPTIONS = {
    'bar_mode': {'dps', 'rdps'},
    'columns': {'damage', 'damage_rate', 'rdamage', 'rdamage_rate'},
    'theme': {'light', 'dark', 'transparent', 'endfield'},
    'show_character_avatars': {'on', 'off'},
    'display_style': {'circles', 'bars'},
    'shape': {'rectangle', 'rounded'},
}


def valid_module_value(key, value):
    if key == 'avatar_size_percent':
        return type(value) is int and 50 <= value <= 300
    if key == 'columns':
        return isinstance(value, list) and all(isinstance(v, str) and v in MODULE_OPTIONS[key] for v in value)
    return isinstance(value, str) and value in MODULE_OPTIONS[key]


@dataclass(slots=True)
class OverlayTemplate:
    path: Path | None = None
    name: str = "原生皮肤"
    subscriptions: tuple[str, ...] = ()
    settings: list[dict] = field(default_factory=list)
    window: dict[str, int] = field(default_factory=dict)
    modules: list[dict] = field(default_factory=list)
    layout: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)
    error: str = ""


def read_template(path: Path) -> OverlayTemplate:
    path = Path(path).resolve()
    stat = path.stat()
    if stat.st_size > 1024*1024:
        raise ValueError('皮肤文件上限为 1 MiB')
    return copy.deepcopy(_read_template(str(path), stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=128)
def _read_template(filename, mtime, size):
    path = Path(filename)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get('schema_version') != 2:
        raise ValueError('原生皮肤 schema_version 必须为 2')
    if set(data)-{'schema_version', 'name', 'window', 'settings', 'modules', 'layout', 'theme'}:
        raise ValueError('皮肤包含未支持的字段')
    settings = data.get("settings", [])
    keys = set()
    if not isinstance(settings, list) or len(settings) > 64:
        raise ValueError("模板 settings 必须为数组")
    for item in settings:
        if not isinstance(item, dict):
            raise ValueError('皮肤设置必须为对象')
        key = item.get("key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("模板设置 key 不能为空或重复")
        keys.add(key)
        if item.get("type") not in {"select", "multiselect", "slider"}:
            raise ValueError("模板设置类型仅支持 select / multiselect / slider")
        if item["type"] == "slider":
            if (any(type(item.get(k)) is not int for k in ("min", "max", "default"))
                    or not -16384 <= item["min"] <= item["default"] <= item["max"] <= 16384
                    or item.get("legacy_field") is not None):
                raise ValueError("模板滑条需要有效的整数 min / max / default，不能绑定 legacy_field")
            continue
        options = item.get("options", [])
        values = [o["value"] for o in options]
        if not values or any(not isinstance(v, str) for v in values) or len(set(values)) != len(values):
            raise ValueError("模板选项 value 必须为不重复的字符串")
        default = item.get("default")
        if item["type"] == "select" and default not in values:
            raise ValueError("模板默认值不在选项内")
        if item["type"] == "multiselect" and (not isinstance(default, list) or any(v not in values for v in default)):
            raise ValueError("模板多选默认值不在选项内")
        if item.get("legacy_field") not in {None, "bar_mode", "visible_columns", "overlay_theme"}:
            raise ValueError("未知 legacy_field")
    window = data.get("window", {})
    if not isinstance(window, dict) or any(k not in {"min_width", "min_height", "default_width", "default_height"}
           or not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 16384 for k, v in window.items()):
        raise ValueError("模板窗口尺寸无效")
    modules = data.get('modules')
    if not isinstance(modules, list) or not 1 <= len(modules) <= 16:
        raise ValueError('皮肤需要 1–16 个原生模块')
    subscriptions = set()
    for module in modules:
        if not isinstance(module, dict) or module.get('type') not in MODULE_SUBSCRIPTIONS:
            raise ValueError('模块仅支持 damage / combo_skill / uid_mask')
        if set(module)-{'type', 'settings', 'setting_bindings'}:
            raise ValueError('模块包含未支持的字段')
        for field in ('settings', 'setting_bindings'):
            values = module.get(field, {})
            if not isinstance(values, dict) or set(values)-MODULE_SETTINGS[module['type']]:
                raise ValueError('模块设置无效')
            if field == 'settings' and any(not valid_module_value(k, v) for k, v in values.items()):
                raise ValueError('模块设置值无效')
            if field == 'setting_bindings' and any(not isinstance(value, str) or value not in keys for value in values.values()):
                raise ValueError('模块绑定必须引用已声明的设置')
        declarations = {item['key']: item for item in settings}
        bindings = {key: key for key in MODULE_SETTINGS[module['type']] if key in declarations}
        bindings.update(module.get('setting_bindings', {}))
        for key, target in bindings.items():
            item = declarations[target]
            expected = 'slider' if key == 'avatar_size_percent' else 'multiselect' if key == 'columns' else 'select'
            if item['type'] != expected or not valid_module_value(key, item['default']):
                raise ValueError('模块绑定与设置类型或默认值不匹配')
            if expected == 'slider':
                valid = 50 <= item['min'] <= item['max'] <= 300
            else:
                valid = all(option['value'] in MODULE_OPTIONS[key] for option in item['options'])
            if not valid:
                raise ValueError('模块绑定的选项或范围无效')
        subscriptions.update(MODULE_SUBSCRIPTIONS[module['type']])
    layout = data.get('layout', {})
    if (not isinstance(layout, dict) or set(layout)-{'direction'}
            or layout.get('direction', 'single') not in {'single', 'horizontal', 'vertical'}
            or len(modules) > 1 and layout.get('direction', 'single') == 'single'):
        raise ValueError('布局应为 single / horizontal / vertical；多个模块需要排列方向')
    theme = data.get('theme', {})
    if not isinstance(theme, dict) or set(theme)-{'font_family', 'background', 'foreground', 'muted',
            'accent', 'ready', 'border', 'radius', 'spacing', 'padding', 'border_width', 'image'}:
        raise ValueError('主题参数无效')
    for key, value in theme.items():
        if key in {'radius', 'spacing', 'padding', 'border_width'}:
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 128:
                raise ValueError('主题尺寸参数必须为 0–128 的有限数值')
        elif key == 'image':
            if not isinstance(value, str) or Path(value).is_absolute():
                raise ValueError('主题图片必须使用皮肤目录内的相对路径')
            image = (path.parent/value).resolve()
            if not image.is_relative_to(path.parent) or not image.is_file() or image.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}:
                raise ValueError('主题图片不存在或格式无效')
        elif key == 'font_family':
            if not isinstance(value, str) or len(value) > 120:
                raise ValueError('主题字体名称无效')
        elif not isinstance(value, str) or not re.fullmatch(r'#[\da-fA-F]{6}(?:[\da-fA-F]{2})?|transparent', value):
            raise ValueError('主题颜色使用 #RRGGBB / #AARRGGBB / transparent')
    return OverlayTemplate(path=path, name=str(data.get('name', path.stem))[:160],
        subscriptions=tuple(sorted(subscriptions)), settings=settings, window=window,
        modules=modules, layout=layout, theme=theme)


def template_for(entry: OverlayEntry) -> OverlayTemplate:
    path = None
    if entry.source_type == OverlaySourceType.BUILTIN:
        path = ASSETS / BUILTIN_DIRECTORIES.get(entry.source_value, entry.source_value) / "template.json"
    elif entry.source_type == OverlaySourceType.FILE:
        source = Path(entry.source_value)
        if source.suffix.lower() == ".json":
            path = source
    if path is None:
        return OverlayTemplate(error='仅支持内置浮窗或 v2 JSON 原生皮肤')
    try:
        return read_template(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return OverlayTemplate(path=path, error=f"模板读取失败：{exc}")


def template_values(entry: OverlayEntry, template: OverlayTemplate | None = None) -> dict[str, object]:
    template = template or template_for(entry)
    result = {}
    for item in template.settings:
        legacy = getattr(entry, item.get("legacy_field") or "", item["default"])
        value = entry.template_settings.get(item["key"], legacy)
        if item["type"] == "slider":
            value = max(item["min"], min(item["max"], value)) if type(value) is int else item["default"]
            result[item["key"]] = value
            continue
        allowed = [option["value"] for option in item["options"]]
        if item["type"] == "multiselect":
            value = [v for v in allowed if v in value] if isinstance(value, (list, tuple)) else item["default"]
        elif value not in allowed:
            value = item["default"]
        result[item["key"]] = copy.deepcopy(value)
    return result


def with_template_value(entry: OverlayEntry, key: str, value: object) -> OverlayEntry:
    template = template_for(entry)
    item = next((item for item in template.settings if item["key"] == key), None)
    if item is None:
        return entry
    settings = {**template_values(entry, template), key: value}
    candidate = replace(entry, template_settings=settings)
    normalized = template_values(candidate, template)
    for scale_key in ('_damage_window_scale', '_combo_window_scale', '_native_window_scale'):
        if scale_key in entry.template_settings:
            normalized[scale_key] = entry.template_settings[scale_key]
    changes = {"template_settings": normalized}
    # Keep the old serialized fields readable by older dev builds.
    if legacy := item.get("legacy_field"):
        changes[legacy] = tuple(normalized[key]) if item["type"] == "multiselect" else normalized[key]
    return replace(entry, **changes)
