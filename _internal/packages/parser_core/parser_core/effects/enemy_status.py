"""Observed enemy defense values and per-target HP evidence."""
from __future__ import annotations

from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.effects.approval import _normalize_buff_id
from parser_core.ingestion.fields import _coerce_optional_float, _coerce_optional_int
import re
from typing import Any

from parser_core.ingestion.fields import _safe_positive_rate


def _apply_enemy_status_bb_overrides(
    record: dict[str, Any],
    *,
    context_enemy_hint: str | None,
) -> None:
    root = _load_current_buff_roots().get(_normalize_buff_id(record.get('event_key')))
    if not isinstance(root, dict) or root.get('lifeType') not in {'Limited', 'Infinity'}:
        return
    record['lifetime_mode'] = root['lifeType']
    record['lifetime_source'] = 'typed_current_BuffData'
    if record.get("raw_duration_ms") is not None:
        return
    # Infinity ignores the duration configuration. It remains an open interval
    # until a concrete finish event; battle-end clipping is only for display.
    if root['lifeType'] == 'Infinity':
        return
    duration = root.get('duration')
    if not isinstance(duration, dict):
        return
    use_key = duration.get('useBlackboardKey')
    key = str(duration.get("blackboardKey") or "")
    values = record.get("bb_values") or {}
    seconds = (_coerce_optional_float(values.get(key)) if use_key is True and key else
               _coerce_optional_float(duration.get('value')) if use_key is False else None)
    if seconds is None or seconds < 0:
        return
    record["raw_duration_ms"] = int(round(seconds * 1000))
    record["raw_duration_source"] = "official_duration_blackboard" if use_key is True else "official_duration_constant"


def _cap_enemy_overkill_damage(
    hit_value: int,
    *,
    enemy_hp_after: int | None,
    previous_enemy_hp: int | None,
) -> int:
    if hit_value <= 0 or enemy_hp_after is None or previous_enemy_hp is None:
        return hit_value
    if previous_enemy_hp <= 0 and enemy_hp_after <= 0:
        return 0
    if enemy_hp_after <= 0 and previous_enemy_hp > 0:
        return min(hit_value, previous_enemy_hp)
    return hit_value


def _enemy_hp_state_key(target_enemy_key: Any, target_actor_id: Any = None) -> str:
    """Use the packet entity identity when present; template keys are only a fallback."""
    actor_id = str(target_actor_id or "")
    if re.fullmatch(r"[1-9]\d*", actor_id):
        return f"actor:{actor_id}"
    return f"template:{str(target_enemy_key or '')}"


def _annotate_hit_enemy_hp_state(hits: list[dict[str, Any]]) -> None:
    previous_enemy_hp_by_target: dict[str, int] = {}
    observed_max_hp_by_target: dict[str, int] = {}

    for hit in hits:
        target_enemy_key = str(hit.get("target_enemy_key") or "")
        hp_state_key = _enemy_hp_state_key(target_enemy_key, hit.get("target_actor_id"))
        enemy_hp_after = _coerce_optional_int(hit.get("enemy_hp_after"))
        if not target_enemy_key or enemy_hp_after is None:
            continue

        previous_enemy_hp = previous_enemy_hp_by_target.get(hp_state_key)
        hit_value = max(0, _coerce_optional_int(hit.get("hit_value")) or 0)
        if previous_enemy_hp is not None and previous_enemy_hp >= enemy_hp_after:
            enemy_hp_before = previous_enemy_hp
            source = "previous_enemy_hp"
        else:
            enemy_hp_before = enemy_hp_after + hit_value
            source = "enemy_hp_after_plus_hit"

        hit["enemy_hp_before"] = enemy_hp_before
        hit["enemy_hp_before_source"] = source
        observed_max_hp_by_target[hp_state_key] = max(
            observed_max_hp_by_target.get(hp_state_key, 0),
            enemy_hp_before,
            enemy_hp_after,
        )
        previous_enemy_hp_by_target[hp_state_key] = enemy_hp_after

    for hit in hits:
        target_enemy_key = str(hit.get("target_enemy_key") or "")
        hp_state_key = _enemy_hp_state_key(target_enemy_key, hit.get("target_actor_id"))
        observed_max_hp = observed_max_hp_by_target.get(hp_state_key)
        enemy_hp_before = _coerce_optional_int(hit.get("enemy_hp_before"))
        if observed_max_hp is None or observed_max_hp <= 0:
            continue
        hit["target_enemy_observed_max_hp"] = observed_max_hp
        # The highest observed HP may be an already-damaged enemy, so it is
        # not the maximum HP required by CheckHp. Only an explicit maximum
        # from the packet can establish a percentage condition.
        explicit_max_hp = _coerce_optional_int(hit.get("target_enemy_max_hp"))
        if enemy_hp_before is not None and explicit_max_hp is not None and explicit_max_hp > 0:
            hit["target_enemy_hp_ratio_before"] = enemy_hp_before / explicit_max_hp



_ENEMY_DEFENSE_EFFECT_BB_KEYS = {
    "additional_def_decrease",
    "all_resistance_decrease",
    "def_decrease",
    "def_decrease_tick",
    "def_decrease_tick_final",
    "final_spell_resistance_decrease",
    "max_def_decrease",
    "physical_res_down",
    "physical_vulnerable_dmg_increase",
    "phy_resist_down",
    "spell_damage_taken_up",
    "spell_resistance_decrease",
    "spell_taken_up",
    "start_def_decrease",
}


def _record_has_enemy_defense_effect(record: dict[str, Any], bb_values: dict[str, Any]) -> bool:
    bb_keys = {str(key).lower() for key in bb_values}
    if bb_keys & _ENEMY_DEFENSE_EFFECT_BB_KEYS:
        return True

    event_key = _normalize_buff_id(record.get("event_key")).lower()
    if "conduct_triggered" in event_key:
        return True
    if "corrupt_triggered" in event_key or "corrupt_do" in event_key:
        return True
    if re.match(r"^buff_common_(?:try_)?natural_(?:fire|pulse|cryst|natural)_triggered(?:_wrapper)?$", event_key):
        return True
    return False


def _bb_duration_ms_for_enemy_defense_effect(bb_values: dict[str, Any]) -> int | None:
    for key in ("duration", "corrupt_duration", "duration_corrupt", "duration_corrupt_final"):
        duration = _safe_positive_rate(bb_values.get(key))
        if duration is not None:
            return int(duration * 1000)
    return None
