from parser_core import BattleCandidate, BattleSummary


def test_parser_core_exports() -> None:
    summary = BattleSummary(dungeon_name="Dungeon", boss_name="Boss")
    candidate = BattleCandidate(local_id="local-1", summary=summary)
    assert candidate.summary.boss_name == "Boss"

