"""One team resource, separate control observations, and explicit estimates.

ATB owners identify the controlled actor at observation time, not ownership of
the resource. Only packet samples are measured values. Inter-sample modeling
never participates in canonical damage/rDPS calculations.
"""
import json
import math
from bisect import bisect_right
from functools import lru_cache
from endfield_pcap.analysis.battle.enemy import number
from endfield_pcap.runtime.paths import bundle_root
from endfield_pcap.data.skill_names import character_name


@lru_cache(maxsize=1)
def energy_rules():
    path = bundle_root() / 'data/local_semantics/team_energy_rules.json'
    if path.is_file():
        return json.loads(path.read_text(encoding='utf8'))
    return {'capacity': 300, 'base_recovery_per_second': 8, 'skills': {}}


def _observations(snapshot):
    return sorted((dict(row, time_ms=stamp) for row in snapshot.get('atb_events') or []
                   if (stamp := number(row.get('ts_ms_from_start'))) is not None),
                  key=lambda r: (r['time_ms'], number(r.get('line_no')) or 0))


def energy_tracks(snapshot, character=''):
    # Character filters deliberately do not filter a shared resource.
    samples = [dict(row, value=value) for row in _observations(snapshot)
               if (value := number(row.get('value'))) is not None]
    return [dict(key=('team', ''), name='全队共享技力', samples=samples)] if samples else []


def control_segments(snapshot):
    observations = [row for row in _observations(snapshot) if row.get('character_key')]
    if not observations:
        return []
    end = max(number((snapshot.get('battle') or {}).get('duration_ms')) or 0,
              observations[-1]['time_ms'])
    result = []
    if observations[0]['time_ms'] > 0:
        result.append(dict(start_ms=0., end_ms=observations[0]['time_ms'], character_key='',
                           name='未知', evidence='首次主控观测之前，没有切换证据'))
    for i, row in enumerate(observations):
        start = max(0., row['time_ms'])
        stop = min(end, observations[i+1]['time_ms']) if i+1 < len(observations) else end
        if stop <= start:
            continue
        key = row['character_key']
        if result and result[-1]['character_key'] == key and result[-1]['end_ms'] == start:
            result[-1]['end_ms'] = stop
        else:
            result.append(dict(start_ms=start, end_ms=stop, character_key=key,
                name=character_name(key), evidence='ATB owner 主控观测；色块延续至下一次观测，不是精确切换时刻'))
    return result


def _cast_inputs(snapshot, rules):
    costs, pauses, missing = [], [], set()
    for cast in snapshot.get('casts') or []:
        stamp = number(cast.get('ts_ms_from_start'))
        if stamp is None:
            continue
        skill = str(cast.get('skill_key') or '')
        rule = rules.get('skills', {}).get(skill)
        if rule and number(rule.get('cost')) is not None:
            cost = float(rule['cost'])
            if cost > 0:
                costs.append((stamp, cost, skill))
                pauses.append((stamp, stamp+500.))
        elif '_normal_skill' in skill and skill.endswith('_normal_skill'):
            missing.add('部分战技消耗未知')
        if '_ultimate_skill' in skill and skill.endswith('_ultimate_skill'):
            end = number(cast.get('end_ms_from_start'))
            if end is not None and end >= stamp:
                pauses.append((stamp, end))
            else:
                missing.add('部分终结技恢复暂停终点未知')
    return costs, pauses, missing


def energy_series(snapshot):
    tracks = energy_tracks(snapshot)
    if not tracks:
        return dict(samples=[], segments=[], notes=['没有技力锚点，无法推算初始值'])
    samples = tracks[0]['samples']
    rules = energy_rules()
    # The packet schema exposes value and recovery speed, but no capacity.
    # A high sample is a lower bound, never proof of the stage's maximum.
    # Use only a versioned stage rule when available; do not silently clamp
    # every stage to the ordinary-mode 300 or assume its starting resource.
    stage_id = str((snapshot.get('battle') or {}).get('dungeon_context_id') or '')
    stage = rules.get('stages', {}).get(stage_id, {})
    known_capacity = number(stage.get('capacity'))
    if known_capacity is not None and known_capacity < max(p['value'] for p in samples):
        known_capacity = None  # Packet evidence overrides an outdated table.
    capacity = known_capacity if known_capacity is not None and known_capacity > 0 else math.inf
    costs, pauses, missing = _cast_inputs(snapshot, rules)
    end = max(number((snapshot.get('battle') or {}).get('duration_ms')) or 0, samples[-1]['time_ms'])
    segments = []
    last_recovery = number(stage.get('base_recovery_per_second'))
    for index, point in enumerate(samples):
        start = point['time_ms']
        stop = samples[index+1]['time_ms'] if index+1 < len(samples) else end
        recovery = number(point.get('recovery_speed'))
        if recovery is not None:
            last_recovery = recovery
        else:
            recovery = last_recovery
        if stop <= start:
            continue
        if recovery is None:
            missing.add('恢复速度未知的区间不补画；不套用普通关卡 8/s')
            continue
        boundaries = {start, stop}
        deductions = {}
        for stamp, cost, skill in costs:
            if start < stamp < stop:
                boundaries.add(stamp)
                deductions[stamp] = deductions.get(stamp, 0.) + cost
        for a, b in pauses:
            if start < a < stop:
                boundaries.add(a)
            if start < b < stop:
                boundaries.add(b)
        value = point['value']
        edges = sorted(boundaries)
        for a, b in zip(edges, edges[1:]):
            value = max(0., value-deductions.get(a, 0.))
            rate = 0. if any(left <= a < right for left, right in pauses) else recovery
            final = max(0., min(capacity, value + rate*(b-a)/1000))
            segments.append(dict(start_ms=a, end_ms=b, start_value=value, end_value=final,
                                 rate=rate, capacity=capacity, confidence='estimated'))
            value = final
    if known_capacity is None:
        missing.add('本关技力上限未知，未按普通关卡 300 截断；图形纵轴不是上限')
    if samples[0]['time_ms'] > 0:
        missing.add('初始技力未知，不从普通关卡初始值补画')
    notes = ['实心点为实测；虚线为自然恢复及已知战技消耗推算，锚点到来即校正',
             '闪避、动态返还、脱战与恢复暂停可能缺失；推算不能当作精确实测']
    return dict(samples=samples, segments=segments, capacity=known_capacity,
                initial_value=next((p['value'] for p in samples if p['time_ms'] == 0), None),
                notes=notes+sorted(missing))


def energy_value_at(series, stamp):
    samples = series['samples']
    index = bisect_right([p['time_ms'] for p in samples], stamp)-1
    if index < 0:
        return None, '未知（首次技力观测之前）'
    point = samples[index]
    if abs(point['time_ms']-stamp) < 0.5:
        return point['value'], '实测'
    segments = series['segments']
    segment_index = bisect_right([p['start_ms'] for p in segments], stamp)-1
    if segment_index < 0:
        return None, '未知'
    segment = segments[segment_index]
    if not segment['start_ms'] <= stamp <= segment['end_ms']:
        return None, '未知（超出观测/推算范围）'
    value = max(0., min(segment['capacity'], segment['start_value']+
                       segment['rate']*(stamp-segment['start_ms'])/1000))
    return value, '估算（缺失状态可能影响数值）'
