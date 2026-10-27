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
        ingestion.atb_observations.append({
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
        if str(fields.get("reason") or "") == "AddValue" and _safe_positive_rate(fields.get("delta")) is not None:
            atb_char = _extract_character_key(fields.get("owner"), "")
            if atb_char:
                ingestion.atb_gain_ms_by_char[atb_char].append(ts_ms)
        return True

    if " SKILL_CAST_START " in raw_line:
        fields = _extract_fields(raw_line)
        cast_skill = str(fields.get("skill") or "")
        cast_character_key = _extract_character_key(fields.get("owner"), cast_skill)
        cast_record = {
            "ts_ms": ts_ms,
            "line_no": line_no,
            "skill": cast_skill,
            "owner": fields.get("owner"),
            "owner_id": fields.get("ownerId"),
            "skill_inst_id": fields.get("inst"),
            "skill_source": fields.get("skillSource") or fields.get("skill_source"),
            "source_character_key": cast_character_key,
            "end_ts_ms": None,
        }
        ingestion.skill_casts.append(cast_record)
        inst_key = str(cast_record.get("skill_inst_id") or "")
        if inst_key:
            ingestion.active_skill_casts_by_inst[inst_key] = cast_record
        if cast_character_key:
            if ingestion.first_party_action_ms is None and not _is_generic_runtime_skill_id(cast_skill):
                ingestion.first_party_action_ms = ts_ms
            rows = ingestion.recent_skill_casts_by_char[cast_character_key]
            rows.append(
                {
                    "ts_ms": ts_ms,
                    "skill": cast_skill,
                    "owner": fields.get("owner"),
                    "skill_inst_id": fields.get("inst"),
                    "skill_source": fields.get("skillSource") or fields.get("skill_source"),
                }
            )
            del rows[:-16]
        return True

    if " SKILL_CAST_END " in raw_line:
        fields = _extract_fields(raw_line)
        inst_key = str(fields.get("inst") or "")
        cast_record = ingestion.active_skill_casts_by_inst.pop(inst_key, None) if inst_key else None
        if cast_record is not None:
            cast_record["end_ts_ms"] = ts_ms
            cast_record["end_line_no"] = line_no
        return True
    return False


def _is_generic_runtime_skill_id(skill_key: str | None) -> bool:
    return bool(re.fullmatch(r"skill_\d+", str(skill_key or "")))
