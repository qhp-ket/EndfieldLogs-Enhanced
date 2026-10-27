"""Exact typed action lookup, scoped to one ingestion stream's immutable roots."""
from __future__ import annotations

from typing import Any

RootActionIndex = tuple[
    Any, dict[int, list[tuple[dict[str, Any], bool]]],
    list[tuple[dict[str, Any], bool]],
]
RootActionCache = dict[int, RootActionIndex]


def indexed_root_actions(root: Any, cache: RootActionCache) -> RootActionIndex:
    cached = cache.get(id(root))
    if cached is not None and cached[0] is root:
        return cached
    actions: dict[int, list[tuple[dict[str, Any], bool]]] = {}
    creations: list[tuple[dict[str, Any], bool]] = []
    pending = [(root, True)]
    while pending:
        node, enabled = pending.pop()
        if isinstance(node, dict):
            enabled = enabled and ('serverActionIndex' not in node or node.get('isEnable') is True)
            if type(node.get('serverActionIndex')) is int:
                actions.setdefault(node['serverActionIndex'], []).append((node, enabled))
            if node.get('$type') == 'Beyond.Gameplay.Core.CreateBuffAction.Data':
                creations.append((node, enabled))
            pending.extend((item, enabled) for item in node.values())
        elif isinstance(node, list):
            pending.extend((item, enabled) for item in node)
    result = (root, actions, creations)
    cache[id(root)] = result
    return result
