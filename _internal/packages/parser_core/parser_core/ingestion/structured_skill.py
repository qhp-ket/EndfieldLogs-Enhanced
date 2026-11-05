"""Skill, ATB and poise events call shared observation state without trace text."""
from parser_core.ingestion.identity import _extract_character_key
from parser_core.ingestion.fields import _coerce_optional_float
from parser_core.ingestion.skills import apply_atb_observation, apply_skill_start, apply_skill_end
from parser_core.ingestion.skill_wire import integer, projected_number, label, identity_token
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.reporting.poise import poise_damage_observation
from parser_core.trace_values import restore_value


def consume_structured_skill(ingestion, event, evidence_index):
    data = _object(event.data)
    if event.type not in {"skill_cast", "atb", "poise"}:
        raise ValueError("Expected skill/resource event")
    for key in ("owner_id", "skill_inst_id", "attacker_id"):
        if key in data:
            _identity(data[key])
    if event.type == "skill_cast" and (data.get("phase") not in {"start", "end"} or "skill_inst_id" not in data):
        raise ValueError("Expected skill phase and instance")
    for key in ("owner", "attacker", "skill", "skill_source", "source", "original_source"):
        if key in data and data[key] is not None and not isinstance(data[key], str):
            raise ValueError("Expected skill/resource label")
    restored = restore_value(data, _object(data.get("legacy_layout", {})))
    stamp = event.captured_at_ms
    if event.type == "skill_cast":
        instance = identity_token(restored.get("skill_inst_id"))
        if data["phase"] == "start":
            apply_skill_start(ingestion, stamp, evidence_index, label(restored, "skill", "unknown_skill"),
                label(restored, "owner", "?"), identity_token(restored.get("owner_id")), instance, label(restored, "skill_source"))
        else:
            apply_skill_end(ingestion, instance, stamp, evidence_index)
    elif event.type == "atb":
        apply_atb_observation(ingestion, {"ts_ms": stamp, "line_no": evidence_index,
            "character_key": _extract_character_key(label(restored, "owner", "?"), ""),
            "owner_actor_id": identity_token(restored.get("owner_id")),
            "value": projected_number(restored.get("value")), "delta": projected_number(restored.get("delta")),
            "recovery_speed": projected_number(restored.get("recovery_speed")),
            "client_tick_ms": _coerce_optional_float(str(integer(restored.get("client_tick_ms")) or 0)),
            "reason": label(restored, "reason"), "source": label(restored, "source"),
            "original_source": label(restored, "original_source")})
    else:
        observation = poise_damage_observation(stamp, evidence_index, label(restored, "modify_type"),
            projected_number(restored.get("value")), projected_number(restored.get("current_value")),
            label(restored, "source"), integer(restored.get("source_int")) or None,
            label(restored, "original_source"), integer(restored.get("original_source_int")) or None)
        if observation is not None:
            ingestion.poise_damage_events.append(observation)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = stamp
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = stamp
    ingestion.last_context_ms = stamp
