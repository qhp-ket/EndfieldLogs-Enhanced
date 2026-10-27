"""Coordinate one hit through explicit evidence, baseline and allocation phases."""
from __future__ import annotations

from parser_core.allocation.baseline import attach_observed_baseline
from parser_core.allocation.baseline import check_remaining_baselines
from parser_core.allocation.baseline import resolve_attack_baseline
from parser_core.allocation.context import HitAllocation
from parser_core.allocation.context import prepare_allocation
from parser_core.allocation.contributors import collect_effect_contributors
from parser_core.allocation.debug import _rdps_contribution_rows
from parser_core.allocation.explanation import project_allocation_explanation
from parser_core.allocation.multipliers import compute_zone_multipliers
from parser_core.allocation.resistance import resolve_resistance_baseline
from parser_core.allocation.shares import allocate_log_marginal
from parser_core.allocation.stack_selection import select_stack_effects
from parser_core.ink_provenance import ink_allocation_result
from typing import Any


def _allocate_rdps_for_hit(
    hit: dict[str, Any],
    buff_windows: list[dict[str, Any]],
    *,
    include_debug: bool = False,
    buff_records_by_uid: dict[str, list[dict[str, Any]]] | None = None,
    condition_buff_records: list[dict[str, Any]] | None = None,
    condition_records_by_target: dict[str, list[dict[str, Any]]] | None = None,
    effect_window_indices: list[int] | None = None,
    condition_records_by_uid: dict[str, list[dict[str, Any]]] | None = None,
    condition_records_by_actor: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    ink_result = ink_allocation_result(hit, include_debug=include_debug)
    if ink_result is not None:
        ink_result['contributions_list'] = _rdps_contribution_rows(ink_result['contributions_map'], sort_by_value=True)
        return ink_result
    state = HitAllocation(
        hit=hit,
        buff_windows=buff_windows,
        include_debug=include_debug,
        buff_records_by_uid=buff_records_by_uid,
        condition_buff_records=condition_buff_records,
        condition_records_by_target=condition_records_by_target,
        effect_window_indices=effect_window_indices,
        condition_records_by_uid=condition_records_by_uid,
        condition_records_by_actor=condition_records_by_actor,
    )
    prepare_allocation(state)
    select_stack_effects(state)
    resolve_resistance_baseline(state)
    collect_effect_contributors(state)
    attach_observed_baseline(state)
    resolve_attack_baseline(state)
    check_remaining_baselines(state)
    compute_zone_multipliers(state)
    allocation_shares = allocate_log_marginal(
        state.attacker_key, state.hit_value, m_values=state.m_values, external_by_zone=state.external_by_zone,
        external_sum_by_zone=state.external_sum_by_zone, include_debug=state.include_debug,
    )
    state.product_external = allocation_shares.product_external
    state.attacker_share = allocation_shares.attacker_share
    state.external_pool = allocation_shares.external_pool
    state.normalized_contributions = allocation_shares.contributions
    state.result: dict[str, Any] = {
        "allocation_policy": "log_marginal_v1",
        "allocation_policy_basis": "accounting_convention",
        "contributions_map": state.normalized_contributions,
        "contributions_list": _rdps_contribution_rows(state.normalized_contributions, sort_by_value=True),
    }

    if not state.include_debug:
        return state.result
    return project_allocation_explanation(state)
