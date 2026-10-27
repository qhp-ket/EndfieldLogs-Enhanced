"""Project sorted participant statistics and roster from canonical allocation results."""
from __future__ import annotations

from parser_core.realtime.live_summary import canonical_rates
from parser_core.reporting.state import ReportState
from typing import Any


def build_participants(report_state: ReportState, battle_loadout_by_char: dict[str, dict[str, Any]], rdps_damage: dict[str, float], duration_ms: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project sorted participant statistics and roster from canonical allocation results."""
    participants = []
    for character_key in report_state.roster_order:
        participant = report_state.participant_totals.get(character_key)
        if participant is None or not participant["character_name"]:
            continue
        if battle_loadout_by_char and character_key not in battle_loadout_by_char and participant["total_damage"] <= 0:
            continue
        total_rd = rdps_damage.get(character_key, float(participant["total_damage"]))
        if participant["total_damage"] <= 0 and total_rd <= 0:
            continue
        dps, rdps = canonical_rates(participant["total_damage"], total_rd, duration_ms)
        hit_count = participant["hit_count"]
        participants.append(
            {
                "character_key": character_key,
                "character_name": participant["character_name"],
                "total_damage": participant["total_damage"],
                "total_rd": total_rd,
                "dps": dps,
                "rdps": rdps,
                "max_hit": participant["max_hit"] or None,
                "hit_count": hit_count or None,
                "crit_hits": participant["crit_hits"] or None,
                "crit_rate": round(participant["crit_hits"] / hit_count, 4) if hit_count else None,
            }
        )
    participants.sort(key=lambda item: (-item["dps"], -item["rdps"], item["character_name"]))
    roster = [
        {
            "slot": index,
            "character_key": participant["character_key"],
            "character_name": participant["character_name"],
        }
        for index, participant in enumerate(participants, start=1)
    ]
    return participants, roster
