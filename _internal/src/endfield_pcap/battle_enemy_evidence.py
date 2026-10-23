"""Read-only enemy observations; no resistance reconstruction or state simulation."""
from __future__ import annotations

from collections import defaultdict
import math

RESISTANCE_ATTRS = {'physical': 94, 'natural': 95, 'cryst': 96, 'pulse': 97, 'fire': 98, 'ether': 99}
ELEMENT_NAMES = {'physical': '物理', 'natural': '自然', 'cryst': '寒冷', 'pulse': '电磁', 'fire': '灼热', 'ether': '源石'}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def enemy_identity(event):
    return str(event.get('target_character_key') or ''), str(event.get('target_actor_id') or '')


def enemy_label(event):
    name = str(event.get('target_character_name') or event.get('target_character_key') or '未知目标')
    actor = str(event.get('target_actor_id') or '')
    return f'{name} #{actor}' if actor else f'{name}（实例未知）'


def hit_resistance(event):
    """Only explicit, consistent PKT_ATTR for this hit's element is known."""
    attr = RESISTANCE_ATTRS.get(event.get('damage_element'))
    if attr is None or event.get('packet_attr_conflict') is not False:
        return None
    tokens = (event.get('packet_attr_details') or {}).get('defender') or []
    values = [number(v) for token in tokens if str(token).partition(':')[0] == str(attr)
              for v in str(token).partition(':')[2].split(',')]
    if not values or any(v is None for v in values) or len(set(values)) != 1:
        return None
    return values[0]


def enemy_observations(snapshot):
    """Keep entity snapshots separate from per-hit effective resistance.

    POISE_V1 has no target identity. Core matches by timestamp/skill; samples
    copied to hits on different enemies are therefore displayed as unbound.
    """
    events = [e for e in snapshot.get('timeline_events') or [] if e.get('event_type') == 'damage']
    tracks = {}
    snapshots = []
    seen = set()
    candidates = defaultdict(list)
    for e in events:
        key = enemy_identity(e)
        if not key[0]:
            continue
        tracks.setdefault(key, {'key': key, 'name': enemy_label(e), 'samples': []})
        entity = e.get('target_entity') or {}
        signature = (key, entity.get('target_stats_snapshot_ts_ms'), entity.get('target_stats_snapshot_line_no'))
        if entity and signature not in seen:
            seen.add(signature)
            snapshots.append({'name': enemy_label(e), 'key': key, **entity})
        poise = e.get('poise_damage') or {}
        value = number(poise.get('current_value'))
        if value is not None:
            stamp = float(e.get('ts_ms_from_start') or 0)
            signature = (stamp, poise.get('source'), poise.get('source_int'),
                         poise.get('orig_source_int'), value, poise.get('value'))
            candidates[signature].append((key, e))
    for signature, hits in candidates.items():
        ambiguous = len({key for key, _ in hits}) > 1
        key = ('', 'unbound') if ambiguous else hits[-1][0]
        if ambiguous:
            tracks.setdefault(key, {'key': key, 'name': '目标未绑定（同刻多目标命中）', 'samples': []})
        tracks[key]['samples'].append({'time_ms': signature[0], 'value': signature[4],
                                      'change': signature[5], 'ambiguous': ambiguous})
    for track in tracks.values():
        # Last recorded value at a timestamp, isolated by enemy instance.
        track['samples'] = list({p['time_ms']: p for p in sorted(track['samples'], key=lambda p: p['time_ms'])}.values())
        track['peak'] = max((p['value'] for p in track['samples']), default=None)
    return list(tracks.values()), snapshots
