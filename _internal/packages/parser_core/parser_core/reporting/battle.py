"""Coordinate evidence preparation, canonical allocation and battle report projections."""
from __future__ import annotations

from parser_core.allocation.basis import _build_rdps_damage_basis
from parser_core.allocation.ledger import _compute_rdps_damage_shares
from parser_core.allocation.preflight import _build_rdps_preflight
from parser_core.catalog.display import _resolve_enemy_name
from parser_core.catalog.dungeons import UNKNOWN_DUNGEON_NAME
from parser_core.catalog.dungeons import _contract_tag_payload
from parser_core.constants import PARSER_VERSION
from parser_core.constants import RULES_VERSION
from parser_core.constants import UNKNOWN_DUNGEON_KEY
from parser_core.ingestion.fields import _build_iso_datetime
from parser_core.ingestion.fields import _coerce_int
from parser_core.ingestion.identity import _infer_context_enemy_hint
from parser_core.ingestion.skill_identity import _infer_missing_hit_damage_schools
from parser_core.integrity import build_canonical_sha256
from parser_core.reporting.baseline import prepare_static_baseline
from parser_core.reporting.buffs import _build_buff_events
from parser_core.reporting.critical import attach_critical_context
from parser_core.reporting.effect_windows import prepare_effect_windows
from parser_core.reporting.empty import build_empty_report
from parser_core.reporting.evidence import bind_dynamic_observations
from parser_core.reporting.evidence import prepare_buff_sources
from parser_core.reporting.hit_details import build_debug_hits
from parser_core.reporting.loadout import _repair_weapon_puton_loadout_groups
from parser_core.reporting.participants import build_participants
from parser_core.reporting.poise import _apply_poise_damage_events_to_hits
from parser_core.reporting.skill_stats import _assign_skill_timeline_group_keys
from parser_core.reporting.skill_stats import _build_role_skill_stats_from_timeline_groups
from parser_core.reporting.state import ReportState
from parser_core.reporting.timeline import append_buff_events
from parser_core.reporting.timeline import append_non_damage_casts
from parser_core.reporting.timeline import build_hit_events
from parser_core.reporting.timeline import export_casts
from parser_core.reporting.timing import apply_official_timing
from parser_core.reporting.window import BattleTimeline
from parser_core.reporting.window import select_hit_window
from parser_core.timing.timer_evidence import validate_timer_evidence
from typing import Any


def _build_raw_battle_report(state, text, *, file_name=None, include_rdps_debug=False, summary=False, allow_empty=False):
    """Project a private copy; finalization must never mutate ingestion state."""
    from parser_core.realtime.live_summary import finish_live_report, canonical_rates
    from parser_core.realtime.live_metrics import mark
    from parser_core.realtime.incremental import ACTIVE_ALLOCATION_CACHE
    live_projection = ACTIVE_ALLOCATION_CACHE.get()
    report_state = ReportState.from_snapshot(state)
    context_enemy_hint = _infer_context_enemy_hint(text)
    trace_identity_inference_seen = " IDENTITY_INFERENCE " in text

    report_state.loadout_by_char = _repair_weapon_puton_loadout_groups(report_state.loadout_groups, report_state.loadout_by_char)
    for event in report_state.buff_attribute_refresh_events:
        if isinstance(event.get('snapshot'), dict):
            event['snapshot_status'] = event['snapshot']['status']
    _apply_poise_damage_events_to_hits(report_state.hits, report_state.poise_damage_events)

    bind_dynamic_observations(report_state.hits, report_state.buff_starts, report_state.skill_casts, report_state.dynamic_bb_events)

    mark("state_preparation_ms")
    timer_evidence, official_timer_observed_elapsed_ms, official_scope = apply_official_timing(report_state, text, live_projection)

    if not report_state.hits and (report_state.loadout_by_char or report_state.dungeon_context_id or report_state.unresolved_hits or report_state.unresolved_buff_actions):
        return build_empty_report(report_state, official_timer_observed_elapsed_ms, file_name=file_name, summary=summary)

    if not report_state.hits and (summary or allow_empty):
        return None
    if not report_state.hits:
        raise ValueError("未在日志中解析到任何 HP_V2 伤害事件。")

    identity_retargeted = prepare_buff_sources(report_state, context_enemy_hint)

    hit_window = select_hit_window(report_state, timer_evidence, official_scope)
    first_hit_ms, last_hit_ms = hit_window.start_ms, hit_window.end_ms
    time_source, timeline_zero_source = hit_window.time_source, hit_window.zero_source
    has_game_timer_window = hit_window.has_game_timer

    boss_key = report_state.enemy_counter.most_common(1)[0][0] if report_state.enemy_counter else "unknown_boss"
    boss_name = _resolve_enemy_name(boss_key) or boss_key
    dungeon_key, dungeon_name = report_state.dungeon_context or (UNKNOWN_DUNGEON_KEY, UNKNOWN_DUNGEON_NAME)
    if timer_evidence is not None or dungeon_key.startswith("indie_battletower"):
        # War Echo records are leaderboard data. Only the server's official
        # challenge-complete message may mark them cleared; HP zero, scene
        # exits and late dungeon status are retained as diagnostics only.
        clear_flag = report_state.official_pass_confirmed
    else:
        clear_flag = report_state.challenge_pass_confirmed or any(
            hit["target_enemy_key"] == boss_key and hit.get("enemy_hp_after", 1) <= 0
            for hit in report_state.hits
        )
    if not report_state.timer_window_valid:
        clear_flag = False
    duration_ms = max(
        report_state.game_timer_elapsed_ms if report_state.game_timer_elapsed_ms is not None else last_hit_ms - first_hit_ms,
        1,
    )
    timer_integrity_reasons: list[str] = []
    if report_state.official_pass_confirmed:
        timer_integrity_reasons = validate_timer_evidence(
            timer_evidence, duration_ms=duration_ms, game_id=report_state.dungeon_context_id)
    timer_integrity_ok = not timer_integrity_reasons if report_state.official_pass_confirmed else None
    wall_window_ms = max(last_hit_ms - first_hit_ms, 1)
    timeline_scale = duration_ms / wall_window_ms if has_game_timer_window else 1.0
    timer_start_inferred = timeline_zero_source in {
        "timer_end_inferred",
        "timer_elapsed_first_hit_inferred",
    }

    timeline = BattleTimeline(first_hit_ms, last_hit_ms, timeline_scale)
    battle_offset_ms_unclamped = timeline.offset_ms_unclamped

    total_damage = sum(hit["hit_value"] for hit in report_state.hits)
    total_dps = canonical_rates(total_damage, 0, duration_ms)[0]
    battle_loadout_by_char, loadout_stale, static_arts_strength_by_char = prepare_static_baseline(report_state, first_hit_ms)

    roster = []

    buff_windows = prepare_effect_windows(report_state, static_arts_strength_by_char, last_hit_ms)

    # Static audit classifies each exact weapon skill field above. Observing
    # one known trigger never waives other unknown fields from that weapon.
    # Trigger capture coverage and allocation remain separate per-Buff checks.

    _infer_missing_hit_damage_schools(report_state.hits, buff_windows)
    mark("semantic_windows_ms")
    buff_events = []
    if not summary:
        buff_events = _build_buff_events(
            report_state.buff_starts,
            buff_windows,
            battle_start_ms=first_hit_ms,
            battle_end_ms=last_hit_ms,
            root_lookup_cache=report_state.buff_root_action_indices,
        )
    ink_summary: dict = {}
    rdps_damage = _compute_rdps_damage_shares(report_state.hits, buff_windows, condition_buff_records=report_state.buff_starts,
        trace_text=text, ink_summary=ink_summary)
    mark("allocation_ms")
    if not summary:
        attach_critical_context(report_state, buff_windows)
    rdps_preflight = _build_rdps_preflight(
        report_state.buff_starts,
        buff_windows,
        hits=report_state.hits,
        unresolved_hits=report_state.unresolved_hits,
        unresolved_buff_actions=report_state.unresolved_buff_actions,
        battle_start_ms=first_hit_ms,
        battle_end_ms=last_hit_ms,
        active_character_keys=set(battle_loadout_by_char),
        root_lookup_cache=report_state.buff_root_action_indices,
    )
    rdps_damage_basis = _build_rdps_damage_basis(report_state.hits, rdps_damage, int(total_damage))
    if ink_summary:
        rdps_damage_basis['ink_provenance'] = ink_summary
    rdps_damage_basis["rdps_preflight_ok"] = bool(rdps_preflight.get("ok"))
    rdps_damage_basis["rdps_strict_ok"] = bool(rdps_preflight.get("ok")) and bool(rdps_damage_basis.get("rdps_conservation_ok"))
    rdps_damage_basis["preflight_blocker_count"] = int(rdps_preflight.get("blocker_count") or 0)
    rdps_damage_basis["unresolved_damage_actor_count"] = sum(
        first_hit_ms <= int(row.get("ts_ms") or 0) <= last_hit_ms for row in report_state.unresolved_hits
    )
    mark("quality_checks_ms")
    if not summary:
        _assign_skill_timeline_group_keys(report_state.hits)

    participants, roster = build_participants(report_state, battle_loadout_by_char, rdps_damage, duration_ms)

    mark("participants_ms")
    timeline_events = []
    role_skill_stats = []
    casts_export = []
    debug_hits = []
    fingerprint_payload = None
    loadout = sorted(battle_loadout_by_char.values(), key=lambda item: (int(item.get("slot") or 0), str(item.get("character_key") or "")))
    if not summary:
        timeline_events = build_hit_events(report_state, timeline)

        # 零伤害施放补录（例如辅助干员的终结技）：这些施放没有任何伤害命中，
        # 时间轴上会完全缺失。仅当施放技能名可解析为真实模板（非运行时兜底 id）、
        # 属于战技/连携/终结技形态、且该角色同技能在本场没有伤害命中时补一个 cast 事件；
        # 解析不出真名的老日志自动不生效，不会产生歧义数据。
        participant_keys = append_non_damage_casts(report_state, timeline, participants, timeline_events)

        # 完整施法序列（v33，排轴导出 API 专用通道，不进 timeline_events 不影响展示）：
        # 参与者的每一次 SKILL_CAST_START 原样保留分段（attack1~5/重击/战技/终结…），
        # 运行时 id 经 num 表解析、失败自弃；子实体派生施放（projhit/abilityrange 等）
        # 不是玩家操作，过滤掉。窗口放宽到战斗零点前 10s（开怪第一个施放先于首刀落地）。
        casts_export = export_casts(report_state, timeline, participant_keys)

        append_buff_events(report_state, timeline, buff_windows, timeline_events)
        timeline_events.sort(key=lambda item: (item["ts_ms_from_start"], item["lane_type"], item["event_name"]))

        role_skill_stats = _build_role_skill_stats_from_timeline_groups(report_state.hits, report_state.roster_order)
        loadout = sorted(
            battle_loadout_by_char.values(),
            key=lambda item: (int(item.get("slot") or 0), str(item.get("character_key") or "")),
        )
        debug_hits: list[dict[str, Any]] = []
        if include_rdps_debug:
            debug_hits = build_debug_hits(report_state, buff_windows)

        fingerprint_payload = {
            "rules_version": RULES_VERSION,
            "boss_key": boss_key,
            "first_hit_ms": first_hit_ms,
            "last_hit_ms": last_hit_ms,
            "hits": [
                {
                    "ts_ms": hit["ts_ms"],
                    "character_key": hit["character_key"],
                    "skill_key": hit["skill_key"],
                    "hit_value": hit["hit_value"],
                    "crit_flag": hit["crit_flag"],
                    "target_enemy_key": hit["target_enemy_key"],
                }
                for hit in report_state.hits
            ],
        }
    mark("detail_projection_ms")
    contract_tags = [_contract_tag_payload(tag_id) for tag_id in report_state.contract_tag_ids]
    if contract_tags:
        tag_scores = [_coerce_int(str(tag.get("score") or ""), default=0) for tag in contract_tags]
        computed_contract_tag_score = sum(tag_scores)
        if computed_contract_tag_score > 0:
            report_state.contract_tag_score = computed_contract_tag_score
        elif report_state.contract_tag_score is None:
            report_state.contract_tag_score = computed_contract_tag_score

    return finish_live_report({
        "battle": {
            "dungeon_key": dungeon_key,
            "dungeon_name": dungeon_name,
            "boss_key": boss_key,
            "boss_name": boss_name,
            "battle_start_at": _build_iso_datetime(report_state.reference_date, first_hit_ms),
            "battle_end_at": _build_iso_datetime(report_state.reference_date, last_hit_ms),
            "duration_ms": duration_ms,
            "time_source": "game_timer" if has_game_timer_window else time_source,
            "timeline_zero_source": timeline_zero_source,
            "timer_start_seen": report_state.timer_start_seen,
            "timer_end_seen": report_state.timer_end_seen,
            "official_timer_start_seen": report_state.official_timer_start_ms is not None,
            "official_timer_end_seen": report_state.official_timer_end_ms is not None,
            "official_timer_observed_elapsed_ms": official_timer_observed_elapsed_ms,
            "packet_timer_elapsed_ms": report_state.packet_timer_elapsed_ms,
            "timer_integrity_ok": timer_integrity_ok,
            "timer_integrity_reasons": timer_integrity_reasons,
            "timer_evidence": timer_evidence,
            "timer_start_inferred": timer_start_inferred,
            "timer_window_valid": report_state.timer_window_valid,
            "clear_flag": clear_flag,
            "challenge_pass_confirmed": report_state.challenge_pass_confirmed,
            "official_pass_confirmed": report_state.official_pass_confirmed,
            "completion_source": report_state.completion_source,
            "boss_identity_source": (
                "trace_inference"
                if trace_identity_inference_seen
                else "inferred_dungeon_context"
                if identity_retargeted
                else "damage_target"
            ),
            "dungeon_context_id": report_state.dungeon_context_id,
            "dungeon_identity_source": (
                "dungeon_context"
                if report_state.dungeon_context is not None
                else "unmapped_dungeon_context"
                if report_state.dungeon_context_id
                else "missing_dungeon_context"
            ),
            "total_damage": total_damage,
            "total_dps": total_dps,
            "roster": roster,
            "battle_fingerprint": build_canonical_sha256(fingerprint_payload) if not summary else None,
            "parser_version": PARSER_VERSION,
            "rules_version": RULES_VERSION,
            "source_file_name": file_name,
            "loadout_stale": loadout_stale,
            "rdps_damage_basis": rdps_damage_basis,
            "contract_tag_score": report_state.contract_tag_score,
            "contract_tags": contract_tags,
        },
        "participants": participants,
        "loadout": loadout,
        "buff_events": buff_events,
        "timeline_events": timeline_events,
        "dynamic_bb_events": report_state.dynamic_bb_events,
        "buff_attribute_refresh_events": report_state.buff_attribute_refresh_events,
        "role_skill_stats": role_skill_stats,
        "debug_hits": debug_hits,
        **({'debug_context': {'start_ts_ms': first_hit_ms, 'end_ts_ms': last_hit_ms,
                              'buff_windows': buff_windows}} if include_rdps_debug else {}),
        "rdps_damage_basis": rdps_damage_basis,
        "rdps_preflight": rdps_preflight,
        "unresolved_hits": report_state.unresolved_hits,
        "unresolved_buff_actions": report_state.unresolved_buff_actions,
        "casts": casts_export,
        "atb_events": [{**{k: v for k, v in row.items() if k != 'ts_ms'},
                        "ts_ms_from_start": battle_offset_ms_unclamped(row['ts_ms'])}
                       for row in (() if summary else report_state.atb_observations) if first_hit_ms - 10_000 <= row['ts_ms'] <= last_hit_ms],
        "char_skills": {
            character_key: [
                {"skill_key": skill_key, "level": level}
                for skill_key, level in sorted(levels.items())
            ]
            for character_key, levels in (() if summary else report_state.char_skill_levels.items())
        },
    }, summary, hits=report_state.hits)
