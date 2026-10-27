"""Stack selection phase of per-hit allocation."""
from __future__ import annotations

from collections import defaultdict
from parser_core.allocation.context import HitAllocation
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.conditions import _effect_element_applies_to_hit
from parser_core.effects.evaluation import _window_effects_at_ts
from parser_core.effects.stacking_rules import _buff_stack_limit
from parser_core.effects.window_identity import _buff_window_stack_group_key
from parser_core.ingestion.fields import _positive_int
from typing import Any


def select_stack_effects(state: HitAllocation) -> None:
    for window in state.buff_windows:
        window['_enable_state_unobserved_at_hit'] = False
        window['_effect_state_unresolved_at_hit'] = False
        window['_buff_enabled_at_hit'] = None
    state.effects_at_hit = {index: _window_effects_at_ts(state.buff_windows[index], state.hit_ts_ms, line_no=state.hit_line_no,
                                           packet_seq_id=state.hit.get('packet_seq_id'),
                                           packet_session_id=state.hit.get('packet_session_id')) for index in state.window_indices}
    stack_groups: defaultdict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    disabled_self_groups: defaultdict[tuple[str, str, str, str], list[int]] = defaultdict(list)
    state.unresolved_stack_zones: set[str] = set()
    for index in state.window_indices:
        window, effects = state.buff_windows[index], state.effects_at_hit[index]
        owner = window.get('target_character_key')
        actor_id = str(state.hit.get('source_actor_id' if owner == state.attacker_key else 'target_actor_id') or '')
        window_actor_id = str(window.get('target_actor_id') or '')
        if owner not in {state.attacker_key, state.target_enemy_key} or (actor_id and window_actor_id and actor_id != window_actor_id):
            continue
        if window.get('_effect_state_unresolved_at_hit'):
            potential_effects = list(window.get('zone_effects') or []) + list(window.get('dynamic_effects') or [])
            zones = {str(effect['zone']) for effect in potential_effects
                     if _effect_element_applies_to_hit(effect, state.damage_element, state.damage_school)}
            if zones:
                state.unresolved_stack_zones.update(zones)
                state.hit['rdps_unresolved_effect_conditions'] = True
                if state.include_debug:
                    state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                        'reason': 'unresolved_buff_state_zone_baseline', 'reason_group': 'condition_unobservable'})
        if window.get('_buff_enabled_at_hit') is False and window.get('source_character_key') == state.attacker_key:
            disabled_self_groups[_buff_window_stack_group_key(window)].append(index)
        if not effects:
            continue
        stack_groups[_buff_window_stack_group_key(window)].append(index)
    for group, indices in stack_groups.items():
        policies, limits = set(), set()
        for index in indices:
            window = state.buff_windows[index]
            root = _load_current_buff_roots().get(str(window.get('event_key') or ''))
            settings = root.get('stackingSettings') if isinstance(root, dict) else None
            policies.add(settings.get('stackingType') if isinstance(settings, dict) else window.get('stacking_type'))
            limits.add(_buff_stack_limit(window.get('event_key'), window.get('bb_values'))
                       if isinstance(settings, dict) else _positive_int(window.get('stack_limit')))
        if policies == {'Unlimited'}:
            continue
        if (policies & {'HighPriority', 'HighPriorityWithMaxStack'} and disabled_self_groups.get(group)
                and any(state.buff_windows[i].get('source_character_key') != state.attacker_key for i in indices)):
            # Removing an external priority winner may reactivate a suppressed
            # self buff. Its counterfactual selection has not been proved.
            for index in indices + disabled_self_groups[group]:
                window = state.buff_windows[index]
                potential_effects = list(window.get('zone_effects') or []) + list(window.get('dynamic_effects') or [])
                zones = {str(effect['zone']) for effect in potential_effects
                         if _effect_element_applies_to_hit(effect, state.damage_element, state.damage_school)}
                if zones:
                    state.unresolved_stack_zones.update(zones)
                    state.hit['rdps_unresolved_effect_conditions'] = True
                    window['rdps_unresolved_stack_evidence'] = True
                    if state.include_debug:
                        state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                            'reason': 'unresolved_priority_self_baseline', 'reason_group': 'condition_unobservable'})
        uids = {str(state.buff_windows[i].get('uid') or f'unknown:{i}') for i in indices}
        if len(uids) <= 1:
            continue
        limit = next(iter(limits)) if len(limits) == 1 else None
        if len(policies) == 1 and limit is not None and len(uids) <= limit:
            continue
        # No enabled winner is implied by age, UID ordering, or BB magnitude.
        # Omit this zone too when a competing self buff makes its baseline
        # unknown; allocating another external effect against zero would lie.
        for index in indices:
            window = state.buff_windows[index]
            zones = {str(effect['zone']) for effect in state.effects_at_hit[index]
                     if _effect_element_applies_to_hit(effect, state.damage_element, state.damage_school)}
            if not zones:
                continue
            state.unresolved_stack_zones.update(zones)
            window['rdps_unresolved_stack_evidence'] = True
            state.hit['rdps_unresolved_effect_conditions'] = True
            if state.include_debug:
                state.ignored_effects.append({'uid': window.get('uid'), 'event_key': window.get('event_key'),
                    'reason': 'unresolved_buff_stack_selection', 'reason_group': 'condition_unobservable',
                    'stack_group': list(group), 'candidate_uids': sorted(uids)})
