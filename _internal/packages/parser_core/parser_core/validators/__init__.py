from parser_core.schemas.battle import BattleCandidate


def validate_candidate(candidate: BattleCandidate) -> BattleCandidate:
    return candidate.model_copy(update={"validation_status": "pass"})

