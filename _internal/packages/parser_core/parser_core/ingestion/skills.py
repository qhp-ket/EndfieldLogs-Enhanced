"""Observed ATB and skill instance lifecycle."""
from __future__ import annotations

from parser_core.ingestion.fields import _coerce_optional_float, _extract_fields, _safe_positive_rate
from parser_core.ingestion.identity import _extract_character_key
from parser_core.ingestion.state import IngestionState
import re


def consume_skill_observation(ingestion: IngestionState, raw_line: str, line_no: int, ts_ms: int) -> bool:
    if " ATB_UPDATE " in raw_line:
        fields = _extract_fields(raw_line)
        # Evidence projection only: retain observed values, never integrate
        # recovery speed or infer unobserved consumption/initial energy.
        apply_atb_observation(ingestion, {
            "ts_ms": ts_ms, "line_no": line_no,
            "character_key": _extract_character_key(fields.get("owner"), ""),
            "owner_actor_id": fields.get("ownerId"),
            "value": _coerce_optional_float(fields.get("atb")),
            "delta": _coerce_optional_float(fields.get("delta")),
            "recovery_speed": _coerce_optional_float(fields.get("recoverySpeed")),
            "client_tick_ms": _coerce_optional_float(fields.get("tick")),
            "reason": fields.get("reason"), "source": fields.get("source"),
            "original_source": fields.get("origSource"),
        })
        return True

    if " SKILL_CAST_START " in raw_line:
        fields = _extract_fields(raw_line)
        cast_skill = str(fields.get("skill") or "")
        apply_skill_start(ingestion, ts_ms, line_no, cast_skill, fields.get("owner"), fields.get("ownerId"),
                          fields.get("inst"), fields.get("skillSource") or fields.get("skill_source"))
        return True

    if " SKILL_CAST_END " in raw_line:
        fields = _extract_fields(raw_line)
        apply_skill_end(ingestion, fields.get("inst"), ts_ms, line_no)
        return True
    return False


def apply_atb_observation(ingestion, observation):
    ingestion.atb_observations.append(observation)
    character = observation["character_key"]
    if character and observation["reason"] == "AddValue" and _safe_positive_rate(observation["delta"]) is not None:
        ingestion.atb_gain_ms_by_char[character].append(observation["ts_ms"])


def apply_skill_start(ingestion, ts_ms, line_no, skill, owner, owner_id, instance, source):
    character = _extract_character_key(owner, skill)
    record = {"ts_ms": ts_ms, "line_no": line_no, "skill": skill, "owner": owner, "owner_id": owner_id,
              "skill_inst_id": instance, "skill_source": source, "source_character_key": character, "end_ts_ms": None}
    ingestion.skill_casts.append(record)
    if instance:
        ingestion.active_skill_casts_by_inst[instance] = record
    if character:
        if ingestion.first_party_action_ms is None and not _is_generic_runtime_skill_id(skill):
            ingestion.first_party_action_ms = ts_ms
        rows = ingestion.recent_skill_casts_by_char[character]
        rows.append({"ts_ms": ts_ms, "skill": skill, "owner": owner, "skill_inst_id": instance, "skill_source": source})
        del rows[:-16]


def apply_skill_end(ingestion, instance, ts_ms, line_no):
    record = ingestion.active_skill_casts_by_inst.pop(instance, None) if instance else None
    if record is not None:
        record["end_ts_ms"] = ts_ms
        record["end_line_no"] = line_no


def _is_generic_runtime_skill_id(skill_key: str | None) -> bool:
    return bool(re.fullmatch(r"skill_\d+", str(skill_key or "")))
