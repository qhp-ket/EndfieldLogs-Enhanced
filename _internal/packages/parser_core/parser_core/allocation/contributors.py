"""Contributors phase of per-hit allocation."""
from __future__ import annotations

from math import isfinite
from parser_core.allocation.arts_strength import _arts_strength_effect_contributors
from parser_core.allocation.context import HitAllocation
from parser_core.allocation.debug import _rdps_debug_record_applicable_effect
from parser_core.allocation.debug import _rdps_debug_record_arts_effect_provenance
from parser_core.allocation.packet_evidence import _packet_modifier_guard_signature
from parser_core.effects.conditions import _effect_condition_failure
from parser_core.effects.conditions import _effect_element_applies_to_hit
from parser_core.effects.conditions import _element_filter_debug_fields
from parser_core.effects.damage_types import _BUFF_EFFECT_SKILL_FILTER
from parser_core.effects.damage_types import _BUFF_SKILL_FILTER
from parser_core.effects.damage_types import _attr_type_applies_to_skill
from parser_core.effects.damage_types import _normalize_effect_element
from parser_core.effects.registry import _RDPS_ALLOCATABLE_ZONES
from parser_core.effects.window_identity import _window_uid_aliases
from parser_core.ingestion.fields import _coerce_optional_float
from typing import Any


from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WindowCandidate:
    window: dict[str, Any]
    effects: list[dict[str, Any]]
    applies_to_attacker: bool
    applies_to_enemy: bool
    uid_aliases: set[str]
    packet_uid_match: bool
    source_key: str


@dataclass(frozen=True, slots=True)
class MatchedEffect:
    zone: str
    rate: float
    attr_type: Any


def match_window(state: HitAllocation, index: int) -> WindowCandidate | None:
    window, window_effects = state.buff_windows[index], state.effects_at_hit[index]
    if not window_effects:
        if window.get('_enable_state_unobserved_at_hit'):
            state.hit['rdps_unresolved_effect_conditions'] = True
            if state.include_debug:
                state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                    'reason': 'unobserved_initial_buff_enable_state', 'reason_group': 'condition_unobservable'})
        if (not state.hit_line_no and (window.get('snapshot_update') and window.get('start_ts_ms') == state.hit_ts_ms
                                or window.get('snapshot_end_ts_ms') == state.hit_ts_ms)):
            state.hit['rdps_unresolved_effect_conditions'] = True
            if state.include_debug:
                state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                                        'reason': 'unresolved_buff_snapshot_order', 'reason_group': 'condition_unobservable'})
        return None
    window_start_ts_ms = int(window.get("start_ts_ms") or 0)
    if not (window_start_ts_ms <= state.hit_ts_ms <= int(window.get("end_ts_ms") or 0)):
        return None
    window_line_no = int(window.get("start_line_no") or window.get("line_no") or 0)
    if window_start_ts_ms == state.hit_ts_ms and state.hit_line_no and window_line_no and window_line_no > state.hit_line_no:
        return None
    if window_start_ts_ms == state.hit_ts_ms and str(window.get("event_key") or "") == str(state.hit.get("skill_key") or ""):
        return None
    skill_family_key = window.get("skill_family_key")
    if skill_family_key and state.hit.get("skill_family_key") != skill_family_key:
        return None
    skill_filter = _BUFF_SKILL_FILTER.get(window["event_key"])
    if skill_filter and not skill_filter.search(str(state.hit.get("skill_key") or "")):
        return None

    applies_to_attacker = window["target_character_key"] == state.attacker_key
    applies_to_enemy = bool(state.target_enemy_key) and window["target_character_key"] == state.target_enemy_key
    if not applies_to_attacker and not applies_to_enemy:
        return None

    window_uid_aliases = _window_uid_aliases(window)
    packet_uid_match = bool(window_uid_aliases & state.defender_modifier_uids)
    if applies_to_attacker:
        attacker_instance = str(state.hit.get("source_actor_id") or "")
        window_instance = str(window.get("target_actor_id") or "")
        if attacker_instance and window_instance and attacker_instance != window_instance:
            if window_uid_aliases & state.attacker_modifier_uids:
                state.hit["rdps_unresolved_target_binding"] = True
            if state.include_debug:
                state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                                        'reason': 'buff_owner_instance_mismatch'})
            return None
    if applies_to_enemy:
        target_instance = str(state.hit.get("target_actor_id") or "")
        window_instance = str(window.get("target_actor_id") or "")
        if target_instance and window_instance and target_instance != window_instance:
            if packet_uid_match:
                state.hit["rdps_unresolved_target_binding"] = True
            return None
        if not (target_instance and window_instance) and not packet_uid_match:
            state.hit["rdps_unresolved_target_binding"] = True
            return None

    source_key = window["source_character_key"]
    if not source_key:
        return None
    return WindowCandidate(window, window_effects, applies_to_attacker, applies_to_enemy, window_uid_aliases, packet_uid_match, source_key)


def match_effect_recipient(state: HitAllocation, candidate: WindowCandidate, effect: dict[str, Any]) -> MatchedEffect | None:
    window = candidate.window
    applies_to_attacker, applies_to_enemy = candidate.applies_to_attacker, candidate.applies_to_enemy
    window_uid_aliases, packet_uid_match = candidate.uid_aliases, candidate.packet_uid_match
    zone = effect["zone"]
    if zone == 'atk' and state.attack_kind in {'independent', 'unknown'}:
        if state.attack_kind == 'unknown':
            state.hit['rdps_unresolved_effect_conditions'] = True
        if state.include_debug:
            state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                'zone': 'atk', 'reason': 'damage_not_scaled_by_attack' if state.attack_kind == 'independent'
                else 'attack_damage_calculation_unresolved'})
        return None
    if zone in state.unresolved_stack_zones:
        if state.include_debug:
            state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                'zone': zone, 'reason': 'unresolved_stack_zone_baseline', 'reason_group': 'condition_unobservable'})
        return None
    rate = _coerce_optional_float(effect.get('rate'))
    if rate is None:
        state.invalid_numeric_allocation = True
        if state.include_debug:
            state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                                    'reason': 'invalid_effect_rate'})
        return None
    element = effect.get("element")
    required_side = ('defender' if zone in {'vuln_taken', 'fragile', 'res', 'prod_vuln_taken'} else
                     'attacker' if zone in {'atk', 'dmg_inc', 'amp', 'combo', 'arts_strength', 'crit', 'prod_dmg_inc'} else None)
    if 'recipient_side' in effect:
        if effect['recipient_side'] not in {'attacker', 'defender'}:
            state.hit['rdps_unresolved_effect_conditions'] = True
            return None
        required_side = effect['recipient_side']
    if ((required_side == 'defender' and not applies_to_enemy)
            or (required_side == 'attacker' and not applies_to_attacker)):
        if state.include_debug:
            state.ignored_effects.append({
                **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope='ignored'),
                'reason': 'effect_recipient_side_mismatch', 'required_side': required_side,
            })
        return None
    packet_uid_restricted = (
        bool(state.hit.get("packet_modifier_seen"))
        and applies_to_enemy
        and bool(window_uid_aliases)
        and zone == "vuln_taken"
        and _packet_modifier_guard_signature(effect) in state.matched_packet_defender_effect_signatures
    )
    if packet_uid_restricted and not packet_uid_match:
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    "reason": "packet_defender_uid_suppressed",
                    "reason_group": "packet_modifier_uid_mismatch",
                    "packet_modifier_guard": "defender_uid_selection",
                    "packet_modifier_seen": True,
                    "packet_modifier_uids": {
                        "attacker": sorted(state.attacker_modifier_uids),
                        "defender": sorted(state.defender_modifier_uids),
                    },
                    "candidate_uids": sorted(window_uid_aliases),
                }
            )
        return None
    effect_skill_filter = _BUFF_EFFECT_SKILL_FILTER.get((window["event_key"], zone))
    if effect_skill_filter and not effect_skill_filter.search(str(state.hit.get("skill_key") or "")):
        return None
    attr_type = effect.get("attr_type")
    if isinstance(attr_type, int):
        attr_applies = _attr_type_applies_to_skill(
            attr_type, None, damage_decorate_mask=state.hit.get('damage_decorate_mask'),
            static_damage_decorate_mask=state.hit.get('static_damage_decorate_mask'),
            static_damage_decorate_mask_source=state.hit.get('static_damage_decorate_mask_source'))
        if attr_applies is None:
            state.hit['rdps_unresolved_effect_conditions'] = True
        if attr_applies is not True:
            if state.include_debug:
                state.ignored_effects.append({
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope='ignored'),
                    'reason': 'attribute_damage_mask_missing' if attr_applies is None else 'attribute_damage_mask_filtered',
                    'reason_group': 'condition_unobservable' if attr_applies is None else 'condition_unsatisfied',
                })
            return None
    return MatchedEffect(zone, rate, attr_type)


def effect_is_allocatable(state: HitAllocation, candidate: WindowCandidate, effect: dict[str, Any], matched: MatchedEffect) -> bool:
    window, source_key = candidate.window, candidate.source_key
    applies_to_enemy = candidate.applies_to_enemy
    zone, rate = matched.zone, matched.rate
    if zone == "crit":
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    "reason": "crit_not_allocated",
                }
            )
        return False
    if zone not in _RDPS_ALLOCATABLE_ZONES:
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    "reason": "resistance_counterfactual_unresolved" if zone == 'res' else "utility_not_allocated",
                }
            )
        return False
    if zone == "arts_strength" and not state.arts_strength_damage_hit:
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    "reason": "arts_strength_only_affects_anomaly_damage",
                }
            )
        return False
    if rate <= 0:
        return False
    if not _effect_element_applies_to_hit(effect, state.damage_element, state.damage_school):
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    **_element_filter_debug_fields(effect["element"], state.damage_element, state.damage_school),
                }
            )
        return False
    condition_failure = _effect_condition_failure(effect, state.hit)
    if condition_failure:
        if condition_failure.get("reason_group") == "condition_unobservable":
            state.hit["rdps_unresolved_effect_conditions"] = True
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    **condition_failure,
                }
            )
        return False
    if (
        source_key != state.attacker_key
        and applies_to_enemy
        and state.defender_allowed_effects
        and not state.defender_modifier_uids
        and (zone, _normalize_effect_element(effect["element"])) not in state.defender_allowed_effects
    ):
        if state.include_debug:
            state.ignored_effects.append(
                {
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope="ignored"),
                    "reason": "packet_attr_mismatch",
                }
            )
        return False
    if zone == 'res':
        if state.damage_element in {'real', 'lifedrain'}:
            return False
        if (state.resistance_numerator is None or not isfinite(state.resistance_numerator)
                or state.resistance_numerator <= 0):
            state.hit['rdps_unresolved_effect_conditions'] = True
            if state.include_debug:
                state.ignored_effects.append({
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope='ignored'),
                    'reason': 'resistance_counterfactual_unresolved',
                    'detail': 'missing_or_conflicting_hit_resistance',
                })
            return False
    return True


def record_effect_contributions(state: HitAllocation, candidate: WindowCandidate, effect: dict[str, Any], matched: MatchedEffect) -> None:
    window, source_key = candidate.window, candidate.source_key
    applies_to_attacker, applies_to_enemy = candidate.applies_to_attacker, candidate.applies_to_enemy
    zone, rate, attr_type = matched.zone, matched.rate, matched.attr_type
    effect_contributors = (
        _arts_strength_effect_contributors(
            effect_window=window,
            effect=effect,
            buff_windows=state.buff_windows,
        )
        if applies_to_enemy
        else [(source_key, rate, None)]
    )
    for contributor_key, contributor_rate, provenance in effect_contributors:
        contributor_rate = _coerce_optional_float(contributor_rate)
        if contributor_rate is None:
            state.invalid_numeric_allocation = True
            continue
        if contributor_rate <= 0:
            continue
        if contributor_key != state.attacker_key and effect.get('external_rdps_allowed') is False:
            state.hit['rdps_unresolved_whitelist_effect'] = True
            if state.include_debug:
                state.ignored_effects.append({
                    **_rdps_debug_record_applicable_effect(window=window, effect=effect, scope='ignored'),
                    'reason': 'external_effect_not_whitelisted',
                })
            continue
        # Subtract only effects actually retained in the model from
        # the observed final attribute. Rejected external effects
        # remain in the attacker's baseline; they get no credit.
        if applies_to_attacker and isinstance(attr_type, int):
            state.captured_by_attr_type[attr_type] += contributor_rate
        scope = "self" if contributor_key == state.attacker_key else "external"
        record = (
            _rdps_debug_record_arts_effect_provenance(
                effect_window=window,
                effect=effect,
                source_key=contributor_key,
                rate=contributor_rate,
                provenance=provenance,
                scope=scope,
            )
            if state.include_debug
            else None
        )
        if contributor_key == state.attacker_key:
            if zone.startswith('prod_'):
                state.self_factor_by_zone[zone] *= 1.0 + contributor_rate
            else:
                state.self_by_zone[zone] += contributor_rate
        else:
            state.external_by_zone[zone].append((contributor_key, contributor_rate, record))
        if state.include_debug and record is not None:
            state.contributors_by_zone[zone].append(record)


def collect_effect_contributors(state: HitAllocation) -> None:
    for index in state.window_indices:
        candidate = match_window(state, index)
        if candidate is None:
            continue
        for effect in candidate.effects:
            matched = match_effect_recipient(state, candidate, effect)
            if matched is None:
                continue
            if not effect_is_allocatable(state, candidate, effect, matched):
                continue
            record_effect_contributions(state, candidate, effect, matched)
