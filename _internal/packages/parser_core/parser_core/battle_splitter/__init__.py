from parser_core.schemas.battle import BattleCandidate, BattleSummary


def split_placeholder_battles(trace_name: str) -> list[BattleCandidate]:
    return [
        BattleCandidate(
            local_id="placeholder-1",
            summary=BattleSummary(
                dungeon_name="Unknown Dungeon",
                boss_name=f"Placeholder from {trace_name}",
                duration_ms=None,
            ),
            validation_status="pending",
        )
    ]

