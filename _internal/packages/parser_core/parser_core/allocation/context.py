"""Context phase of per-hit allocation."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from parser_core.allocation.arts_strength import _is_arts_strength_damage_hit
from parser_core.allocation.attack_model import observed_attack_dependence
from parser_core.allocation.packet_evidence import _active_target_buff_ids_for_hit
from parser_core.allocation.packet_evidence import _matched_packet_defender_effect_signatures
from parser_core.allocation.packet_evidence import _packet_attr_allowed_effects
from parser_core.ingestion.fields import _coerce_optional_float
from typing import Any


@dataclass
class HitAllocation:
    """One ordered hit evaluation; evidence and accumulators never cross hits."""
    hit: dict[str, Any]
    buff_windows: list[dict[str, Any]]
    include_debug: bool
    buff_records_by_uid: dict[str, list[dict[str, Any]]] | None
    condition_buff_records: list[dict[str, Any]] | None
    condition_records_by_target: dict[str, list[dict[str, Any]]] | None
    effect_window_indices: list[int] | None
    condition_records_by_uid: dict[str, list[dict[str, Any]]] | None
    condition_records_by_actor: dict[str, list[dict[str, Any]]] | None
    attacker_key: str = field(init=False)
    target_enemy_key: str = field(init=False)
    hit_value: float = field(init=False)
    hit_ts_ms: int = field(init=False)
    damage_element: str | None = field(init=False)
    damage_school: str | None = field(init=False)
    arts_strength_damage_hit: bool = field(init=False)
    attack_kind: str = field(init=False)
    calculation: Any = field(init=False)
    packet_modifier_uids: dict[str, Any] = field(init=False)
    attacker_modifier_uids: set[str] = field(init=False)
    defender_modifier_uids: set[str] = field(init=False)
    packet_attr_details: dict[str, Any] = field(init=False)
    defender_allowed_effects: set[tuple[str, str]] = field(init=False)
    hit_line_no: int = field(init=False)
    invalid_numeric_allocation: bool = field(init=False)
    resistance_attr_type: int | None = field(init=False)
    resistance_rows: list[str] = field(init=False)
    effective_resistance: float | None = field(init=False)
    resistance_numerator: float | None = field(init=False)
    resistance_source: str = field(init=False)
    window_indices: range | list[int] = field(init=False)
    matched_packet_defender_effect_signatures: set[tuple[Any, ...]] = field(init=False)
    active_target_buff_ids: set[str] = field(init=False)
    effects_at_hit: dict[int, list[dict[str, Any]]] = field(init=False)
    attack_baseline_error: str | None = field(init=False)
    product_external: float = field(init=False)
    attacker_share: float = field(init=False)
    external_pool: float = field(init=False)
    normalized_contributions: dict[str, float] = field(init=False)
    external_by_zone: dict[str, list[tuple[str, float, dict[str, Any] | None]]] = field(init=False)
    self_by_zone: dict[str, float] = field(init=False)
    self_factor_by_zone: dict[str, float] = field(init=False)
    captured_by_attr_type: dict[int, float] = field(init=False)
    contributors_by_zone: dict[str, list[dict[str, Any]]] = field(init=False)
    ignored_effects: list[dict[str, Any]] = field(init=False)
    unresolved_stack_zones: set[str] = field(init=False)
    m_values: dict[str, float] = field(init=False)
    external_sum_by_zone: dict[str, float] = field(init=False)
    result: dict[str, Any] = field(init=False)


def prepare_allocation(state: HitAllocation) -> None:
    state.attacker_key = state.hit["character_key"]
    state.target_enemy_key = state.hit["target_enemy_key"]
    state.hit_value = float(state.hit["hit_value"])
    state.hit_ts_ms = state.hit["ts_ms"]
    state.damage_element = state.hit.get("damage_element")
    state.damage_school = state.hit.get("damage_school")
    state.arts_strength_damage_hit = _is_arts_strength_damage_hit(state.hit)
    # Attack percentage bonuses affect only attack-scaled damage. A dormant
    # custom calculation on a simple unit is not its active damage formula.
    state.attack_kind, state.calculation = observed_attack_dependence(state.hit)
    # The official text defines arts-strength as anomaly-only. A hit that
    # is not observed as anomaly damage does not consume this entry.
    state.packet_modifier_uids = state.hit.get("packet_modifier_uids") if isinstance(state.hit.get("packet_modifier_uids"), dict) else {}
    state.attacker_modifier_uids = {str(item) for item in state.packet_modifier_uids.get("attacker") or [] if str(item)}
    state.defender_modifier_uids = {str(item) for item in state.packet_modifier_uids.get("defender") or [] if str(item)}
    state.packet_attr_details = state.hit.get("packet_attr_details") if isinstance(state.hit.get("packet_attr_details"), dict) else {}
    state.defender_allowed_effects = _packet_attr_allowed_effects(state.packet_attr_details.get("defender") if isinstance(state.packet_attr_details, dict) else [])
    state.hit_line_no = int(state.hit.get("line_no") or 0)

    state.external_by_zone: dict[str, list[tuple[str, float, dict[str, Any] | None]]] = defaultdict(list)
    state.self_by_zone: dict[str, float] = defaultdict(float)
    state.self_factor_by_zone: dict[str, float] = defaultdict(lambda: 1.0)
    state.captured_by_attr_type: dict[int, float] = defaultdict(float)
    state.contributors_by_zone: dict[str, list[dict[str, Any]]] = defaultdict(list) if state.include_debug else {}
    state.ignored_effects: list[dict[str, Any]] = []
    state.invalid_numeric_allocation = False
    state.resistance_attr_type = {'physical': 94, 'natural': 95, 'cryst': 96,
                            'pulse': 97, 'fire': 98, 'ether': 99}.get(state.damage_element)
    state.resistance_rows = [str(token).partition(':')[2]
                       for token in (state.packet_attr_details.get('defender') or [])
                       if state.resistance_attr_type is not None
                       and str(token).partition(':')[0] == str(state.resistance_attr_type)]
    # This is the resistance observed in this damage operation, including
    # temporary modifications such as the attacker's resistance ignore.
    # ENTITY_STATS may predate the debuff and is not a replacement for it.
    resistance_values = [_coerce_optional_float(value) for row in state.resistance_rows for value in row.split(',')]
    state.effective_resistance = (resistance_values[0] if resistance_values and not state.hit.get('packet_attr_conflict')
                            and all(value is not None for value in resistance_values)
                            and len(set(resistance_values)) == 1 else None)
    state.resistance_numerator = 100.0 - state.effective_resistance if state.effective_resistance is not None else None
    state.resistance_source = f'PKT_ATTR.defender.attr{state.resistance_attr_type}'
    state.window_indices = range(len(state.buff_windows)) if state.effect_window_indices is None else state.effect_window_indices
    state.matched_packet_defender_effect_signatures = _matched_packet_defender_effect_signatures(
        hit=state.hit,
        buff_windows=[state.buff_windows[index] for index in state.window_indices],
        defender_modifier_uids=state.defender_modifier_uids,
    ) if bool(state.hit.get("packet_modifier_seen")) else set()
    defender_records = (state.condition_records_by_target.get(str(state.hit.get('target_enemy_key') or ''), [])
                        if state.condition_records_by_target is not None else state.condition_buff_records)
    state.active_target_buff_ids = _active_target_buff_ids_for_hit(state.hit, defender_records)
    state.hit["_active_target_buff_ids"] = sorted(state.active_target_buff_ids)
    if state.hit.get('source_actor_id'):
        attacker_records = (state.condition_records_by_target.get(str(state.hit.get('character_key') or ''), [])
                            if state.condition_records_by_target is not None else state.condition_buff_records)
        state.hit['_active_attacker_buff_ids'] = sorted(_active_target_buff_ids_for_hit(state.hit, attacker_records, side='attacker'))
