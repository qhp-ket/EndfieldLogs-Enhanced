"""Resistance phase of per-hit allocation."""
from __future__ import annotations

from math import isfinite
from parser_core.allocation.context import HitAllocation
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.conditions import _effect_element_applies_to_hit
from parser_core.ingestion.fields import _coerce_optional_float
from typing import Any


def resolve_resistance_baseline(state: HitAllocation) -> None:
    if (state.effective_resistance is None and not state.resistance_rows and state.resistance_attr_type is not None
            and state.hit.get('packet_attribute_report_present') is True
            and not state.hit.get('packet_attribute_report_unresolved') and 'res' not in state.unresolved_stack_zones):
        initial = _coerce_optional_float((state.hit.get('target_resistance_points') or {}).get(state.damage_element))
        snapshot_ts = state.hit.get('target_stats_snapshot_ts_ms')
        snapshot_line = state.hit.get('target_stats_snapshot_line_no')
        target_id = str(state.hit.get('target_actor_id') or '')
        if (initial is not None and type(snapshot_ts) is int and type(snapshot_line) is int
                and target_id and not state.hit.get('rdps_unresolved_target_binding')):
            baseline_stamp = (snapshot_ts, snapshot_line)
            current_stamp = (state.hit_ts_ms, state.hit_line_no)
            known = baseline_stamp <= current_stamp
            persistent_points = 0.0
            observed_persistent = False
            covered_instances = set()
            for index, candidate in enumerate(state.buff_windows):
                effects = state.effects_at_hit.get(index, [])
                if (str(candidate.get('target_actor_id') or '') != target_id
                        or candidate.get('target_character_key') != state.target_enemy_key):
                    continue
                specs = [spec for spec in candidate.get('dynamic_effects') or []
                         if 'parameter_snapshots' in spec and spec.get('zone') == 'res'
                         and _effect_element_applies_to_hit(spec, state.damage_element, state.damage_school)]
                if not specs:
                    continue
                covered_instances.add((str(candidate.get('uid') or ''), candidate.get('start_ts_ms'), candidate.get('start_line_no')))
                start_stamp = (int(candidate.get('start_ts_ms') or 0), int(candidate.get('start_line_no') or 0))
                end_stamp = (int(candidate.get('end_ts_ms') or 0), int(candidate.get('end_line_no') or 2**63 - 1))
                if start_stamp <= baseline_stamp < end_stamp:
                    known = False  # The snapshot may already include this Buff.
                if candidate.get('_effect_state_unresolved_at_hit'):
                    known = False
                if start_stamp <= current_stamp <= end_stamp:
                    observed_persistent = True
                    persistent_points += sum(effect['rate'] for effect in effects
                        if effect.get('resistance_point_source') == 'packet_bb_update_and_refresh'
                        and _effect_element_applies_to_hit(effect, state.damage_element, state.damage_school))
            attribute_name = {'physical': 'PhysicalResistance', 'natural': 'NaturalResistance',
                              'cryst': 'CrystResistance', 'pulse': 'PulseResistance',
                              'fire': 'FireResistance', 'ether': 'EtherResistance'}[state.damage_element]
            target_records = (state.condition_records_by_actor.get(target_id, [])
                              if state.condition_records_by_actor is not None else state.condition_buff_records)
            for candidate in target_records or []:
                if (str(candidate.get('target_actor_id') or '') != target_id
                        or (str(candidate.get('uid') or ''), candidate.get('ts_ms'), candidate.get('line_no')) in covered_instances):
                    continue
                start_stamp = (int(candidate.get('ts_ms') or 0), int(candidate.get('line_no') or 0))
                end_stamp = (int(candidate.get('end_ts_ms') or state.hit_ts_ms), int(candidate.get('end_line_no') or 2**63 - 1))
                if not (start_stamp <= baseline_stamp < end_stamp or start_stamp <= current_stamp < end_stamp):
                    continue
                root = _load_current_buff_roots().get(str(candidate.get('event_key') or '')) or {}
                if any(modifier.get('attributeType') == attribute_name
                       for modifier in (root.get('attributeModifier') or {}).get('attributeModifiers') or []):
                    known = False  # Another observed persistent change is not modeled here.
            if known and observed_persistent and isfinite(persistent_points):
                state.effective_resistance = initial - persistent_points
                state.resistance_numerator = 100.0 - state.effective_resistance
                state.resistance_source = 'ENTITY_STATS+packet_bb_refresh+complete_instant_report'
