"""Local renderer declarations. No battle calculation belongs in this module."""
from __future__ import annotations
import copy
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from endfield_pcap.models import OverlayEntry, OverlaySourceType


ASSETS = Path(__file__).resolve().parent / "assets"
BUILTIN_DIRECTORIES = {"combo_skill": "combo"}
SNAPSHOTS = {"analysis_snapshot", "analysis_summary", "combo_snapshot", "buff_snapshot"}


@dataclass(slots=True)
class OverlayTemplate:
    path: Path | None = None
    name: str = "网页自带配置"
    entry: Path | None = None
    subscriptions: tuple[str, ...] = ()
    settings: list[dict] = field(default_factory=list)
    window: dict[str, int] = field(default_factory=dict)
    font_mode: str = "dom"
    error: str = ""


def read_template(path: Path) -> OverlayTemplate:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema_version") != 1:
        raise ValueError("模板 schema_version 必须为 1")
    entry = (path.parent / data["entry"]).resolve()
    if entry.suffix.lower() not in {".html", ".htm"} or not entry.is_file():
        raise ValueError("模板 entry 必须指向存在的 HTML 文件")
    subscriptions = data.get("subscriptions", [])
    if not isinstance(subscriptions, list) or any(s not in SNAPSHOTS for s in subscriptions):
        raise ValueError("模板订阅仅支持 analysis_snapshot / combo_snapshot / buff_snapshot")
    settings = data.get("settings", [])
    keys = set()
    if not isinstance(settings, list):
        raise ValueError("模板 settings 必须为数组")
    for item in settings:
        key = item.get("key")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("模板设置 key 不能为空或重复")
        keys.add(key)
        if item.get("type") not in {"select", "multiselect"}:
            raise ValueError("模板设置类型仅支持 select / multiselect")
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
    if any(k not in {"min_width", "min_height", "default_width", "default_height"}
           or not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 16384 for k, v in window.items()):
        raise ValueError("模板窗口尺寸无效")
    return OverlayTemplate(path.resolve(), str(data.get("name", path.stem)), entry,
                           tuple(subscriptions), settings, window,
                           "css" if data.get("font_mode") == "css" else "dom")


def template_for(entry: OverlayEntry) -> OverlayTemplate:
    path = None
    if entry.source_type == OverlaySourceType.BUILTIN:
        path = ASSETS / BUILTIN_DIRECTORIES.get(entry.source_value, entry.source_value) / "template.json"
    elif entry.source_type == OverlaySourceType.FILE:
        source = Path(entry.source_value)
        if source.suffix.lower() == ".json":
            path = source
        else:
            path = source.with_suffix(".template.json")
            if not path.is_file():
                path = source.parent / "template.json"
    if path is None or (not path.is_file() and path.suffix.lower() == ".json"
                        and not (entry.source_type == OverlaySourceType.FILE and Path(entry.source_value).suffix.lower() == ".json")):
        return OverlayTemplate()
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
    changes = {"template_settings": normalized}
    # Keep the old serialized fields readable by older dev builds.
    if legacy := item.get("legacy_field"):
        changes[legacy] = tuple(normalized[key]) if item["type"] == "multiselect" else normalized[key]
    return replace(entry, **changes)
