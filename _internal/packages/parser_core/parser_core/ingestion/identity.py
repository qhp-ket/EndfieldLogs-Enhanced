"""Explicit actor and target identities; legacy inference entry points remain conservative."""
from __future__ import annotations

from parser_core.ingestion.fields import _extract_fields
import re
from typing import Any




_CHAR_KEY_RE = re.compile(r"(chr_\d{4}_[a-z0-9]+)")


_SQUAD_MEMBER_RE = re.compile(r"(chr_\d{4}_[a-z0-9]+)_(\d+)")


_ENEMY_KEY_RE = re.compile(r"(eny_\d{4}_[a-z0-9]+)")


_FULL_ENEMY_KEY_RE = re.compile(r"^(eny_\d{4}_[a-z0-9]+(?:_[a-z0-9]+)*)$")


def _apply_short_actor_aliases(text: str) -> str:
    return text


def _extract_character_key(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        match = _CHAR_KEY_RE.search(value)
        if match:
            return match.group(1)
    return None


def _extract_enemy_key(*values: str | None) -> str | None:
    for value in values:
        if not value:
            continue
        full_match = _FULL_ENEMY_KEY_RE.match(value)
        if full_match:
            return full_match.group(1)
        match = _ENEMY_KEY_RE.search(value)
        if match:
            return match.group(1)
    return None


def _collect_party_actor_ids(raw_line: str) -> set[str]:
    actor_ids: set[str] = set()
    if " SQUAD " in raw_line:
        actor_ids.update(match.group(2) for match in _SQUAD_MEMBER_RE.finditer(raw_line))
    if " ENTITY_STATS " in raw_line:
        fields = _extract_fields(raw_line)
        if fields.get("kind") == "character" and _extract_character_key(fields.get("template")):
            actor_id = fields.get("id")
            if actor_id:
                actor_ids.add(actor_id)
    return actor_ids


def _recover_enemy_target_from_mislabeled_actor(
    fields: dict[str, str],
    *,
    context_enemy_hint: str | None,
    party_actor_ids: set[str],
) -> str | None:
    return None


def _infer_context_enemy_hint(*args: Any, **kwargs: Any) -> None:
    return None



def _retarget_unknown_enemy_hits(
    hits: list[dict[str, Any]],
    buff_starts: list[dict[str, Any]],
    enemy_key: str | None,
) -> bool:
    return False


_apply_short_actor_aliases._live_identity = True
