"""Resolve stack limits from exact typed and declared metadata."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.buff_templates import _load_local_buff_semantic_entries
from parser_core.catalog.buff_templates import _load_weapon_buff_stack_limits
from parser_core.ingestion.fields import _positive_int
import re
from typing import Any


_WEAPON_ID_FROM_BUFF_RE = re.compile(r"^buff_(wpn_[a-z]+_\d+)_")


_FOOD_POTION_BUFF_RE = re.compile(r"^buff_common_.*_potion(?:_\d+)?$", re.IGNORECASE)


def _is_nonstacking_refresh_event(event_key: str | None) -> bool:
    event_key = str(event_key or "")
    root = _load_current_buff_roots().get(event_key)
    settings = root.get('stackingSettings') if isinstance(root, dict) else None
    return isinstance(settings, dict) and settings.get('stackingType') == 'Unique'


def _is_food_potion_buff(event_key: str | None) -> bool:
    return bool(_FOOD_POTION_BUFF_RE.match(str(event_key or "")))


def _buff_stack_limit(event_key: str | None, bb_values: dict[str, Any] | None = None) -> int | None:
    event_key = str(event_key or "")
    if not event_key:
        return None
    root = _load_current_buff_roots().get(event_key)
    settings = root.get('stackingSettings') if isinstance(root, dict) else None
    if isinstance(settings, dict):
        if settings.get('stackingType') == 'HighPriority':
            return 1
        if settings.get('stackingType') == 'Unique' and settings.get('useMaxStackCntKey') is False:
            return _positive_int(settings.get('maxStackCnt')) or 1
        if settings.get('useMaxStackCntKey') is True:
            value = _positive_int((bb_values or {}).get(str(settings.get('maxStackCntKey') or '')))
            return value
        value = _positive_int(settings.get('maxStackCnt'))
        if value is not None:
            return value
        return None
    semantic_entry = _load_local_buff_semantic_entries().get(event_key)
    if isinstance(semantic_entry, dict):
        stacking = semantic_entry.get("stacking")
        if isinstance(stacking, dict):
            semantic_limit = _positive_int(stacking.get("maxStackCnt"))
            if semantic_limit is not None:
                return semantic_limit
    exact_limit = _load_weapon_buff_stack_limits().get(event_key)
    if exact_limit is not None:
        return exact_limit
    match = _WEAPON_ID_FROM_BUFF_RE.match(event_key)
    return None
