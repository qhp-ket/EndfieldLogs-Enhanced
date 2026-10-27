"""Project battle readiness and unresolved evidence when no damage is observed."""
from __future__ import annotations

from collections import Counter
from parser_core.catalog.dungeons import UNKNOWN_DUNGEON_NAME
from parser_core.constants import PARSER_VERSION
from parser_core.constants import RULES_VERSION
from parser_core.constants import UNKNOWN_DUNGEON_KEY
from parser_core.ingestion.fields import _build_iso_datetime
from parser_core.integrity import build_canonical_sha256
from parser_core.realtime.live_summary import finish_live_report
from parser_core.reporting.loadout import _select_loadout_snapshot_for_battle
from parser_core.reporting.state import ReportState
from typing import Any


def build_empty_report(report_state: ReportState, official_timer_observed_elapsed_ms: int | None, *, file_name: str | None, summary: bool) -> dict[str, Any]:
    """Project battle readiness and unresolved evidence when no damage is observed."""
    anchor_ms = (
        report_state.official_timer_start_ms
        if report_state.official_timer_start_ms is not None
        else report_state.first_party_action_ms
        if report_state.first_party_action_ms is not None
        else report_state.game_timer_start_ms
        if report_state.game_timer_start_ms is not None
        else report_state.first_context_ms
        if report_state.first_context_ms is not None
        else 0
    )
    battle_loadout_by_char = _select_loadout_snapshot_for_battle(
        report_state.loadout_groups,
        report_state.loadout_by_char,
        anchor_ms=anchor_ms,
    )
    loadout = sorted(
        battle_loadout_by_char.values(),
        key=lambda item: (int(item.get("slot") or 0), str(item.get("character_key") or "")),
    )
    roster = [
        {
            "slot": int(row.get("slot") or index),
            "character_key": str(row.get("character_key") or ""),
            "character_name": str(row.get("character_name") or row.get("character_key") or ""),
        }
        for index, row in enumerate(loadout, start=1)
        if row.get("character_key")
    ]
    end_ms = report_state.last_context_ms if report_state.last_context_ms is not None else anchor_ms
    dungeon_key, dungeon_name = report_state.dungeon_context or (UNKNOWN_DUNGEON_KEY, UNKNOWN_DUNGEON_NAME)
    time_source = "party_action_window" if report_state.first_party_action_ms is not None else "battle_ready"
    fingerprint_payload = {
        "rules_version": RULES_VERSION,
        "time_source": time_source,
        "loadout": [row["character_key"] for row in roster],
        "anchor_ms": anchor_ms,
    }
    return finish_live_report({
        "battle": {
            "dungeon_key": dungeon_key,
            "dungeon_name": dungeon_name,
            "boss_key": "unknown_boss",
            "boss_name": "未知对象",
            "boss_identity_source": "missing_damage_target",
            "dungeon_context_id": report_state.dungeon_context_id,
            "dungeon_identity_source": (
                "dungeon_context"
                if report_state.dungeon_context is not None
                else "unmapped_dungeon_context"
                if report_state.dungeon_context_id
                else "missing_dungeon_context"
            ),
            "battle_start_at": _build_iso_datetime(report_state.reference_date, anchor_ms),
            "battle_end_at": _build_iso_datetime(report_state.reference_date, end_ms),
            "duration_ms": 0,
            "time_source": time_source,
            "timeline_zero_source": time_source,
            "timer_start_seen": report_state.timer_start_seen,
            "timer_end_seen": report_state.timer_end_seen,
            "official_timer_start_seen": report_state.official_timer_start_ms is not None,
            "official_timer_end_seen": report_state.official_timer_end_ms is not None,
            "official_timer_observed_elapsed_ms": official_timer_observed_elapsed_ms,
            "packet_timer_elapsed_ms": report_state.packet_timer_elapsed_ms,
            "timer_integrity_ok": False if report_state.official_pass_confirmed else None,
            "timer_integrity_reasons": (
                ["missing_damage_events"] if report_state.official_pass_confirmed else []
            ),
            "timer_start_inferred": False,
            "clear_flag": False,
            "total_damage": 0,
            "total_dps": 0.0,
            "roster": roster,
            "battle_fingerprint": build_canonical_sha256(fingerprint_payload) if not summary else None,
            "parser_version": PARSER_VERSION,
            "rules_version": RULES_VERSION,
            "source_file_name": file_name,
        },
        "participants": [],
        "loadout": loadout,
        "buff_events": [],
        "timeline_events": [],
        "role_skill_stats": [],
        "debug_hits": [],
        "unresolved_hits": report_state.unresolved_hits,
        "unresolved_buff_actions": report_state.unresolved_buff_actions,
        "rdps_preflight": {
            "ok": False, "blocker_count": max(1, len(report_state.unresolved_hits) + len(report_state.unresolved_buff_actions)),
            "blocker_reason_counts": dict(Counter(row['reason'] for row in
                (report_state.unresolved_hits + report_state.unresolved_buff_actions or [{'reason': 'missing_damage_events'}]))),
            "blockers": (report_state.unresolved_hits + report_state.unresolved_buff_actions)[:100] or [{"reason": "missing_damage_events"}],
        },
        "rdps_damage_basis": {
            "rdps_preflight_ok": False, "rdps_strict_ok": False,
            "rdps_conservation_ok": False, "hit_count": 0,
            "unresolved_damage_actor_count": len(report_state.unresolved_hits),
        },
        "casts": [],
        "atb_events": [],
        "char_skills": {},
    }, summary)
