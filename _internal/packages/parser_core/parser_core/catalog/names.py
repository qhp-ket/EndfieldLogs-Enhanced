"""Canonical numeric skill identifiers and character/skill display names."""
from __future__ import annotations

from functools import lru_cache
from parser_core.catalog.resources import _repo_root
from parser_core.ingestion.identity import _CHAR_KEY_RE, _ENEMY_KEY_RE
import json
import re
from typing import Any




_RUNTIME_SKILL_ID_RE = re.compile(r"^(?:skill_)?(\d+)$")


_COMPOSITE_RUNTIME_SKILL_RE = re.compile(r"^(chr_\d{4}_[a-z0-9]+)_skill_(\d+)$")


_ENDMIN_VARIANTS = {"chr_0002_endminm", "chr_0003_endminf"}


_CURRENT_TYPED_RESOURCE_BINDING = {
    'gameAssemblySha256': 'ab00f1c41e13edf9816f142b166e3c2536d5bc7707992c39e5ed52d1cc888e2c',
    'metadataSha256': '461321d9dca6a832bce3bd2390402efc7c83c145554e97a8058bb68fbec1c8ca',
    'schemaSha256': '42bd4483f3f6f5937fd4a1f8bd43f3152ee62d33e259c67260a4be25a8a4bcf2',
}


_RUNTIME_SKILL_NAME_OVERRIDES = {
    "chr_0017_yvonne_skill_162": "伊冯连携 / 机器人持续伤害",
    "chr_0017_yvonne_skill_163": "伊冯连携 / 机器人终结爆炸",
}


@lru_cache(maxsize=1)
def _load_packet_numeric_skill_map() -> dict[str, dict[str, Any]]:
    map_path = _repo_root() / "data" / "packet_semantics" / "skill_numeric_map.json"
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
        str(skill_id): mapping
        for skill_id, mapping in mappings.items()
        if isinstance(mapping, dict)
    }


def _packet_numeric_skill_hint(skill_key: str | None) -> dict[str, Any]:
    return _load_packet_numeric_skill_map().get(str(skill_key or ""), {})


@lru_cache(maxsize=1)
def _load_num_id_str_skill_map() -> dict[str, str]:
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
        skill_section = payload.get("skill_id") if isinstance(payload, dict) else None
        if not isinstance(skill_section, dict):
            continue
        mapping = skill_section.get("dic")
        if not isinstance(mapping, dict):
            continue
        return {
            str(skill_id): str(static_id)
            for skill_id, static_id in mapping.items()
            if static_id is not None
        }
    return {}


def _canonical_num_table_skill_number(skill_number: str | None, character_key: str | None) -> str | None:
    if not skill_number:
        return None
    static_id = _load_num_id_str_skill_map().get(str(skill_number))
    if not static_id:
        return None
    if not _runtime_owner_matches_static_domain(character_key, static_id):
        return None
    if not character_key:
        return static_id
    match = _CHAR_KEY_RE.search(static_id)
    if match and not _character_key_matches_static_family(str(character_key), match.group(1)):
        return None
    return static_id


def _character_key_matches_static_family(character_key: str | None, static_character_key: str | None) -> bool:
    character = str(character_key or "")
    static_character = str(static_character_key or "")
    if not character or not static_character:
        return True
    if character == static_character:
        return True
    if character == "chr_9000_endmin" and static_character in _ENDMIN_VARIANTS:
        return True
    return False


def _runtime_owner_matches_static_domain(character_key: str | None, static_id: str | None) -> bool:
    owner = str(character_key or "")
    static = str(static_id or "")
    if not owner or not static:
        return True
    if owner.startswith("chr_") and _ENEMY_KEY_RE.search(static):
        return False
    if owner.startswith("eny_") and _CHAR_KEY_RE.search(static):
        return False
    return True


@lru_cache(maxsize=1)
def _load_canonical_skill_display_names() -> dict[str, str]:
    display_names: dict[str, str] = {}
    skill_map = _load_packet_numeric_skill_map()
    map_path = _repo_root() / "data" / "packet_semantics" / "skill_numeric_map.json"
    if map_path.exists():
        try:
            payload = json.loads(map_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        preserved = payload.get("canonical_display_names") if isinstance(payload, dict) else {}
        if isinstance(preserved, dict):
            for canonical_skill_id, display_name in preserved.items():
                canonical_text = str(canonical_skill_id or "").strip()
                display_text = str(display_name or "").strip()
                if not canonical_text or not display_text:
                    continue
                existing = display_names.get(canonical_text, "")
                if not existing or len(display_text) > len(existing):
                    display_names[canonical_text] = display_text
    for mapping in skill_map.values():
        canonical_skill_id = str(mapping.get("canonical_skill_id") or "")
        display_name = str(mapping.get("display_name") or "").strip()
        if not canonical_skill_id or not display_name:
            continue
        existing = display_names.get(canonical_skill_id, "")
        if not existing or len(display_name) > len(existing):
            display_names[canonical_skill_id] = display_name
    return display_names


def _runtime_skill_number(skill_key: str | None) -> str | None:
    raw_skill_key = str(skill_key or "")
    match = _RUNTIME_SKILL_ID_RE.match(raw_skill_key)
    if match:
        return match.group(1)
    match = _COMPOSITE_RUNTIME_SKILL_RE.match(raw_skill_key)
    if match:
        return match.group(2)
    return None


def _canonical_packet_skill_id(skill_key: str | None) -> str:
    raw_skill_key = str(skill_key or "")
    number = _runtime_skill_number(raw_skill_key)
    if not number:
        return raw_skill_key
    return _canonical_num_table_skill_number(number, None) or raw_skill_key


@lru_cache(maxsize=1)
def _load_character_names() -> dict[str, str]:
    names = {}
    for source in ('akedata', 'local_tables'):
        manifest_path = _repo_root() / 'data' / source / 'character/manifest.json'
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf8'))
        except (OSError, ValueError):
            continue
        entries = manifest.get('entries', []) if isinstance(manifest, dict) else manifest
        if isinstance(entries, list):
            names.update({str(entry['charId']): str(entry['name']) for entry in entries
                          if isinstance(entry, dict) and entry.get('charId') and entry.get('name')})
    return names


@lru_cache(maxsize=1)
def _load_skill_name_prefixes() -> list[tuple[str, str]]:
    character_root = _repo_root() / "data" / "akedata" / "character" / "items"
    if not character_root.exists():
        return []

    prefixes: list[tuple[str, str]] = []
    for path in character_root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for skill in data.get("skills") or []:
            skill_name = str(skill.get("name") or "")
            skill_ids = skill.get("skillIds") or []
            if not skill_name:
                continue
            for skill_id in skill_ids:
                skill_key = str(skill_id or "")
                if skill_key:
                    prefixes.append((skill_key, skill_name))
    prefixes.sort(key=lambda item: len(item[0]), reverse=True)
    return prefixes


@lru_cache(maxsize=1)
def _load_skill_exact_names() -> dict[str, str]:
    names = {
        skill_key: skill_name
        for skill_key, skill_name in _load_skill_name_prefixes()
    }
    # Display labels have their own exact, version-bound official relation.
    # They must not change skill family, damage classification or attribution.
    try:
        catalog = json.loads((_repo_root() / 'data/local_static/skill/display_name_catalog.json')
                             .read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return names
    if (not isinstance(catalog, dict) or catalog.get('schemaVersion') != 1
            or catalog.get('source') != 'official_CharGrowth_I18n_typed_skill_display'
            or not isinstance(catalog.get('decoder'), dict)
            or any(catalog['decoder'].get(key) != value
                   for key, value in _CURRENT_TYPED_RESOURCE_BINDING.items())):
        return names
    entries = catalog.get('entries')
    conflicts = catalog.get('conflicts', {})
    if not isinstance(entries, dict) or not isinstance(conflicts, dict):
        return names
    for skill_key, entry in entries.items():
        if (not isinstance(skill_key, str) or not skill_key or not isinstance(entry, dict)
                or skill_key in conflicts
                or entry.get('proofKind') not in {'official_char_growth_skill_list', 'typed_enabled_creation_path'}):
            continue
        display_name = entry.get('displayName')
        if isinstance(display_name, str) and display_name.strip():
            names[skill_key] = display_name.strip()
    # An explicit official ambiguity must not select an older cached label.
    for skill_key in conflicts:
        names[skill_key] = ''
    return names


def _resolve_character_name(character_key: str | None) -> str | None:
    if not character_key:
        return None
    return _load_character_names().get(character_key, character_key)


def _resolve_skill_name(skill_key: str | None) -> str | None:
    if not skill_key:
        return None
    exact_names = _load_skill_exact_names()
    if str(skill_key) in exact_names and not exact_names[str(skill_key)]:
        return None
    override = _RUNTIME_SKILL_NAME_OVERRIDES.get(str(skill_key))
    if override:
        return override
    hint = _packet_numeric_skill_hint(skill_key)
    if hint.get("display_name"):
        return str(hint["display_name"])
    exact = exact_names.get(str(skill_key))
    if exact:
        return exact
    canonical = _canonical_packet_skill_id(skill_key)
    if canonical in exact_names:
        return exact_names[canonical] or None
    return _load_canonical_skill_display_names().get(canonical)



def _is_runtime_numeric_skill_id(skill_key: str | None) -> bool:
    text = str(skill_key or "")
    return bool(re.fullmatch(r"skill_\d+", text) or re.search(r"_skill_\d+$", text))


def _derived_skill_id_from_origin_skill(origin_skill_id: str | None) -> str | None:
    origin = str(origin_skill_id or "")
    if not origin:
        return None
    if origin.endswith("_projhit"):
        return origin
    return f"{origin}_projhit"


def _char_prefix(value: Any) -> str | None:
    match = re.match(r"^(chr_\d{4})_", str(value or ""))
    return match.group(1) if match else None
