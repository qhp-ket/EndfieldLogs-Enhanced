"""Versioned evidence projection for canonical battle snapshots.

This module does not allocate damage, infer evidence, or change availability
flags consumed by existing displays. Its states describe evidence, not numbers.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

SNAPSHOT_QUALITY_SCHEMA_VERSION = 1
_JS_SAFE_INTEGER = (1 << 53) - 1
_TIMING_FIELDS = (
    "duration_ms", "time_source", "timeline_zero_source", "timer_start_seen",
    "timer_end_seen", "official_timer_start_seen", "official_timer_end_seen",
    "official_timer_observed_elapsed_ms", "packet_timer_elapsed_ms",
    "timer_integrity_ok", "timer_integrity_reasons", "timer_evidence",
    "timer_start_inferred", "timer_window_valid", "official_pass_confirmed",
    "completion_source",
)


def _json_evidence(value: Any) -> Any:
    """Copy JSON evidence; preserve wide integer identities as decimal strings."""
    if isinstance(value, dict):
        return {key: _json_evidence(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_evidence(item) for item in value]
    if type(value) is int and abs(value) > _JS_SAFE_INTEGER:
        return str(value)
    if isinstance(value, float) and not isfinite(value):
        return None
    return value


def _positive_number(value: Any) -> bool:
    return type(value) in (int, float) and isfinite(value) and value > 0


def build_snapshot_quality(report: dict[str, Any], *, include_evidence: bool = True) -> dict[str, Any]:
    """Project existing canonical evidence conservatively, without reparsing.

    Missing evidence is retained as null. Unresolved lists retain their original
    scope; only the canonical preflight/basis decides which affect this battle.
    """
    battle = report.get("battle") or {}
    preflight = report.get("rdps_preflight")
    basis = report.get("rdps_damage_basis")
    if basis is None:
        basis = battle.get("rdps_damage_basis")
    preflight_map = preflight if isinstance(preflight, dict) else {}
    basis_map = basis if isinstance(basis, dict) else {}
    rdps_reasons = []
    if not isinstance(preflight, dict):
        rdps_reasons.append("missing_rdps_preflight")
    if not isinstance(basis, dict):
        rdps_reasons.append("missing_rdps_damage_basis")
    for field, value in (
        ("rdps_preflight_ok", preflight_map.get("ok")),
        ("rdps_damage_basis_preflight_ok", basis_map.get("rdps_preflight_ok")),
        ("rdps_strict_ok", basis_map.get("rdps_strict_ok")),
        ("rdps_conservation_ok", basis_map.get("rdps_conservation_ok")),
    ):
        if value is not True:
            rdps_reasons.append(field + ("_failed" if value is False else "_unknown"))
    count = preflight_map.get("blocker_count")
    blockers = preflight_map.get("blockers")
    if type(count) is not int or count != 0 or not isinstance(blockers, list) or blockers:
        rdps_reasons.append("rdps_blockers_present_or_unknown")
    if basis_map.get("unresolved_damage_actor_count"):
        rdps_reasons.append("unresolved_damage_actors")
    if basis_map.get("missing_packet_hit_count"):
        rdps_reasons.append("missing_packet_hits")
    if basis_map.get("hit_conservation_mismatch_count"):
        rdps_reasons.append("hit_conservation_mismatches")
    hit_count = basis_map.get("hit_count")
    if type(hit_count) is not int or hit_count <= 0:
        rdps_reasons.append("missing_damage_events" if hit_count == 0 else "damage_hit_count_unknown")
    rdps_status = "provisional" if rdps_reasons else "verified"
    if not isinstance(basis, dict) or (type(hit_count) is int and hit_count <= 0):
        rdps_status = "unavailable"

    timing_reasons = []
    duration = battle.get("duration_ms")
    if not _positive_number(duration):
        timing_reasons.append("duration_missing_or_nonpositive")
    integrity = battle.get("timer_integrity_ok")
    if integrity is not True:
        timing_reasons.append("timer_integrity_failed" if integrity is False else "timer_integrity_unknown")
    integrity_reasons = battle.get("timer_integrity_reasons")
    if not isinstance(integrity_reasons, list) or integrity_reasons:
        timing_reasons.append("timer_integrity_reasons_present_or_unknown")
    validity = battle.get("timer_window_valid")
    if validity is not True:
        timing_reasons.append("timer_window_invalid" if validity is False else "timer_window_validity_unknown")
    if not battle.get("time_source"):
        timing_reasons.append("time_source_unknown")
    if battle.get("timer_start_inferred") is True:
        timing_reasons.append("timer_start_inferred")
    elif battle.get("timer_start_inferred") is not False:
        timing_reasons.append("timer_start_inference_unknown")
    timing_status = "provisional" if timing_reasons else "verified"
    if not _positive_number(duration) or validity is False:
        timing_status = "unavailable"

    statuses = (rdps_status, timing_status)
    status = "unavailable" if "unavailable" in statuses else "provisional" if "provisional" in statuses else "verified"
    return {
        "schema_version": SNAPSHOT_QUALITY_SCHEMA_VERSION,
        "status": status,
        "rdps": {
            "status": rdps_status,
            "reasons": rdps_reasons,
            **({"evidence": _json_evidence({
                "rdps_preflight": preflight,
                "rdps_damage_basis": basis,
                "unresolved_hits": report.get("unresolved_hits"),
                "unresolved_buff_actions": report.get("unresolved_buff_actions"),
            })} if include_evidence else {}),
        },
        "timing": {
            "status": timing_status,
            "reasons": timing_reasons,
            **({"evidence": _json_evidence({key: battle.get(key) for key in _TIMING_FIELDS})} if include_evidence else {}),
        },
    }


def with_snapshot_quality(report: dict[str, Any]) -> dict[str, Any]:
    """Add the contract to a newly built canonical report, preserving all fields."""
    report["snapshot_quality"] = build_snapshot_quality(report)
    return report
