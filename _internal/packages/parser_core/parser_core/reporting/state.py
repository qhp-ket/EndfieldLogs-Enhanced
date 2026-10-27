"""Evidence owned by one report, after the caller isolates ingestion state."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping


@dataclass
class ReportState:
    """Keep evidence references and report-local replacements in one owner.

    The caller copies the ingestion snapshot before constructing this object.
    Collection identity and typed-root cache ownership remain unchanged here.
    """
    active_suits_by_char: dict[str, set[str]]
    active_weapons_by_char: dict[str, str]
    atb_gain_ms_by_char: dict[str, list[int]]
    atb_observations: list[dict[str, Any]]
    buff_attribute_refresh_events: list[dict[str, Any]]
    buff_root_action_indices: dict[int, tuple[Any, dict[int, list[tuple[dict[str, Any], bool]]], list[tuple[dict[str, Any], bool]]]]
    buff_starts: list[dict[str, Any]]
    challenge_pass_confirmed: bool
    char_skill_levels: dict[str, dict[str, int]]
    completion_source: str
    contract_tag_ids: list[int]
    contract_tag_score: int | None
    dungeon_context: tuple[str, str] | None
    dungeon_context_id: str | None
    dynamic_bb_events: list[dict[str, Any]]
    enemy_counter: Counter[str]
    first_context_ms: int | None
    first_hit_hint_ms: int | None
    first_party_action_ms: int | None
    game_timer_elapsed_ms: int | None
    game_timer_end_ms: int | None
    game_timer_start_ms: int | None
    game_timer_window_elapsed_ms: int | None
    hits: list[dict[str, Any]]
    last_context_ms: int | None
    last_hit_hint_ms: int | None
    live_timer_elapsed_ms: int | None
    loadout_by_char: dict[str, dict[str, Any]]
    loadout_groups: list[dict[str, Any]]
    official_pass_confirmed: bool
    official_timer_elapsed_ms: int | None
    official_timer_end_ms: int | None
    official_timer_start_ms: int | None
    packet_modifier_last_seen_by_uid: dict[str, int]
    packet_timer_elapsed_ms: int | None
    participant_totals: dict[str, dict[str, Any]]
    poise_damage_events: list[dict[str, Any]]
    reference_date: date
    roster_order: list[str]
    roster_seen: set[str]
    skill_casts: list[dict[str, Any]]
    timer_end_seen: bool
    timer_observed_times: dict[int, int]
    timer_start_seen: bool
    timer_window_valid: bool
    unresolved_buff_actions: list[dict[str, Any]]
    unresolved_hits: list[dict[str, Any]]

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> ReportState:
        return cls(
            active_suits_by_char=snapshot['active_suits_by_char'],
            active_weapons_by_char=snapshot['active_weapons_by_char'],
            atb_gain_ms_by_char=snapshot['atb_gain_ms_by_char'],
            atb_observations=snapshot['atb_observations'],
            buff_attribute_refresh_events=snapshot['buff_attribute_refresh_events'],
            buff_root_action_indices=snapshot['buff_root_action_indices'],
            buff_starts=snapshot['buff_starts'],
            challenge_pass_confirmed=snapshot['challenge_pass_confirmed'],
            char_skill_levels=snapshot['char_skill_levels'],
            completion_source=snapshot['completion_source'],
            contract_tag_ids=snapshot['contract_tag_ids'],
            contract_tag_score=snapshot['contract_tag_score'],
            dungeon_context=snapshot['dungeon_context'],
            dungeon_context_id=snapshot['dungeon_context_id'],
            dynamic_bb_events=snapshot['dynamic_bb_events'],
            enemy_counter=snapshot['enemy_counter'],
            first_context_ms=snapshot['first_context_ms'],
            first_hit_hint_ms=snapshot['first_hit_hint_ms'],
            first_party_action_ms=snapshot['first_party_action_ms'],
            game_timer_elapsed_ms=snapshot['game_timer_elapsed_ms'],
            game_timer_end_ms=snapshot['game_timer_end_ms'],
            game_timer_start_ms=snapshot['game_timer_start_ms'],
            game_timer_window_elapsed_ms=snapshot['game_timer_window_elapsed_ms'],
            hits=snapshot['hits'],
            last_context_ms=snapshot['last_context_ms'],
            last_hit_hint_ms=snapshot['last_hit_hint_ms'],
            live_timer_elapsed_ms=snapshot['live_timer_elapsed_ms'],
            loadout_by_char=snapshot['loadout_by_char'],
            loadout_groups=snapshot['loadout_groups'],
            official_pass_confirmed=snapshot['official_pass_confirmed'],
            official_timer_elapsed_ms=snapshot['official_timer_elapsed_ms'],
            official_timer_end_ms=snapshot['official_timer_end_ms'],
            official_timer_start_ms=snapshot['official_timer_start_ms'],
            packet_modifier_last_seen_by_uid=snapshot['packet_modifier_last_seen_by_uid'],
            packet_timer_elapsed_ms=snapshot['packet_timer_elapsed_ms'],
            participant_totals=snapshot['participant_totals'],
            poise_damage_events=snapshot['poise_damage_events'],
            reference_date=snapshot['reference_date'],
            roster_order=snapshot['roster_order'],
            roster_seen=snapshot['roster_seen'],
            skill_casts=snapshot['skill_casts'],
            timer_end_seen=snapshot['timer_end_seen'],
            timer_observed_times=snapshot['timer_observed_times'],
            timer_start_seen=snapshot['timer_start_seen'],
            timer_window_valid=snapshot['timer_window_valid'],
            unresolved_buff_actions=snapshot['unresolved_buff_actions'],
            unresolved_hits=snapshot['unresolved_hits'],
        )
