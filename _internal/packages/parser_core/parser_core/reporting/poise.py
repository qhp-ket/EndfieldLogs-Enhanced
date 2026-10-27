"""Observed poise events and their exact hit-identity projection."""
from __future__ import annotations

from parser_core.ingestion.fields import _coerce_int, _coerce_optional_float, _extract_fields
import re
from typing import Any


_POISE_RE = re.compile(r"\bPOISE_V1\b")


def _parse_poise_damage_event(raw_line: str, ts_ms: int, line_no: int) -> dict[str, Any] | None:
    if not _POISE_RE.search(raw_line):
        return None
    fields = _extract_fields(raw_line)
    if str(fields.get("type") or "") != "PoiseDamage":
        return None
    source = str(fields.get("source") or "").strip()
    orig_source = str(fields.get("origSource") or "").strip()
    if source in {"", "unknown"}:
        source = orig_source
    if source in {"", "unknown"}:
        return None
    return {
        "line_no": line_no,
        "ts_ms": ts_ms,
        "type": "PoiseDamage",
        "value": _coerce_optional_float(fields.get("value")),
        "current_value": _coerce_optional_float(fields.get("cur")),
        "source": source,
        "source_int": _coerce_int(fields.get("sourceInt"), default=0) or None,
        "orig_source": orig_source if orig_source not in {"", "unknown"} else None,
        "orig_source_int": _coerce_int(fields.get("origSourceInt"), default=0) or None,
    }


def _apply_poise_damage_events_to_hits(
    hits: list[dict[str, Any]],
    poise_damage_events: list[dict[str, Any]],
) -> None:
    if not hits or not poise_damage_events:
        return

    for event in poise_damage_events:
        source = str(event.get("source") or "")
        source_int = event.get("source_int")
        orig_source_int = event.get("orig_source_int")
        event_ts_ms = int(event.get("ts_ms") or 0)
        matches = [
            hit
            for hit in hits
            if int(hit.get("ts_ms") or 0) == event_ts_ms
            and (
                source in {str(hit.get("skill_key") or ""), str(hit.get("skill_family_key") or "")}
                or (source_int is not None and source_int == hit.get("template_int_id"))
                or (orig_source_int is not None and orig_source_int == hit.get("original_template_int_id"))
            )
        ]
        if not matches:
            continue
        for hit in matches:
            hit["poise_damage"] = {
                "type": event.get("type") or "PoiseDamage",
                "value": event.get("value"),
                "current_value": event.get("current_value"),
                "source": source,
                "source_int": source_int,
                "orig_source": event.get("orig_source"),
                "orig_source_int": orig_source_int,
            }
