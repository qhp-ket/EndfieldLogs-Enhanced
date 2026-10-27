"""Summarize observed damage basis and conservation after allocation."""
from __future__ import annotations

from parser_core.allocation.shares import _round4
from typing import Any


def _build_rdps_damage_basis(
    hits: list[dict[str, Any]],
    rdps_damage: dict[str, float],
    total_damage: int,
) -> dict[str, Any]:
    total_rdps_contribution = sum(float(value or 0.0) for value in rdps_damage.values())
    hit_conservation_deltas: list[float] = []
    for hit in hits:
        contribution_total = sum(
            float(value or 0.0)
            for value in (hit.get("rdps_contributions") or {}).values()
        )
        hit_conservation_deltas.append(contribution_total - float(hit.get("hit_value") or 0.0))

    packet_final_values = [
        float(hit["packet_final_value"])
        for hit in hits
        if hit.get("packet_final_value") is not None
    ]
    packet_raw_values = [
        float(hit["packet_raw_value"])
        for hit in hits
        if hit.get("packet_raw_value") is not None
    ]
    conservation_delta = total_rdps_contribution - float(total_damage)
    max_hit_delta = max((abs(delta) for delta in hit_conservation_deltas), default=0.0)
    hit_mismatch_count = sum(1 for delta in hit_conservation_deltas if abs(delta) > 0.01)
    return {
        "mode": "packet_hp_loss",
        "rdps_mode": "packet_hp_loss",
        "allocation_policy": "log_marginal_v1",
        "allocation_policy_basis": "accounting_convention",
        "source": "HP_V2.hit with packet eHP overkill cap",
        "hit_count": len(hits),
        "packet_grounded_hit_count": sum(1 for hit in hits if hit.get("packet_hit_value") is not None),
        "packet_hit_count": sum(1 for hit in hits if hit.get("packet_hit_value") is not None),
        "packet_final_value_count": len(packet_final_values),
        "packet_raw_value_count": len(packet_raw_values),
        "formula_grounded_hit_count": 0,
        "missing_packet_hit_count": sum(1 for hit in hits if hit.get("packet_hit_value") is None),
        "overkill_capped_hit_count": sum(1 for hit in hits if int(hit.get("overkill_damage") or 0) > 0),
        "total_damage": total_damage,
        "total_packet_final_value": _round4(sum(packet_final_values)) if packet_final_values else None,
        "total_packet_raw_value": _round4(sum(packet_raw_values)) if packet_raw_values else None,
        "total_rdps_contribution": _round4(total_rdps_contribution),
        "rdps_conservation_delta": _round4(conservation_delta),
        "rdps_conservation_ok": abs(conservation_delta) <= 0.01 and hit_mismatch_count == 0,
        "hit_conservation_mismatch_count": hit_mismatch_count,
        "max_hit_conservation_delta": _round4(max_hit_delta),
    }
