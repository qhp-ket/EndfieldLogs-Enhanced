"""Public battle-log parsing entry using isolated ordered evidence and canonical reports."""
from __future__ import annotations

from parser_core.ingestion.identity import _apply_short_actor_aliases
from parser_core.ingestion.stream import _raw_battle_ingestion
from parser_core.reporting.battle import _build_raw_battle_report
from typing import Any


def parse_raw_battle_log_text(
    text: str,
    *,
    file_name: str | None = None,
    first_hit_hint: str | None = None,
    last_hit_hint: str | None = None,
    reference_date: date | None = None,
    include_rdps_debug: bool = False,
    loadout_override_by_char: dict[str, dict[str, Any]] | None = None,
    critical_attributes_override_by_actor: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    # Offline and live paths share exactly the same ingestion and projection.
    normalized = _apply_short_actor_aliases(text)
    stream = _raw_battle_ingestion(normalized, file_name=file_name,
        first_hit_hint=first_hit_hint, last_hit_hint=last_hit_hint,
        reference_date=reference_date, include_rdps_debug=include_rdps_debug,
        loadout_override_by_char=loadout_override_by_char,
        critical_attributes_override_by_actor=critical_attributes_override_by_actor)
    next(stream)
    state = stream.send(enumerate(normalized.splitlines(), 1))
    stream.close()
    return _build_raw_battle_report(state, normalized, file_name=file_name,
                                   include_rdps_debug=include_rdps_debug)
