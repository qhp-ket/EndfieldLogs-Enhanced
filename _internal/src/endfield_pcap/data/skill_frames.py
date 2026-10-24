"""Exact skill-ID configuration references, never a second combat parser."""
import json
from functools import lru_cache
from endfield_pcap.runtime.paths import bundle_root
from endfield_pcap.analysis.battle.enemy import number
from endfield_pcap.analysis.battle.time import FRAMES_PER_SECOND, format_time


@lru_cache(maxsize=1)
def frame_rules():
    path = bundle_root()/'data/local_semantics/skill_frame_rules.json'
    if not path.is_file():
        return {'skills': {}}
    data = json.loads(path.read_text(encoding='utf8'))
    if data.get('schema_version') != 1 or data.get('frames_per_second') != FRAMES_PER_SECOND:
        raise ValueError('Unsupported skill-frame reference schema')
    return data


def skill_frame_reference(block):
    if block.lane != 'skill':
        return {}
    # A complete logged lifecycle is already the interval we need to draw.
    # Time-dilation reconstruction is unnecessary for displaying those bounds.
    cast_start = number(block.cast_evidence.get('ts_ms_from_start'))
    cast_end = number(block.cast_evidence.get('end_ms_from_start'))
    if cast_start is not None and cast_end is not None and cast_end >= cast_start:
        return {}
    intervals = {(number(e.get('actual_start_ms_from_start')),
                  number(e.get('actual_end_ms_from_start'))) for e in block.events}
    if (block.start_ms, block.end_ms) in intervals:
        return {}
    # Projectile/buff names must never inherit a parent skill's timing merely
    # because they share a prefix or Chinese dictionary group.
    key = str(block.cast_evidence.get('skill_key') or block.events[0].get('event_key') or '')
    rule = frame_rules()['skills'].get(key)
    if rule is None:
        return {}
    # For incomplete lifecycles, existing traces do not contain a complete
    # per-entity clock history with which to reconstruct the missing bounds.
    # Use the first observed hit as a display anchor, not a reconstructed
    # input/cast start. Never move the canonical cast interval or hit markers.
    hits = [number(e.get('ts_ms_from_start')) for e in block.events
            if e.get('event_type') == 'damage']
    anchor = min((stamp for stamp in hits if stamp is not None), default=None)
    duration = number(rule.get('duration_frames'))
    return dict(rule, skill_key=key, anchor_ms=anchor,
                end_ms=anchor+duration*1000/FRAMES_PER_SECOND
                if anchor is not None and duration is not None and duration > 0 else None)


def reference_description(reference, unit='seconds'):
    if not reference:
        return []
    lines = [f"AKEData 配置：{reference.get('duration_frames')}F 总时长；"
             f"exclusiveFrame={reference.get('exclusive_frames')}F（非完整动画实测）"]
    if reference['anchor_ms'] is None:
        lines.append('没有实际命中点，不套用固定时长；保留日志施放区间或起点')
    else:
        lines.append('固定显示区间：'+format_time(reference['anchor_ms'], unit)
                     +' 起，首个实际命中点 + 配置时长；不还原前摇、动画结束或时缓/时停')
    for window in reference.get('damage_windows', []):
        note = '条件分支' if window['conditional'] else '直接动作'
        lines.append(f"相对配置伤害窗口：{window['start_frame']:g}–{window['end_frame']:g}F · {note} · {window['action']}（未对齐实战时间）")
    if reference.get('unplaced_damage_actions'):
        lines.append('另有回调/异步伤害动作，没有直接可放置的相对帧')
    if not reference.get('damage_windows'):
        lines.append('该技能没有可直接放置的 Hp 伤害窗口；弹体/BUFF 等伤害不补猜')
    return lines


def display_bounds(block, show_reference=True):
    reference = block.frame_reference
    if show_reference and reference and reference.get('end_ms') is not None:
        return reference['anchor_ms'], reference['end_ms']
    return block.start_ms, block.end_ms
