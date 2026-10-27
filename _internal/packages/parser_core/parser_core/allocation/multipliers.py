"""Multipliers phase of per-hit allocation."""
from __future__ import annotations

from math import isfinite
from parser_core.allocation.arts_strength import _arts_strength_damage_multiplier
from parser_core.allocation.context import HitAllocation
from typing import Any


def compute_zone_multipliers(state: HitAllocation) -> None:
    state.m_values: dict[str, float] = {}
    state.external_sum_by_zone: dict[str, float] = {}
    combined_multiplier = 1.0
    if any(not isfinite(value) for value in (*state.self_by_zone.values(), *state.self_factor_by_zone.values(), *state.captured_by_attr_type.values())):
        state.invalid_numeric_allocation = True
    for zone, contributors in state.external_by_zone.items():
        if zone == 'atk' and state.attack_baseline_error:
            continue
        external_sum = sum(rate for _, rate, _ in contributors)
        if not isfinite(external_sum):
            state.invalid_numeric_allocation = True
            break
        if external_sum <= 0:
            continue
        self_sum = state.self_by_zone.get(zone, 0.0)
        if not isfinite(self_sum) or (100.0 if zone == 'arts_strength' else 1.0) + self_sum <= 0:
            state.invalid_numeric_allocation = True
            break
        if zone.startswith('prod_'):
            m_z = 1.0
            for _, rate, _ in contributors:
                m_z *= 1.0 + rate
        elif zone == "arts_strength":
            m_z = (
                _arts_strength_damage_multiplier(self_sum + external_sum)
                / _arts_strength_damage_multiplier(self_sum)
            ) ** (state.hit.get('arts_strength_damage_factor_count') or 1)
        elif zone == 'res':
            # Rates in this lane are positive resistance points. Remove only
            # approved external points from the observed resistance factor;
            # own reductions/ignore and rejected sources stay in the baseline.
            denominator = state.resistance_numerator - external_sum
            if not isfinite(denominator) or denominator <= 0:
                state.hit['rdps_unresolved_effect_conditions'] = True
                if state.include_debug:
                    state.ignored_effects.append({'zone': 'res', 'reason': 'resistance_counterfactual_unresolved',
                                            'detail': 'nonpositive_without_external_resistance_factor'})
                continue
            m_z = state.resistance_numerator / denominator
        else:
            m_z = (1.0 + self_sum + external_sum) / (1.0 + self_sum)
        if not isfinite(m_z):
            state.invalid_numeric_allocation = True
            break
        # DPD buckets remain a cross-check. An unexplained remainder cannot
        # become a self multiplier or calibrate the externally proven rate.
        if m_z <= 1.0:
            continue
        state.external_sum_by_zone[zone] = external_sum
        state.m_values[zone] = m_z
        combined_multiplier *= m_z
        if not isfinite(combined_multiplier):
            state.invalid_numeric_allocation = True
            break

    if state.invalid_numeric_allocation:
        # Invalid or overflowing coefficients cannot erase observed damage.
        # Keep the hit with its attacker and expose the failed allocation.
        state.hit['rdps_invalid_numeric_allocation'] = True
        state.hit['rdps_unresolved_effect_conditions'] = True
        state.m_values.clear()
        state.external_sum_by_zone.clear()
        state.external_by_zone.clear()
        state.self_by_zone.clear()
        state.self_factor_by_zone.clear()
        state.contributors_by_zone.clear()
        if state.include_debug:
            state.ignored_effects.append({'reason': 'invalid_numeric_allocation', 'reason_group': 'condition_unobservable'})
