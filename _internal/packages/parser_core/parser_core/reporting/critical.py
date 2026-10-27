"""Attach hit critical evidence and recorded state-change boundaries for diagnostics."""
from __future__ import annotations

from collections import defaultdict
from parser_core.catalog.buff_templates import _load_current_buff_roots
from parser_core.catalog.packet_semantics import _load_num_id_str_buff_map
from parser_core.critical_context import build_critical_context
from parser_core.critical_context import critical_buff_profile
from parser_core.reporting.state import ReportState
from typing import Any


def attach_critical_context(report_state: ReportState, buff_windows: list[dict[str, Any]]) -> None:
    """Attach hit critical evidence and recorded state-change boundaries for diagnostics."""
    critical_ids = {str(record.get("event_key") or "") for record in report_state.buff_starts}
    for hit in report_state.hits:
        critical_ids.update(hit.get("_active_attacker_buff_ids") or [])
        critical_ids.update(hit.get("_active_target_buff_ids") or [])
    critical_roots = _load_current_buff_roots()
    critical_numeric_map = _load_num_id_str_buff_map()
    critical_profiles = {
        key: critical_buff_profile(critical_roots.get(critical_numeric_map.get(key, key)))
        for key in critical_ids
    }
    critical_changes: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for record in report_state.buff_starts:
        resource = str(record.get("event_key") or "")
        if not critical_profiles.get(resource, {}).get("attributes"):
            continue
        identity = (str(record.get("uid") or ""), str(record.get("target_actor_id") or ""), resource)
        for key in ("dynamic_bb_events", "enable_observations", "repeated_creation_observations"):
            for observation in record.get(key) or []:
                if (isinstance(observation, dict) and type(observation.get("line_no")) is int
                        and observation.get("status") != "duplicate"):
                    critical_changes[identity].add(observation["line_no"])
    for window in buff_windows:
        identities = {str(window.get("uid") or ""), *[str(uid) for uid in window.get("uid_aliases") or []]}
        changes = set()
        for uid in identities:
            changes.update(critical_changes.get((uid, str(window.get("target_actor_id") or ""), str(window.get("event_key") or "")), set()))
        if changes:
            window["critical_state_change_lines"] = sorted(changes)
    critical_windows = [window for window in buff_windows
                        if (profile := critical_profiles.get(str(window.get('event_key') or ''), {})).get('attributes')
                        and not profile.get('processors')]
    for hit in report_state.hits:
        hit["critical_context"] = build_critical_context(hit, hit.get("critical_observation"), critical_profiles, critical_windows)
