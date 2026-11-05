"""Loadout observations shared by the legacy and structured adapters."""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LoadoutSlotObservation:
    character: str
    slot: int = 0
    character_level: int | None = None
    potential: int = 0
    weapon_instance: str | None = None
    weapon: str = ''
    weapon_level: int | None = None
    refine: int | None = None
    breakthrough: int = 0
    suit_blob: str = ''
    equipment_blob: str | None = None
    skill_ids: list[str] = field(default_factory=list)
    unplaced_ids: list[str] | None = None
    equipment_complete: bool | None = None


@dataclass(frozen=True)
class LoadoutStatsObservation:
    character: str
    weapon: str = ''
    weapon_instance: str = ''
    weapon_level: int | None = None
    refine_stats_blob: str | None = None
    source_skills_blob: str | None = None
    base_attack: int = 0
    base_attack_lv1: int = 0
    base_attack_max: int = 0
    gem_instance: str = ''
    gem_weapon: str = ''
    gem_template: str | None = None
    terms_blob: str = ''
