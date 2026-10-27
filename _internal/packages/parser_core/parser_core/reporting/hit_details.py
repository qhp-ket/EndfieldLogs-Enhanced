"""Project detailed per-hit allocation evidence from the same canonical evaluator."""
from __future__ import annotations

from parser_core.allocation.hit import _allocate_rdps_for_hit
from parser_core.effects.lifecycle import _build_buff_record_index
from parser_core.reporting.state import ReportState
from typing import Any


def build_debug_hits(report_state: ReportState, buff_windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project detailed per-hit allocation evidence from the same canonical evaluator."""
    debug_hits: list[dict[str, Any]] = []
    buff_records_by_uid = _build_buff_record_index(report_state.buff_starts)
    for hit in report_state.hits:
        allocation = _allocate_rdps_for_hit(
            hit,
            buff_windows,
            include_debug=True,
            buff_records_by_uid=buff_records_by_uid,
            condition_buff_records=report_state.buff_starts,
        )
        debug_hit = dict(hit)
        debug_hit["rdps_contributions"] = allocation.get("contributions_list") or []
        for key in (
            "zones",
            "ignored_effects",
            "product_external_multiplier",
            "attacker_share",
            "external_pool",
            "external_sources",
            "zone_summary",
            "buff_source_summary",
            "packet_modifier_uids",
            "packet_modifier_details",
        ):
            debug_hit[key] = allocation.get(key)
        debug_hits.append(debug_hit)
    return debug_hits
