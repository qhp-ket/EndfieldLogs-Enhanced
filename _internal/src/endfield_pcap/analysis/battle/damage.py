"""Read-only one-second cumulative damage curves from canonical hit evidence."""
from __future__ import annotations
import math


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def damage_series(snapshot, metric='dps', character=''):
    """DPS is cumulative damage / elapsed time, matching the report's definition.

    Only existing rD allocations contribute to rDMG. Missing allocations are
    counted explicitly, and an entirely unknown allocation produces no curve.
    """
    duration = _number((snapshot.get('battle') or {}).get('duration_ms')) or 0
    if duration <= 0 or metric not in {'dmg', 'dps', 'rdmg', 'rdps'}:
        return dict(metric=metric, points=[], missing=0, hits=0, duration_ms=max(0, duration))
    relative = metric in {'rdmg', 'rdps'}
    bins = {}
    owners = dict.fromkeys(str(p['character_key']) for p in snapshot.get('participants') or [] if p.get('character_key'))
    missing = hits = 0
    for event in snapshot.get('timeline_events') or []:
        stamp = _number(event.get('ts_ms_from_start'))
        if event.get('event_type') != 'damage' or stamp is None or not 0 <= stamp <= duration:
            continue
        hits += 1
        bucket = min(math.ceil(duration/1000)-1, int(stamp//1000))
        if relative:
            values = [(str(c.get('character_key') or ''), _number(c.get('value')))
                      for c in event.get('rdps_contributions') or []]
            values = [(owner, value) for owner, value in values if owner and value is not None]
            missing += not bool(values)
        else:
            values = [(str(event.get('source_character_key') or ''), _number(event.get('value')))]
        for owner, value in values:
            if value is None or (character and owner != character):
                continue
            owners.setdefault(owner, None)
            row = bins.setdefault(bucket, {})
            row[owner] = row.get(owner, 0.)+value
    if relative and (hits == missing):
        return dict(metric=metric, points=[], missing=missing, hits=hits, duration_ms=duration)
    totals = {owner: 0. for owner in owners if not character or owner == character}
    points = [dict(time_ms=0., values=dict(totals))]
    for bucket in range(math.ceil(duration/1000)):
        for owner, value in bins.get(bucket, {}).items():
            totals[owner] = totals.get(owner, 0.)+value
        end = min(duration, (bucket+1)*1000.)
        divisor = end/1000 if metric in {'dps', 'rdps'} else 1.
        points.append(dict(time_ms=end, values={owner: value/divisor for owner, value in totals.items()}))
    return dict(metric=metric, points=points, missing=missing, hits=hits, duration_ms=duration)
