"""Persistent trace evidence owned by one ordered ingestion stream.

Snapshots expose the existing shallow projection; report preparation isolates it
before finalization. Each stream owns its indexes, pending evidence and clocks.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import copy
from datetime import date
from typing import Any

from parser_core.catalog.dungeons import _resolve_dungeon_context
from parser_core.reporting.totals import _new_participant_totals, _new_skill_totals


class IngestionState:
    def __init__(
        self, *, reference_date: date, first_hit_hint_ms: int | None,
        last_hit_hint_ms: int | None, context_enemy_hint: str | None,
        trace_identity_inference_seen: bool,
        loadout_override_by_char: dict[str, dict[str, Any]] | None,
        critical_attributes_override_by_actor: dict[str, dict[str, Any]] | None,
    ) -> None:
        self.reference_date = reference_date
        self.first_hit_hint_ms = first_hit_hint_ms
        self.last_hit_hint_ms = last_hit_hint_ms
        self.context_enemy_hint = context_enemy_hint
        self.trace_identity_inference_seen = trace_identity_inference_seen
        self.hits: list[dict[str, Any]] = []
        self.unresolved_hits: list[dict[str, Any]] = []
        self.unresolved_buff_actions: list[dict[str, Any]] = []
        self.hits_by_seq: dict[int, dict[str, Any]] = {}
        self.critical_stats_by_actor = copy.deepcopy(critical_attributes_override_by_actor or {})
        self.baseline_by_character: dict[str, dict[int, float]] = {}
        self.buff_starts: list[dict[str, Any]] = []
        self.roster_order: list[str] = []
        self.roster_seen: set[str] = set()
        self.participant_totals = _new_participant_totals()
        self.skill_totals = _new_skill_totals()
        self.enemy_counter: Counter[str] = Counter()
        self.last_enemy_hp_by_target: dict[str, int] = {}
        self.active_buff_starts_by_uid: dict[str, dict[str, Any]] = {}
        self.packet_modifier_last_seen_by_uid: dict[str, int] = {}
        self.pending_attr_mods: dict[str, list[dict[str, str]]] = defaultdict(list)
        self.pending_buff_record: dict[str, Any] | None = None
        self.last_chr_src_on_owner: dict[str, tuple[str, int]] = {}
        self.recent_skill_casts_by_char: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.skill_casts: list[dict[str, Any]] = []
        self.active_skill_casts_by_inst: dict[str, dict[str, Any]] = {}
        # ATB_UPDATE（技力更新，v34+ 客户端 BattleOpUpdateAtbInfo）：主控角色重击回技力
        # = reason=AddValue 正 delta。排轴导出据此标记「回能量重击」区分主控 vs AI。
        # 按角色收集技力增加时刻。
        self.atb_gain_ms_by_char: dict[str, list[int]] = defaultdict(list)
        self.atb_observations: list[dict[str, Any]] = []
        # CHAR_SKILLS（bridge 自 SC_SELF_SCENE_INFO_SKILLS 落盘）：角色技能等级清单，
        # 供排轴导出 API 消费；同角色多次同步取最后一次。
        self.char_skill_levels: dict[str, dict[str, int]] = {}
        self.squad_actor_keys: dict[str, str] = {}
        self.first_party_action_ms: int | None = None
        self.recent_numeric_buffs_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.dungeon_context: tuple[str, str] | None = None
        self.dungeon_context_id: str | None = None
        self.party_actor_ids: set[str] = set()
        self.entity_stats_timelines: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        self.dynamic_bb_events: list[dict[str, Any]] = []
        self.buff_attribute_refresh_events: list[dict[str, Any]] = []
        self.buff_creation_operation_history: dict[tuple[Any, ...], dict[str, Any]] = {}
        # A typed root is immutable during a parse. Keep its exact object alive and
        # index every integer action identity once; duplicate identities and the
        # inherited enabled state remain part of each lookup's existing guards.
        # This cache is local so another parse/root/version cannot reuse its proof.
        self.buff_root_action_indices: dict[int, tuple[Any, dict[int, list[tuple[dict[str, Any], bool]]],
                                                       list[tuple[dict[str, Any], bool]]]] = {}
        self.game_timer_start_ms: int | None = None
        self.game_timer_end_ms: int | None = None
        self.game_timer_elapsed_ms: int | None = None
        self.game_timer_window_elapsed_ms: int | None = None
        self.official_timer_start_ms: int | None = None
        self.official_timer_elapsed_ms: int | None = None
        self.official_timer_end_ms: int | None = None
        self.live_timer_elapsed_ms: int | None = None
        self.packet_timer_elapsed_ms: int | None = None
        self.timer_start_seen = False
        self.timer_end_seen = False
        self.timer_window_valid = True
        self.challenge_pass_confirmed = False
        self.official_pass_confirmed = False
        self.completion_source = ""
        self.active_suits_by_char: dict[str, set[str]] = {}
        self.weapon_override_by_char = {
            str(char_key): copy.deepcopy(row)
            for char_key, row in (loadout_override_by_char or {}).items()
            if isinstance(row, dict)
        }
        self.active_weapons_by_char: dict[str, str] = {
            char_key: str(row.get("weapon_template") or "")
            for char_key, row in self.weapon_override_by_char.items()
            if str(row.get("weapon_template") or "")
        }
        self.loadout_by_char: dict[str, dict[str, Any]] = copy.deepcopy(self.weapon_override_by_char)
        self.loadout_groups: list[dict[str, Any]] = []
        self.current_loadout_group: dict[str, Any] | None = None
        self.first_context_ms: int | None = None
        self.last_context_ms: int | None = None
        self.contract_tag_ids: list[int] = []
        self.contract_tag_score: int | None = None
        self.poise_damage_events: list[dict[str, Any]] = []
        self.timestamp_clock_origin: int | None = None
        self.timer_observed_times: dict[int, int] = {}

    def set_dungeon_context(self, raw_dungeon_id: str | None) -> None:
        context_id = str(raw_dungeon_id or "").strip()
        if context_id:
            self.dungeon_context_id = context_id
            # Keep the latest official id even if its catalog entry is unknown.
            self.dungeon_context = _resolve_dungeon_context(context_id)

    def snapshot(self) -> dict[str, Any]:
        """Expose the existing evidence view; callers copy before finalization."""
        return {
            'active_suits_by_char': self.active_suits_by_char,
            'active_weapons_by_char': self.active_weapons_by_char,
            'atb_gain_ms_by_char': self.atb_gain_ms_by_char,
            'atb_observations': self.atb_observations,
            'buff_attribute_refresh_events': self.buff_attribute_refresh_events,
            'buff_root_action_indices': self.buff_root_action_indices,
            'buff_starts': self.buff_starts,
            'challenge_pass_confirmed': self.challenge_pass_confirmed,
            'char_skill_levels': self.char_skill_levels,
            'completion_source': self.completion_source,
            'contract_tag_ids': self.contract_tag_ids,
            'contract_tag_score': self.contract_tag_score,
            'dungeon_context': self.dungeon_context,
            'dungeon_context_id': self.dungeon_context_id,
            'dynamic_bb_events': self.dynamic_bb_events,
            'enemy_counter': self.enemy_counter,
            'first_context_ms': self.first_context_ms,
            'first_hit_hint_ms': self.first_hit_hint_ms,
            'first_party_action_ms': self.first_party_action_ms,
            'game_timer_elapsed_ms': self.game_timer_elapsed_ms,
            'game_timer_end_ms': self.game_timer_end_ms,
            'game_timer_start_ms': self.game_timer_start_ms,
            'game_timer_window_elapsed_ms': self.game_timer_window_elapsed_ms,
            'hits': self.hits,
            'last_context_ms': self.last_context_ms,
            'last_hit_hint_ms': self.last_hit_hint_ms,
            'live_timer_elapsed_ms': self.live_timer_elapsed_ms,
            'loadout_by_char': self.loadout_by_char,
            'loadout_groups': self.loadout_groups,
            'official_pass_confirmed': self.official_pass_confirmed,
            'official_timer_elapsed_ms': self.official_timer_elapsed_ms,
            'official_timer_end_ms': self.official_timer_end_ms,
            'official_timer_start_ms': self.official_timer_start_ms,
            'packet_modifier_last_seen_by_uid': self.packet_modifier_last_seen_by_uid,
            'packet_timer_elapsed_ms': self.packet_timer_elapsed_ms,
            'participant_totals': self.participant_totals,
            'poise_damage_events': self.poise_damage_events,
            'reference_date': self.reference_date,
            'roster_order': self.roster_order,
            'roster_seen': self.roster_seen,
            'skill_casts': self.skill_casts,
            'timer_end_seen': self.timer_end_seen,
            'timer_observed_times': self.timer_observed_times,
            'timestamp_clock_origin': self.timestamp_clock_origin,
            'timer_start_seen': self.timer_start_seen,
            'timer_window_valid': self.timer_window_valid,
            'unresolved_buff_actions': self.unresolved_buff_actions,
            'unresolved_hits': self.unresolved_hits,
        }
