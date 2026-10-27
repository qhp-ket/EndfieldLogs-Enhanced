"""Accumulate per-hit contributions in source order with live cache boundaries."""
from __future__ import annotations

from collections import defaultdict
from parser_core.allocation.hit import _allocate_rdps_for_hit
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.ingestion.fields import _coerce_optional_int
from parser_core.ingestion.fields import _extract_fields
from parser_core.ink_provenance import EXPLOSION as INK_EXPLOSION
from parser_core.ink_provenance import apply_ink_provenance
import copy
from typing import Any


def _compute_rdps_damage_shares(
    hits: list[dict[str, Any]],
    buff_windows: list[dict[str, Any]],
    condition_buff_records: list[dict[str, Any]] | None = None,
    *, trace_text: str | None = None, ink_summary: dict | None = None,
) -> dict[str, float]:
    rdps_damage: dict[str, float] = defaultdict(float)
    from parser_core.realtime.incremental import ACTIVE_ALLOCATION_CACHE
    live_cache = ACTIVE_ALLOCATION_CACHE.get()
    if live_cache is not None:
        live_cache.begin(hits, buff_windows, condition_buff_records, trace_text)
    from parser_core.condition_index import ConditionRecordIndex, EffectWindowIndex
    condition_index = ConditionRecordIndex(condition_buff_records, _coerce_optional_int)
    window_index = EffectWindowIndex(buff_windows)
    condition_records_by_uid: dict[str, list[dict[str, Any]]] = defaultdict(list)
    condition_records_by_actor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in condition_buff_records or []:
        condition_records_by_uid[str(record.get('uid') or '')].append(record)
        condition_records_by_actor[str(record.get('target_actor_id') or '')].append(record)

    for hit in hits:
        if live_cache is not None and live_cache.reuse(hit):
            continue
        original = copy.deepcopy(hit) if live_cache is not None else None
        # Only narrow the condition-ID lookup. The complete records and effect
        # windows remain available for resistance/Arts provenance checks.
        condition_records_by_target = {
            target: condition_index.candidates(target, int(hit.get('ts_ms') or 0))
            for target in {str(hit.get('character_key') or ''), str(hit.get('target_enemy_key') or '')}
        }
        allocation = ({'contributions_map': {hit['character_key']: float(hit['hit_value'])}}
            if trace_text is not None and hit.get('skill_key') == INK_EXPLOSION else
            _allocate_rdps_for_hit(hit, buff_windows, include_debug=False,
                condition_buff_records=condition_buff_records,
                condition_records_by_target=condition_records_by_target,
                effect_window_indices=window_index.candidates(int(hit.get('ts_ms') or 0)),
                condition_records_by_uid=condition_records_by_uid,
                condition_records_by_actor=condition_records_by_actor))
        normalized_contributions = dict(allocation.get("contributions_map") or {})
        hit["rdps_contributions"] = normalized_contributions
        if live_cache is not None:
            live_cache.remember(original, hit)
    if trace_text is not None:
        ink_apply = live_cache.apply_ink if live_cache is not None else lambda h, r, **kw: apply_ink_provenance(trace_text, h, r, **kw)
        summary = ink_apply(hits, condition_buff_records or [],
            root_lookup=_load_current_buff_roots(), extract_fields=_extract_fields)
        if ink_summary is not None:
            ink_summary.update(summary)
    if live_cache is not None:
        live_cache.finish(hits)
        return live_cache.contribution_totals(hits)
    for hit in hits:
        for character_key, value in (hit.get('rdps_contributions') or {}).items():
            rdps_damage[character_key] += value

    return dict(rdps_damage)
