"""Log-marginal contribution pools, preserving exact arithmetic and credit order."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import isfinite, log
from typing import Any


@dataclass(frozen=True)
class ContributionShares:
    product_external: float
    attacker_share: float
    external_pool: float
    contributions: dict[str, float]


def _round4(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None



def allocate_log_marginal(
    attacker_key: str, hit_value: float, *, m_values: dict[str, float],
    external_by_zone: dict[str, list[tuple[str, float, dict[str, Any] | None]]],
    external_sum_by_zone: dict[str, float], include_debug: bool,
) -> ContributionShares:
    hit_rdps_contributions: dict[str, float] = defaultdict(float)
    if not m_values:
        product_external = 1.0
        attacker_share = hit_value
        external_pool = 0.0
        hit_rdps_contributions[attacker_key] += hit_value
    else:
        product_external = 1.0
        for value in m_values.values():
            product_external *= value

        if product_external <= 1.0:
            attacker_share = hit_value
            external_pool = 0.0
            hit_rdps_contributions[attacker_key] += hit_value
        else:
            attacker_share = hit_value / product_external
            external_pool = hit_value - attacker_share
            hit_rdps_contributions[attacker_key] += attacker_share
            log_total = sum(log(value) for value in m_values.values())
            if log_total <= 0:
                hit_rdps_contributions[attacker_key] += external_pool
            else:
                for zone, contributors in external_by_zone.items():
                    if zone not in m_values:
                        continue
                    zone_share = external_pool * (log(m_values[zone]) / log_total)
                    zone_external_sum = external_sum_by_zone[zone]
                    if zone_external_sum <= 0:
                        hit_rdps_contributions[attacker_key] += zone_share
                        continue
                    for source_key, rate, record in contributors:
                        credit = zone_share * (rate / zone_external_sum)
                        if include_debug and record is not None:
                            record["rdps_credit"] = _round4(credit)
                        hit_rdps_contributions[source_key] += credit

    normalized_contributions = {
        character_key: value
        for character_key, value in hit_rdps_contributions.items()
        if value > 0.0
    }
    return ContributionShares(product_external, attacker_share, external_pool, normalized_contributions)
