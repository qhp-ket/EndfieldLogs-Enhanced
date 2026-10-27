"""Dungeon and contract catalogs, authoritative aliases and display metadata."""
from __future__ import annotations

from parser_core.catalog.resources import _repo_root
from parser_core.ingestion.fields import _coerce_int
from functools import lru_cache
from pathlib import Path
import json
from typing import Any




_DUNGEON_CONTEXT_ALIASES: dict[str, tuple[str, str]] = {
    "indie_contract001": ("indie_group_ccdg", "危机合约"),
    "indie_group_ccdg": ("indie_group_ccdg", "危机合约"),
    "indie_ccdg001": ("indie_group_ccdg", "危机合约"),
    "indie_hard016": ("indie_hard016", "仪式旋流"),
    "indie_hard016_s": ("indie_hard016_s", "仪式旋流·苦难"),
    "indie_hard017": ("indie_hard017", "死寂表象"),
    "indie_hard017_s": ("indie_hard017_s", "死寂表象·苦难"),
    "indie_hard018": ("indie_hard018", "忿鼓咆声"),
    "indie_hard018_s": ("indie_hard018_s", "忿鼓咆声·苦难"),
    "indie_hard019": ("indie_hard019", "刺痛盾阵"),
    "indie_hard019_s": ("indie_hard019_s", "刺痛盾阵·苦难"),
    "indie_hard020": ("indie_hard020", "溶解窥看"),
    "indie_hard020_s": ("indie_hard020_s", "溶解窥看·苦难"),
    "indie_hard021": ("indie_hard021", "冯河断水"),
    "indie_hard021_s": ("indie_hard021_s", "冯河断水·苦难"),
}


UNKNOWN_DUNGEON_NAME = "未知副本"


def _apply_dungeon_catalog_overrides() -> None:
    """Merge dungeon alias tables from data/local_tables/dungeon_catalog.json.

    The catalog file is the single maintained source for dungeon aliases shared
    by parser_core, the API service, and the web frontend. Entries in the file
    win over the built-in tables above; the built-ins remain as a fallback for
    environments where the data directory is absent.
    """
    catalog_path = _repo_root() / "data" / "local_tables" / "dungeon_catalog.json"
    if not catalog_path.exists():
        return
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    parser_tables = catalog.get("parser") or {}
    for key, value in (parser_tables.get("dungeon_context_aliases") or {}).items():
        if isinstance(value, list) and len(value) == 2:
            _DUNGEON_CONTEXT_ALIASES[str(key)] = (str(value[0]), str(value[1]))


def _dungeon_table_sources() -> list[tuple[Path, Path]]:
    root = _repo_root()
    return [
        (root / "data" / "akedata" / "dungeon" / "manifest.json", root / "data" / "akedata" / "dungeon" / "items"),
        (root / "data" / "local_tables" / "dungeon" / "manifest.json", root / "data" / "local_tables" / "dungeon" / "items"),
    ]


def _iter_dungeon_manifest_entries(manifest: Any) -> list[dict[str, Any]]:
    if isinstance(manifest, list):
        return [entry for entry in manifest if isinstance(entry, dict)]
    if isinstance(manifest, dict):
        entries = manifest.get("entries")
        if isinstance(entries, list):
            return [entry for entry in entries if isinstance(entry, dict)]
    return []


def _dungeon_item_path(entry: dict[str, Any], dungeon_root: Path) -> Path | None:
    content_file = str(entry.get("contentFile") or "")
    detail_path = str(entry.get("detailPath") or "")
    if detail_path:
        candidate = _repo_root() / detail_path
        if candidate.exists():
            return candidate
    if content_file:
        return dungeon_root / Path(content_file).name
    if detail_path:
        return dungeon_root / Path(detail_path).name
    return None


def _iter_dungeon_table_payloads() -> list[tuple[dict[str, Any], dict[str, Any]]]:
    payloads: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for manifest_path, dungeon_root in _dungeon_table_sources():
        if not manifest_path.exists() or not dungeon_root.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in _iter_dungeon_manifest_entries(manifest):
            item_path = _dungeon_item_path(entry, dungeon_root)
            if item_path is None or not item_path.exists():
                continue
            try:
                data = json.loads(item_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                payloads.append((entry, data))
    return payloads


@lru_cache(maxsize=1)
def _load_dungeon_by_id() -> dict[str, tuple[str, str]]:
    mapping: dict[str, tuple[str, str]] = {}
    for entry, data in _iter_dungeon_table_payloads():
        template_id = str(entry.get("templateId") or "")
        if not template_id:
            continue
        series_key = str(data.get("dungeonSeriesId") or template_id)
        series_name = str(data.get("dungeonSeriesname") or entry.get("name") or UNKNOWN_DUNGEON_NAME)
        mapping.setdefault(series_key, (series_key, series_name))
        child_dungeons = data.get("dungeons") or data.get("childDungeons") or {}
        for dungeon_id, dungeon in child_dungeons.items():
            dungeon_key = str(dungeon_id)
            dungeon_name = str(dungeon.get("name") or series_name)
            if dungeon_key.startswith("indie_hard"):
                mapping[dungeon_key] = (dungeon_key, dungeon_name)
            elif series_name == UNKNOWN_DUNGEON_NAME and dungeon_name != UNKNOWN_DUNGEON_NAME:
                # Activity groups such as dungeon_takestwo have no official
                # series name. Preserve their official child gameId and the
                # resolved DungeonTable name instead of reporting an unknown
                # group. Ranked groups with a real series name keep their
                # existing canonical grouping behavior.
                mapping[dungeon_key] = (dungeon_key, dungeon_name)
            else:
                mapping[dungeon_key] = (series_key, series_name)
        for dungeon_id in data.get("includeDungeonIds") or []:
            dungeon_key = str(dungeon_id or "")
            if not dungeon_key:
                continue
            if dungeon_key.startswith("indie_hard"):
                mapping.setdefault(dungeon_key, (dungeon_key, series_name))
            else:
                mapping.setdefault(dungeon_key, (series_key, series_name))
    return mapping


def _resolve_dungeon_context(dungeon_id: str | None) -> tuple[str, str] | None:
    if not dungeon_id:
        return None
    return _DUNGEON_CONTEXT_ALIASES.get(dungeon_id) or _load_dungeon_by_id().get(dungeon_id)


@lru_cache(maxsize=1)
def _load_contract_tag_texts() -> dict[str, str]:
    candidates = [
        _repo_root().parent / "endfield_tables" / "Data" / "TableCfg" / "I18nTextTable_CN.json",
        _repo_root() / "data" / "local_tables" / "I18nTextTable_CN.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            result: dict[str, str] = {}
            for key, value in payload.items():
                if isinstance(value, str):
                    result[str(key)] = value
                elif isinstance(value, dict):
                    text = value.get("text") or value.get("value")
                    if isinstance(text, str):
                        result[str(key)] = text
            return result
    return {}


def _contract_tag_text(value: Any, texts: dict[str, str]) -> str | None:
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, str) and text:
            return text
        value = value.get("id")
    if value is None:
        return None
    return texts.get(str(value))


@lru_cache(maxsize=1)
def _load_contract_tag_catalog() -> dict[int, dict[str, Any]]:
    catalog: dict[int, dict[str, Any]] = {}
    public_path = _repo_root() / "data" / "public" / "contract_tags.json"
    if public_path.exists():
        try:
            payload = json.loads(public_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        tags = payload.get("tags") if isinstance(payload, dict) else payload
        entries = tags.values() if isinstance(tags, dict) else tags if isinstance(tags, list) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            tag_id = _coerce_int(str(item.get("tagId") or item.get("tag_id") or ""), default=0)
            if tag_id > 0:
                catalog[tag_id] = dict(item)

    table_candidates = [
        _repo_root().parent / "endfield_tables" / "Data" / "TableCfg" / "CcTagTable.json",
        _repo_root() / "data" / "local_tables" / "CcTagTable.json",
    ]
    for path in table_candidates:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = payload.values() if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        for item in entries:
            if not isinstance(item, dict):
                continue
            tag_id = _coerce_int(str(item.get("tagId") or item.get("tag_id") or ""), default=0)
            if tag_id <= 0:
                continue
            merged = dict(catalog.get(tag_id) or {})
            merged.update(item)
            catalog[tag_id] = merged
        break

    texts = _load_contract_tag_texts()
    for tag_id, item in list(catalog.items()):
        enriched = dict(item)
        name = enriched.get("name")
        desc = enriched.get("desc") if "desc" in enriched else enriched.get("description")
        name_text = _contract_tag_text(name, texts) or _contract_tag_text(enriched.get("nameTextId"), texts)
        desc_text = _contract_tag_text(desc, texts) or _contract_tag_text(enriched.get("descTextId"), texts)
        if name_text:
            enriched["name"] = name_text
        if desc_text:
            enriched["description"] = desc_text
        catalog[tag_id] = enriched
    return catalog


def _contract_tag_payload(tag_id: int) -> dict[str, Any]:
    catalog_entry = _load_contract_tag_catalog().get(tag_id, {})
    tag_terms = catalog_entry.get("tagTerms") if isinstance(catalog_entry.get("tagTerms"), list) else []
    values: dict[str, Any] = {}
    for term in tag_terms:
        if not isinstance(term, dict):
            continue
        for row in term.get("blackboard") or []:
            if isinstance(row, dict) and row.get("key") is not None:
                values[str(row.get("key"))] = row.get("value")
    icon_id = catalog_entry.get("iconId") or catalog_entry.get("icon")
    payload: dict[str, Any] = {
        "tag_id": tag_id,
        "score": _coerce_int(str(catalog_entry.get("score") or ""), default=0),
    }
    if catalog_entry.get("name"):
        payload["name"] = catalog_entry.get("name")
    if catalog_entry.get("description"):
        payload["description"] = catalog_entry.get("description")
    if icon_id:
        payload["icon"] = icon_id
    icon_url = catalog_entry.get("iconUrl") or catalog_entry.get("icon_url")
    if icon_url:
        payload["icon_url"] = icon_url
    if catalog_entry.get("buffId"):
        payload["buff_id"] = catalog_entry.get("buffId")
    if catalog_entry.get("groupId") is not None:
        payload["group_id"] = catalog_entry.get("groupId")
    if catalog_entry.get("conflictId") is not None:
        payload["conflict_id"] = catalog_entry.get("conflictId")
    if tag_terms:
        payload["terms"] = tag_terms
    if values:
        payload["values"] = values
    return payload

_apply_dungeon_catalog_overrides()


def _high_difficulty_stage_key(dungeon_id: str) -> str:
    return dungeon_id.removesuffix("_s")
