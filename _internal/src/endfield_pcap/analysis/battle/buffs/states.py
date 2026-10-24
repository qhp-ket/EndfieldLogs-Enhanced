"""Collapse canonical BUFF windows into display states, never combat effects.

Exact IDs and actor instances delimit tracks. Only an explicit Stack policy
and distinct observed UIDs establish layers; refreshes never invent stacks.
"""
from __future__ import annotations
from collections import defaultdict


def buff_tracks(events):
    groups = defaultdict(list)
    for event in events:
        key = tuple(str(event.get(k) or '') for k in (
            'event_key', 'source_character_key', 'source_actor_id',
            'target_character_key', 'target_actor_id'))
        groups[key].append(event)
    for key, rows in groups.items():
        rows.sort(key=lambda e: float(e.get('ts_ms_from_start') or 0))
        # Mirrored packet observations can expose aliases for one instance.
        roots = {}
        def find(uid):
            roots.setdefault(uid, uid)
            if roots[uid] != uid:
                roots[uid] = find(roots[uid])
            return roots[uid]
        for event in rows:
            ids = [str(u) for u in [event.get('buff_uid'), *(event.get('buff_uid_aliases') or [])] if u is not None]
            for uid in ids[1:]:
                roots[find(uid)] = find(ids[0])
        windows = []
        for i, event in enumerate(rows):
            start = float(event.get('ts_ms_from_start') or 0)
            end = start + max(0., float(event.get('duration_ms') or 0))
            uid = event.get('buff_uid')
            windows.append((start, end, find(str(uid)) if uid not in (None, '') else f'unknown:{i}', event, i))
        stacking = {e.get('stacking_type') for e in rows} == {'Stack'}
        replace = all(e.get('stacking_type') in {
            'Refresh', 'Unique', 'EnhanceAndRefresh'
        } for e in rows)
        cuts = {t for start, end, *_ in windows for t in (start, end)}
        cuts.update(float(o['at_ms']) for e in rows for o in e.get('buff_enable_observations') or []
                    if min(cuts) <= float(o['at_ms']) <= max(cuts))
        cuts = sorted(cuts)
        segments = []
        for start, end in zip(cuts, cuts[1:]):
            active = [w for w in windows if w[0] <= start < w[1]]
            def enabled(w):
                observations = [o for o in w[3].get('buff_enable_observations') or [] if o['at_ms'] <= start]
                return not observations or max(observations, key=lambda o: (o['at_ms'], o.get('line_no') or 0))['enabled']
            active = [w for w in active if enabled(w)]
            if replace and active:
                # Latest refresh replaces old expiry, including a shorter one.
                latest = max(w[0] for w in windows if w[0] <= start)
                active = [w for w in active if w[0] == latest]
            if not active:
                continue
            identities = {w[2] for w in active}
            known = all(not uid.startswith('unknown:') for uid in identities)
            layers = len(identities) if stacking and known else (1 if replace or len(identities) == 1 else None)
            limits = [int(w[3]['stack_limit']) for w in active if w[3].get('stack_limit')]
            if layers is not None and limits:
                layers = min(layers, min(limits))
            expiry_values = [(w[3].get('buff_lifetime') or {}).get('expiry_ms_from_start') for w in active]
            # Older cached snapshots lack lifetime evidence; do not treat a
            # snapshot cut or a battle end as a proven expiry time.
            legacy = all('buff_lifetime' not in w[3] for w in active)
            expiry_known = all(v is not None for v in expiry_values)
            expiry = max(float(v) for v in expiry_values) if expiry_known else max(
                float(w[3].get('actual_end_ms_from_start', w[1])) for w in active)
            state = dict(start_ms=start, end_ms=end, stacks=layers, expiry_ms=expiry,
                         boundary=(not expiry_known and not legacy) or any(w[3].get('end_is_observation_boundary') for w in active))
            if segments and segments[-1]['end_ms'] == start and all(
                    segments[-1][k] == state[k] for k in ('stacks', 'expiry_ms', 'boundary')):
                segments[-1]['end_ms'] = end
            else:
                segments.append(state)
        # Keep real gaps, but episodes share the same track key.
        episodes = []
        for segment in segments:
            if not episodes or episodes[-1][-1]['end_ms'] < segment['start_ms']:
                episodes.append([])
            episodes[-1].append(segment)
        for states in episodes:
            start, end = states[0]['start_ms'], states[-1]['end_ms']
            evidence = [e for a, b, _, e, _ in windows if a < end and b > start]
            yield key, start, end, states, evidence


def buff_state_text(states, at_ms=None):
    if not states:
        return ''
    if at_ms is None:
        layers = [s['stacks'] for s in states]
        count = f"峰值 {max(layers)} 层" if all(v is not None for v in layers) else '层数未知'
        final = states[-1]
        end = '观测至' if final['boundary'] else '结束于'
        return f"{count} · {end} {final['expiry_ms']/1000:.2f}s"
    state = next((s for s in states if s['start_ms'] <= at_ms < s['end_ms']), None)
    if state is None:
        return '未生效'
    count = f"{state['stacks']} 层" if state['stacks'] is not None else '层数未知'
    duration = '持续时间未知' if state['boundary'] else f"剩余 {max(0., state['expiry_ms']-at_ms)/1000:.2f}s"
    return f'{count} · {duration}'
