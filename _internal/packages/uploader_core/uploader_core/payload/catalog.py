"""Upload equipment catalogs and resource location."""
from __future__ import annotations
from functools import lru_cache
import json
import os
from pathlib import Path
import sys


def _repo_root() -> Path:
    override = os.environ.get("ENDFIELD_LOGS_DATA_ROOT")
    if override:
        return Path(override)
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    for parent in Path(__file__).resolve().parents:
        if (parent / "data").exists() and (parent / "packages").exists():
            return parent
    return Path(__file__).resolve().parents[4]


def _normalize_asset_url(icon_path: str | None) -> str | None:
    if not icon_path:
        return None
    if icon_path.startswith("http://") or icon_path.startswith("https://"):
        return icon_path
    if icon_path.startswith("/"):
        return icon_path
    return icon_path


@lru_cache(maxsize=1)
def _load_weapon_catalog() -> dict[str, dict]:
    weapon_root = _repo_root() / "data" / "akedata" / "weapon" / "items"
    catalog: dict[str, dict] = {}
    if weapon_root.exists():
        for path in weapon_root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            weapon_id = str(data.get("weaponId") or "")
            if not weapon_id:
                continue
            catalog[weapon_id] = {
                "weaponName": str(data.get("title") or weapon_id),
                "iconUrl": _normalize_asset_url(data.get("icon")),
                # 等级 1..N 的基础攻击阶梯：包内 weaponLv 恒为 0，武器等级用 baseAtk 反查
                "baseAtk": data.get("baseAtk") if isinstance(data.get("baseAtk"), list) else None,
            }

    local_manifest = _repo_root() / "data" / "local_tables" / "weapon" / "manifest.json"
    if local_manifest.exists():
        try:
            local_data = json.loads(local_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            local_data = {}
        for item in local_data.get("entries", []):
            if not isinstance(item, dict):
                continue
            weapon_id = str(item.get("weaponId") or item.get("id") or "")
            if not weapon_id:
                continue
            existing = catalog.get(weapon_id, {})
            catalog[weapon_id] = {
                "weaponName": str(item.get("name") or existing.get("weaponName") or weapon_id),
                "iconUrl": _normalize_asset_url(item.get("icon")) or existing.get("iconUrl"),
                "baseAtk": existing.get("baseAtk"),
            }
    return catalog


def _infer_weapon_level_from_base_atk(weapon_catalog_entry: dict | None, base_atk: object) -> int | None:
    """weaponLv 服务器同步恒为 0；baseAtk 是每级唯一的阶梯值，反查即等级（1 基）。"""
    try:
        base_atk_value = int(base_atk)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if base_atk_value <= 0:
        return None
    ladder = (weapon_catalog_entry or {}).get("baseAtk")
    if not isinstance(ladder, list):
        return None
    level = None
    for index, value in enumerate(ladder):
        if value == base_atk_value:
            level = index + 1
    return level


@lru_cache(maxsize=1)
def _load_equip_catalog() -> dict[str, dict]:
    equip_root = _repo_root() / "data" / "akedata" / "equip" / "items"
    catalog: dict[str, dict] = {}
    if equip_root.exists():
        for path in equip_root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            equip_items = data.get("equip")
            if not isinstance(equip_items, dict):
                continue
            for item_id, item in equip_items.items():
                catalog[str(item_id)] = {
                    "pieceName": str(item.get("name") or item_id),
                    "partName": str(item.get("部位") or ""),
                    "iconUrl": _normalize_asset_url(item.get("icon")),
                }

    local_manifest = _repo_root() / "data" / "local_tables" / "equip" / "pieces.json"
    if local_manifest.exists():
        try:
            local_data = json.loads(local_manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            local_data = {}
        for item in local_data.get("entries", []):
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("itemId") or item.get("id") or "")
            if not item_id:
                continue
            existing = catalog.get(item_id, {})
            catalog[item_id] = {
                "pieceName": str(item.get("name") or existing.get("pieceName") or item_id),
                "partName": str(item.get("partName") or existing.get("partName") or ""),
                "iconUrl": _normalize_asset_url(item.get("icon")) or existing.get("iconUrl"),
            }
    return catalog
