import hashlib

from parser_core.schemas.battle import BattleCandidate


def build_battle_fingerprint(candidate: BattleCandidate) -> str:
    payload = f"{candidate.local_id}:{candidate.summary.dungeon_name}:{candidate.summary.boss_name}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

