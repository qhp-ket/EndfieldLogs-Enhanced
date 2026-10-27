"""Numeric protocol identifiers, canonical mappings and approved semantics registries."""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
from parser_core.catalog.resources import _repo_root
import json
from typing import Any


_RDPS_VERIFIED_INDEX: tuple[dict, dict, dict, dict, dict] | None = None


_CURRENT_KEYWORD_BINDING = {
    'gameAssemblySha256': 'ab00f1c41e13edf9816f142b166e3c2536d5bc7707992c39e5ed52d1cc888e2c',
    'metadataSha256': '461321d9dca6a832bce3bd2390402efc7c83c145554e97a8058bb68fbec1c8ca',
}


@lru_cache(maxsize=1)
def _load_packet_numeric_buff_map() -> dict[str, dict[str, Any]]:
    map_path = _repo_root() / "data" / "packet_semantics" / "buff_numeric_map.json"
    if not map_path.exists():
        return {}
    try:
        payload = json.loads(map_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mappings = payload.get("mappings")
    if not isinstance(mappings, dict):
        return {}
    return {
        str(buff_id): mapping
        for buff_id, mapping in mappings.items()
        if isinstance(mapping, dict)
    }


def _merge_packet_buff_mapping_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    base = dict(rows[0])
    effect_keys: set[str] = set()
    merged_effects: list[dict[str, Any]] = []
    for field in ("effects", "dynamic_effects"):
        merged: list[dict[str, Any]] = []
        for row in rows:
            values = row.get(field)
            if not isinstance(values, list):
                continue
            for item in values:
                if not isinstance(item, dict):
                    continue
                marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                unique_key = f"{field}:{marker}"
                if unique_key in effect_keys:
                    continue
                effect_keys.add(unique_key)
                merged.append(item)
        if merged:
            merged_effects.extend(merged)
            base[field] = merged
    if "effects" not in base:
        base["effects"] = []
    if "dynamic_effects" not in base:
        base["dynamic_effects"] = []
    for row in rows[1:]:
        if not base.get("reason") and row.get("reason"):
            base["reason"] = row.get("reason")
        if not base.get("confidence") and row.get("confidence"):
            base["confidence"] = row.get("confidence")
        if base.get("stack_limit") in (None, "", 0) and row.get("stack_limit") not in (None, "", 0):
            base["stack_limit"] = row.get("stack_limit")
    return base


@lru_cache(maxsize=1)
def _load_packet_canonical_buff_map() -> dict[str, dict[str, Any]]:
    by_canonical: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in _load_packet_numeric_buff_map().values():
        canonical_buff_id = str(row.get("canonical_buff_id") or "")
        if not canonical_buff_id:
            continue
        by_canonical[canonical_buff_id].append(row)
    return {
        canonical_buff_id: _merge_packet_buff_mapping_rows(rows)
        for canonical_buff_id, rows in by_canonical.items()
        if rows
    }


@lru_cache(maxsize=1)
def _load_mechanism_registry_by_buff_id() -> dict[str, list[dict[str, Any]]]:
    path = _repo_root() / "data" / "packet_semantics" / "mechanism_registry.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    rows_by_buff = payload.get("by_buff_id")
    if not isinstance(rows_by_buff, dict):
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for buff_id, rows in rows_by_buff.items():
        if not isinstance(rows, list):
            continue
        normalized_rows = [row for row in rows if isinstance(row, dict)]
        if normalized_rows:
            out[str(buff_id)] = normalized_rows
    return out


@lru_cache(maxsize=1)
def _load_rdps_semantics_registry() -> dict[str, Any]:
    global _RDPS_VERIFIED_INDEX
    _RDPS_VERIFIED_INDEX = None
    path = _repo_root() / "data" / "packet_semantics" / "rdps_semantics_registry.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        keyword = json.loads((_repo_root() / 'data/local_static/buff/keyword_buff_map.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        keyword = {}
    if (isinstance(keyword, dict) and type(keyword.get('schemaVersion')) is int and keyword['schemaVersion'] == 1
            and keyword.get('source') == 'current_native_keyword_switch_and_metadata_literals'
            and keyword.get('decoder') == _CURRENT_KEYWORD_BINDING):
        mapping = keyword.get('mapping')
        subtypes = {'All', 'Spell', 'Physical', 'Natural', 'Fire', 'Crystal', 'Pulse'}
        if (isinstance(mapping, dict) and set(mapping) == {'Vulnerable', 'Enhanced'}
                and all(isinstance(rows, dict) and set(rows) == subtypes
                        and all(isinstance(value, str) and value for value in rows.values()) for rows in mapping.values())):
            payload['_keyword_buff_map'] = mapping
    verified = payload.get('verified_effects')
    if isinstance(verified, dict):
        exact_index: dict[str, set[str]] = defaultdict(set)
        runtime_index: dict[str, set[str]] = defaultdict(set)
        for key, entry in verified.items():
            if not isinstance(entry, dict):
                continue
            for identity in [key, *(entry.get('aliases') or []), *(entry.get('numeric_ids') or [])]:
                if str(identity):
                    exact_index[str(identity)].add(key)
            for binding in entry.get('runtime_bindings') or []:
                if isinstance(binding, dict) and isinstance(binding.get('template'), str):
                    runtime_index[binding['template']].add(key)
        _RDPS_VERIFIED_INDEX = (payload, verified, dict(exact_index), dict(runtime_index),
                                {key: order for order, key in enumerate(verified)})
    return payload


@lru_cache(maxsize=1)
def _load_num_id_str_buff_map() -> dict[str, str]:
    candidate_paths = (
        _repo_root().parent / "endfield_tables" / "Data" / "TableCfg" / "NumIdStrTable.json",
        _repo_root() / "data" / "local_tables" / "NumIdStrTable.json",
    )
    for path in candidate_paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        buff_section = payload.get("buff_id") if isinstance(payload, dict) else None
        if not isinstance(buff_section, dict):
            continue
        mapping = buff_section.get("dic")
        if not isinstance(mapping, dict):
            continue
        return {
            str(buff_id): str(static_id)
            for buff_id, static_id in mapping.items()
            if static_id is not None
        }
    return {}
