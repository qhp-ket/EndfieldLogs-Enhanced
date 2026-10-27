"""Baseline phase of per-hit allocation."""
from __future__ import annotations

from math import isfinite
from parser_core.allocation.context import HitAllocation
from parser_core.allocation.debug import _rdps_debug_record_baseline_self
from parser_core.allocation.debug import _rdps_debug_record_static_self
from parser_core.allocation.packet_evidence import _dpd_bucket_value_for_zone
from parser_core.allocation.static_loadout import _ATTR_TYPE_TO_EFFECT
from parser_core.allocation.static_loadout import _static_entry_applies_to_hit
from parser_core.effects.damage_types import _attr_type_applies_to_skill
from parser_core.effects.damage_types import _effect_applies_to_damage_element
from parser_core.effects.packet_mapping import _DPD_ZONE_BUCKETS
from parser_core.ingestion.fields import _coerce_optional_float
from typing import Any


def attach_observed_baseline(state: HitAllocation) -> None:
    observed_final_attr_types: set[int] = set()
    for raw_attr_type, final_value in (state.hit.get("baseline") or {}).items():
        try:
            attr_type = int(raw_attr_type)
        except (TypeError, ValueError):
            continue
        if attr_type == 2:
            continue
        mapping = _ATTR_TYPE_TO_EFFECT.get(attr_type)
        if mapping is None:
            continue
        final_rate = _coerce_optional_float(final_value)
        if final_rate is None or final_rate < 0:
            state.hit['rdps_unresolved_effect_conditions'] = True
            continue
        zone, element = mapping
        if zone == "crit":
            continue
        observed_final_attr_types.add(attr_type)
        if final_rate == 0:
            continue
        attr_applies = _attr_type_applies_to_skill(
            attr_type, None, damage_decorate_mask=state.hit.get('damage_decorate_mask'),
            static_damage_decorate_mask=state.hit.get('static_damage_decorate_mask'),
            static_damage_decorate_mask_source=state.hit.get('static_damage_decorate_mask_source'))
        if attr_applies is None and element == state.damage_element:
            # An element-specific attribute has an exact element match; the
            # decorate mask is only needed for broader skill-category rules.
            attr_applies = True
        if attr_applies is None:
            state.hit['rdps_unresolved_effect_conditions'] = True
        if attr_applies is not True:
            continue
        if not _effect_applies_to_damage_element(element, state.damage_element, state.damage_school):
            continue
        baseline_rate = final_rate - state.captured_by_attr_type.get(attr_type, 0.0)
        if baseline_rate < 0:
            state.hit['rdps_unresolved_effect_conditions'] = True
            continue
        if baseline_rate == 0:
            continue
        state.self_by_zone[zone] += baseline_rate
        if state.include_debug:
            state.contributors_by_zone[zone].append(
                _rdps_debug_record_baseline_self(
                    hit=state.hit,
                    attr_type=attr_type,
                    zone=zone,
                    element=str(element or "all"),
                    rate=baseline_rate,
                    final_value=final_rate,
                    captured=state.captured_by_attr_type.get(attr_type, 0.0),
                )
            )

    for entry in state.hit.get("static_multiplier_entries") or []:
        if not isinstance(entry, dict) or not _static_entry_applies_to_hit(entry, state.hit):
            continue
        if entry.get('zone') == 'atk' and state.attack_kind == 'independent':
            continue
        if entry.get('attr_type') in observed_final_attr_types:
            # The per-hit final attribute already contains this static source.
            continue
        zone = str(entry.get("zone") or "")
        rate = _coerce_optional_float(entry.get('rate'))
        if rate is None:
            state.invalid_numeric_allocation = True
            continue
        state.self_by_zone[zone] += rate
        if state.include_debug:
            state.contributors_by_zone[zone].append(_rdps_debug_record_static_self(hit=state.hit, entry=entry))


def resolve_attack_baseline(state: HitAllocation) -> None:
    attack_extra_baseline = 0.0
    state.attack_baseline_error = None
    flat_attack = _coerce_optional_float(state.hit.get('static_flat_attack', 0.0))
    base_attack = _coerce_optional_float(state.hit.get('base_attack_for_percent'))
    if flat_attack is None or flat_attack < 0:
        state.attack_baseline_error = 'invalid_flat_attack_baseline'
    elif flat_attack > 0:
        if base_attack is None or base_attack <= 0:
            state.attack_baseline_error = 'missing_base_attack_for_flat_addition'
        else:
            attack_extra_baseline += flat_attack / base_attack
    if state.attack_kind == 'affine':
        custom = state.calculation['atkCalculation']
        params = {}
        resource = (state.calculation.get('sourceProof') or {}).get('resourceId')
        owner_uid = str(state.hit.get('event_inst_id') or '')
        stamp = (state.hit_ts_ms, state.hit_line_no)
        owner_records = (state.condition_records_by_uid.get(owner_uid, [])
                         if state.condition_records_by_uid is not None else state.condition_buff_records)
        records = [record for record in owner_records or []
                   if str(record.get('uid') or '') == owner_uid and record.get('event_key') == resource
                   and (int(record.get('ts_ms') or 0), int(record.get('line_no') or 0)) <= stamp
                   and (record.get('end_ts_ms') is None or stamp < (int(record['end_ts_ms']), int(record.get('end_line_no') or 2**63-1)))
                   and (record.get('snapshot_end_ts_ms') is None or stamp < (int(record['snapshot_end_ts_ms']), int(record.get('snapshot_end_line_no') or 2**63-1)))]
        for key in ('multiplier', 'addition'):
            parameter = custom.get(key) or {}
            raw = parameter.get('value') if parameter.get('useBlackboardKey') is False else (
                (records[0].get('bb_values') or {}).get(parameter.get('blackboardKey'))
                if parameter.get('useBlackboardKey') is True and len(records) == 1 else None)
            params[key] = _coerce_optional_float(raw)
        if params['addition'] is None:
            state.attack_baseline_error = 'missing_damage_base_addition'
        elif params['addition'] != 0:
            ability_factor = _coerce_optional_float(state.hit.get('attack_ability_factor'))
            coefficient = params['multiplier']
            if (base_attack is None or base_attack <= 0 or ability_factor is None or ability_factor <= 0
                    or coefficient is None or coefficient <= 0):
                state.attack_baseline_error = 'missing_attack_scale_for_fixed_damage'
            else:
                scale = base_attack * ability_factor * coefficient
                if not isfinite(scale) or scale <= 0:
                    state.attack_baseline_error = 'invalid_attack_scale_for_fixed_damage'
                else:
                    attack_extra_baseline += params['addition'] / scale
    if not isfinite(attack_extra_baseline):
        state.attack_baseline_error = 'invalid_attack_addition_ratio'
    if state.attack_baseline_error:
        if state.external_by_zone.get('atk'):
            state.hit['rdps_unresolved_effect_conditions'] = True
            if state.include_debug:
                state.ignored_effects.append({'zone': 'atk', 'reason': state.attack_baseline_error})
    elif attack_extra_baseline != 0:
        state.self_by_zone['atk'] += attack_extra_baseline
        if state.include_debug:
            state.contributors_by_zone['atk'].append(_rdps_debug_record_static_self(hit=state.hit, entry={
                'zone': 'atk', 'element': 'all', 'rate': attack_extra_baseline,
                'source_type': 'fixed_attack_basis', 'source_name': '固定攻击与基础伤害项',
                'evidence_kind': 'explicit_fixed_terms_normalization', 'base_attack': base_attack,
                'flat_attack': flat_attack}))


def check_remaining_baselines(state: HitAllocation) -> None:
    if state.arts_strength_damage_hit:
        for entry in state.hit.get("static_arts_strength_entries") or []:
            if not isinstance(entry, dict):
                continue
            points = _coerce_optional_float(entry.get('rate'))
            if points is None:
                state.invalid_numeric_allocation = True
                continue
            if points <= 0:
                continue
            state.self_by_zone["arts_strength"] += points
            if state.include_debug:
                state.contributors_by_zone["arts_strength"].append(
                    _rdps_debug_record_static_self(hit=state.hit, entry=entry)
                )

    for zone in _DPD_ZONE_BUCKETS:
        bucket_value = _dpd_bucket_value_for_zone(zone, state.hit.get("dpd_raw"))
        if bucket_value is None:
            continue
        recognized_total = state.self_by_zone.get(zone, 0.0) + sum(
            rate for _, rate, _ in state.external_by_zone.get(zone, [])
        )
        residual = (bucket_value - 1.0) - recognized_total
        if abs(residual) > 0.003:
            state.hit["rdps_unresolved_dpd_residual"] = True
