"""Exact anomaly-damage eligibility and arts-strength multiplier functions."""
from __future__ import annotations

from typing import Any

from collections import defaultdict
from parser_core.effects.evaluation import _window_effects_at_ts

from parser_core.allocation.static_loadout import _RDPS_DEBUG_ZONE_LABELS
from parser_core.ingestion.fields import _safe_positive_rate


def _is_arts_strength_damage_hit(hit: dict[str, Any]) -> bool:
    # Current native DamageDecorateMask values, matched to the version-bound
    # exact HP action/unit. Shatter is physical damage but a spell anomaly;
    # damage_element and damage_school must not be repurposed for this lane.
    mask = hit.get('damage_decorate_mask')
    source = 'observed_damage_decorate_mask'
    runtime_mask_present = mask is not None
    if not runtime_mask_present:
        mask = hit.get('static_damage_decorate_mask')
        source = hit.get('static_damage_decorate_mask_source')
        if source != 'current_typed_skill_or_buff_exact_unit_generation_only':
            mask = None
    if type(mask) is int and 0 <= mask < 2**64:
        kinds = []
        if mask & 0x4001C000:  # Crush, Airborne, KnockDown, Fracture.
            kinds.append('physical_anomaly')
        if mask & 0x0C100038:  # Four initial anomalies, Burning and Shatter.
            kinds.append('spell_anomaly')
        if mask & 0x03C00000:  # Fire/Crystal/Pulse/Natural Burst.
            kinds.append('spell_burst')
        hit['arts_strength_damage_observed'] = bool(kinds)
        hit['arts_strength_damage_kind'] = kinds[0] if len(kinds) == 1 else 'mixed_anomaly' if kinds else None
        hit['arts_strength_damage_source'] = source
        # The native formula independently multiplies spell-scaling attr49
        # and physical-scaling attr25. Several spell bits still mean one
        # factor, while an explicit physical+spell mask uses both factors.
        hit['arts_strength_damage_factor_count'] = int(bool(mask & 0x4001C000)) + int(bool(mask & 0x0FD00038))
        return bool(kinds)
    # Existing explicit mathematical fixtures can supply their classification.
    # A real but invalid mask, or a stale derived flag, is not that contract.
    explicit = (not runtime_mask_present and hit.get('arts_strength_damage_observed') is True
                and hit.get('arts_strength_damage_source') in (None, 'caller_supplied_classification'))
    hit['arts_strength_damage_observed'] = explicit
    hit['arts_strength_damage_kind'] = 'caller_classified_anomaly' if explicit else None
    hit['arts_strength_damage_source'] = 'caller_supplied_classification' if explicit else None
    hit['arts_strength_damage_factor_count'] = 1 if explicit else 0
    return explicit


def _arts_strength_damage_multiplier(points: float) -> float:
    return 1.0 + max(float(points), 0.0) / 100.0


def _arts_strength_effect_multiplier(points: float) -> float:
    normalized = max(float(points), 0.0)
    return 1.0 + (2.0 * normalized / (normalized + 300.0))



def _arts_strength_effect_contributors(
    *,
    effect_window: dict[str, Any],
    effect: dict[str, Any],
    buff_windows: list[dict[str, Any]],
) -> list[tuple[str, float, dict[str, Any] | None]]:
    """Require a typed source-strength provenance before allocating it."""

    source_key = str(effect_window.get("source_character_key") or "")
    final_rate = float(effect.get("rate") or 0.0)
    if effect.get('arts_strength_provenance') is not True:
        # This helper is also used by ordinary enemy debuffs. Their explicit
        # provider remains the provider; no secondary Arts redistribution is
        # inferred from their identifier.
        return [(source_key, final_rate, None)]

    applied_at_ms = int(effect_window.get("start_ts_ms") or 0)
    applied_line_no = int(effect_window.get("start_line_no") or effect_window.get("line_no") or 0)
    self_points = max(float(effect_window.get("source_static_arts_strength") or 0.0), 0.0)
    external_points: dict[str, float] = defaultdict(float)
    external_approval_keys: dict[str, set[str]] = defaultdict(set)

    for candidate in buff_windows:
        if str(candidate.get("target_character_key") or "") != source_key:
            continue
        start_ms = int(candidate.get("start_ts_ms") or 0)
        end_ms = int(candidate.get("end_ts_ms") or 0)
        if not (start_ms <= applied_at_ms <= end_ms):
            continue
        start_line_no = int(candidate.get("start_line_no") or candidate.get("line_no") or 0)
        if start_ms == applied_at_ms and applied_line_no and start_line_no and start_line_no > applied_line_no:
            continue
        provider_key = str(candidate.get("source_character_key") or "")
        if not provider_key:
            continue
        for candidate_effect in _window_effects_at_ts(candidate, applied_at_ms, line_no=applied_line_no):
            if str(candidate_effect.get("zone") or "") != "arts_strength":
                continue
            points = float(candidate_effect.get("rate") or 0.0)
            if points <= 0:
                continue
            if provider_key == source_key:
                self_points += points
            else:
                if candidate_effect.get('external_rdps_allowed') is False:
                    continue
                external_points[provider_key] += points
                external_approval_keys[provider_key].update(candidate_effect.get('rdps_whitelist_keys') or [])

    external_total = sum(external_points.values())
    if external_total <= 0:
        return [(source_key, final_rate, None)]

    without_external = final_rate * (
        _arts_strength_effect_multiplier(self_points)
        / _arts_strength_effect_multiplier(self_points + external_total)
    )
    external_rate = max(final_rate - without_external, 0.0)
    contributors: list[tuple[str, float, dict[str, Any] | None]] = [(source_key, without_external, None)]
    for provider_key, points in external_points.items():
        provider_rate = external_rate * (points / external_total)
        provenance = {
            "derived_from_zone": "arts_strength",
            "effect_event_key": effect_window.get("event_key"),
            "effect_source_character_key": source_key,
            "arts_strength_points": points,
            "arts_strength_self_points": self_points,
            "arts_strength_external_points": external_total,
            "arts_strength_whitelist_keys": sorted(external_approval_keys[provider_key]),
        }
        contributors.append((provider_key, provider_rate, provenance))
    return contributors



def _arts_strength_entry(
    *,
    source_type: str,
    source_name: str,
    label: str,
    value: Any,
    note: str = "",
) -> dict[str, Any] | None:
    points = _safe_positive_rate(value)
    if points is None:
        return None
    return {
        "source_type": source_type,
        "source_name": source_name,
        "label": label,
        "zone": "arts_strength",
        "zone_label": _RDPS_DEBUG_ZONE_LABELS["arts_strength"],
        "element": "all",
        "rate": points,
        "note": note,
    }
