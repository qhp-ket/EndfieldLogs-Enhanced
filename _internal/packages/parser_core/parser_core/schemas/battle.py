from pydantic import BaseModel


class BattleSummary(BaseModel):
    dungeon_name: str
    boss_name: str
    duration_ms: int | None = None


class BattleCandidate(BaseModel):
    local_id: str
    summary: BattleSummary
    validation_status: str = "unknown"

