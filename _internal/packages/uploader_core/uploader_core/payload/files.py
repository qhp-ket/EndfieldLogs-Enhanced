"""Read and verify trace files, segment battles and preserve cross-battle observations."""
from __future__ import annotations
from datetime import datetime
import copy
import os
from pathlib import Path
from parser_core.ingestion.entities import _parse_entity_stats_snapshot
from parser_core.ingestion.loadout import extract_char_skill_levels_from_text
from uploader_core.log_integrity import load_raw_log_integrity
from parser_core.critical_context import update_critical_observation
from parser_core.battle_splitter.trace import _split_trace_into_battles
from uploader_core.payload.loadout_evidence import (
    _raw_loadout_entries_for_segment,
    _raw_text_loadout_state,
)
from uploader_core.payload.projection import (
    _build_payload_from_segment,
)


_MANAGED_INCREMENTAL_TAIL_BYTES = 8 * 1024 * 1024


def _is_uploadable_battle_payload(payload: dict) -> bool:
    battle = payload.get("battle") if isinstance(payload, dict) else None
    if not isinstance(battle, dict):
        return False
    try:
        total_damage = int(battle.get("totalDamage") or 0)
    except (TypeError, ValueError):
        total_damage = 0
    if total_damage <= 0:
        return False
    if not payload.get("participants"):
        return False
    return any(
        event.get("laneType") == "skill" and (event.get("value") or 0)
        for event in payload.get("timelineEvents") or []
        if isinstance(event, dict)
    )


def _payload_fingerprint(payload: dict) -> str:
    battle = payload.get("battle") if isinstance(payload, dict) else None
    if not isinstance(battle, dict):
        return ""
    return str(battle.get("battleFingerprint") or "")


def _read_incremental_tail_text(path: Path) -> str:
    try:
        tail_bytes = int(os.environ.get("ENDFIELD_MANAGED_INCREMENTAL_TAIL_BYTES") or _MANAGED_INCREMENTAL_TAIL_BYTES)
    except ValueError:
        tail_bytes = _MANAGED_INCREMENTAL_TAIL_BYTES
    tail_bytes = max(1024 * 1024, tail_bytes)
    size = path.stat().st_size
    if size <= tail_bytes:
        return path.read_text(encoding="utf-8", errors="replace")
    with path.open("rb") as handle:
        handle.seek(max(0, size - tail_bytes))
        raw = handle.read()
    text = raw.decode("utf-8", errors="replace")
    newline_index = text.find("\n")
    if newline_index >= 0:
        text = text[newline_index + 1 :]
    return text


def build_battle_upload_payloads_from_log(
    log_path: str,
    *,
    known_fingerprints: set[str] | None = None,
    known_battle_index: int | None = None,
    include_source_metadata: bool = False,
    fast_unverified: bool = False,
) -> list[dict]:
    log_file = Path(log_path)
    use_incremental_tail = fast_unverified and known_battle_index is not None
    if fast_unverified:
        raw_content = (
            _read_incremental_tail_text(log_file)
            if use_incremental_tail
            else log_file.read_text(encoding="utf-8", errors="replace")
        )
        proof = None
    else:
        integrity = load_raw_log_integrity(log_path)
        raw_content = str(integrity.get("raw_content") or "")
        proof = integrity.get("proof") if isinstance(integrity.get("proof"), dict) else None
    reference_date = datetime.fromtimestamp(log_file.stat().st_mtime).astimezone().date()
    segments = _split_trace_into_battles(raw_content)
    source_file_name = log_file.name
    known = {str(item) for item in (known_fingerprints or set()) if str(item)}
    if known_battle_index is not None and not use_incremental_tail:
        segments = [
            segment
            for segment in segments
            if int(segment.get("battle_index") or 0) > int(known_battle_index)
        ]
    if not segments:
        return []
    raw_loadout_groups, raw_loadout_fallback = _raw_text_loadout_state(raw_content)
    raw_char_skill_levels = extract_char_skill_levels_from_text(raw_content)
    critical_overrides: dict[int, dict] = {}
    critical_states: dict[str, dict] = {}
    segment_starts: dict[int, list[int]] = {}
    for segment in segments:
        segment_starts.setdefault(int(segment["start_line_index"]), []).append(int(segment["battle_index"]))
    for line_index, raw_line in enumerate(raw_content.splitlines()):
        if line_index in segment_starts:
            snapshot = copy.deepcopy(critical_states)
            for observation in snapshot.values():
                observation["lines"] = {attr: line - line_index for attr, line in observation["lines"].items()}
            for index in segment_starts[line_index]:
                critical_overrides[index] = snapshot
        if "GAME_TIMER_RESET source=CAPTURE_SESSION_START" in raw_line:
            critical_states.clear()
        partial = " ENTITY_ATTR_UPDATE " in raw_line
        parsed = _parse_entity_stats_snapshot(raw_line.replace(" ENTITY_ATTR_UPDATE ", " ENTITY_STATS ", 1) if partial else raw_line)
        if parsed is not None and parsed[1].get("ts_ms") is not None:
            entity_id, observation = parsed
            update_critical_observation(critical_states, entity_id, observation, line_index + 1, partial=partial)

    payloads: list[dict] = []
    reverse_until_known = bool(known) and (known_battle_index is None or use_incremental_tail)
    iterable = reversed(segments) if reverse_until_known else segments
    for segment in iterable:
        raw_loadout_entries = _raw_loadout_entries_for_segment(
            raw_loadout_groups,
            raw_loadout_fallback,
            segment,
        )
        try:
            payload = _build_payload_from_segment(
                segment=segment,
                source_file_name=f"{Path(source_file_name).stem}#battle{segment['battle_index']}{Path(source_file_name).suffix}",
                reference_date=reference_date,
                proof=proof,
                raw_loadout_entries=raw_loadout_entries,
                raw_char_skill_levels=raw_char_skill_levels,
                critical_attributes_override_by_actor=critical_overrides.get(int(segment["battle_index"])),
            )
        except ValueError as exc:
            if "HP_V2" in str(exc):
                continue
            raise
        if include_source_metadata:
            payload["_sourceBattleIndex"] = int(segment.get("battle_index") or 0)
        if known and _payload_fingerprint(payload) in known:
            break
        if _is_uploadable_battle_payload(payload):
            payloads.append(payload)
    if reverse_until_known:
        payloads.reverse()
    return payloads


def build_battle_upload_payload_from_log(log_path: str) -> dict:
    payloads = build_battle_upload_payloads_from_log(log_path)
    if not payloads:
        raise ValueError("未在日志中识别到可上传的 battle。")
    return payloads[0]
