"""Presentation-only adapters for canonical history reports.

Timeline damage blocks reuse event_group_key, and skill statistics are copied
from role_skill_stats. No cast inference, timers or rDPS allocation lives here.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from endfield_pcap.data.skill_names import character_name, skill_label
from endfield_pcap.analysis.battle.enemy import number
from endfield_pcap.analysis.battle.buffs.states import buff_tracks, buff_state_text
from endfield_pcap.analysis.battle.buffs.labels import buff_display_name
from endfield_pcap.data.skill_frames import skill_frame_reference, reference_description
from endfield_pcap.analysis.battle.time import format_time


@dataclass(slots=True)
class TimelineBlock:
    character_key: str
    lane: str
    start_ms: float
    end_ms: float
    name: str
    category: str
    events: list[dict] = field(default_factory=list)
    buff_track: tuple = ()
    buff_states: list[dict] = field(default_factory=list)
    cast_evidence: dict = field(default_factory=dict)
    frame_reference: dict = field(default_factory=dict)

    def contribution_summary(self) -> dict:
        damage = [e for e in self.events if e.get('event_type') == 'damage']
        amounts, names = {}, {}
        covered = 0
        for event in damage:
            valid = [c for c in event.get('rdps_contributions') or []
                     if c.get('character_key') and number(c.get('value')) is not None]
            covered += bool(valid)
            for c in valid:
                key = str(c['character_key'])
                amounts[key] = amounts.get(key, 0.) + float(c['value'])
                names[key] = character_name(key, str(c.get('character_name') or ''))
        allocated = sum(amounts.values())
        basis = [number(e.get('rdps_basis_value')) for e in damage]
        return {'damage': sum(float(e.get('value') or 0) for e in damage),
                'basis': sum(basis) if all(v is not None for v in basis) else None,
                'covered': covered, 'hits': len(damage), 'allocated': allocated,
                'contributions': [{'key': k, 'name': names[k], 'value': v,
                                   'percent': 100 * v / allocated if allocated else 0}
                                  for k, v in sorted(amounts.items(), key=lambda kv: -kv[1])]}

    def description(self, unit='seconds') -> str:
        first = self.events[0]
        interval = (f'{self.start_ms / 1000:.3f}–{self.end_ms / 1000:.3f} 秒' if unit == 'seconds'
                    else f'{format_time(self.start_ms, unit)}–{format_time(self.end_ms, unit)}（30F/s）')
        lines = [self.name, interval,
                 f"来源：{character_name(str(first.get('source_character_key') or ''), str(first.get('source_character_name') or '未知'))}"]
        targets = sorted({str(e.get('target_character_name') or e.get('target_character_key') or '') for e in self.events} - {''})
        if targets:
            lines.append('目标：' + '、'.join(targets))
        damage = [e for e in self.events if e.get('event_type') == 'damage']
        if self.lane == 'skill':
            if self.cast_evidence:
                end = number(self.cast_evidence.get('end_ms_from_start'))
                lines.append('时间依据：SKILL_CAST_START → SKILL_CAST_END（协议施放生命周期，不代表按键或完整动画）'
                             if end is not None else '时间依据：仅有 SKILL_CAST_START；结束未知，显示起点标记')
            elif any(e.get('actual_start_ms_from_start') is not None for e in damage):
                lines.append('时间依据：核心匹配的施放起止；结束缺失时仅显示起点标记')
            else:
                lines.append('时间依据：只有命中分组，区间为首末命中；没有按键/动画起止证据')
            lines.extend(reference_description(self.frame_reference, unit))
        if damage:
            lines.append(f"伤害：{sum(float(e.get('value') or 0) for e in damage):,.2f}（{len(damage)} 次命中）")
            contributions: dict[str, float] = {}
            for event in self.events:
                for contribution in event.get('rdps_contributions') or []:
                    key = str(contribution.get('character_key') or '')
                    contributions[key] = contributions.get(key, 0) + float(contribution.get('value') or 0)
            if contributions:
                lines.append('rDMG 分配（canonical）：' + '；'.join(
                    f'{character_name(k)} {v:,.2f}' for k, v in contributions.items()))
            summary = self.contribution_summary()
            basis_text = f"{summary['basis']:,.2f}" if summary['basis'] is not None else '未知（部分命中缺失基数）'
            lines.append(f"rD 基数：{basis_text}；已分配：{summary['allocated']:,.2f}；有分配证据 {summary['covered']}/{summary['hits']} 击")
            lines.append('分配沿用核心逐击结果（包括笔意独立乘区）；缺失分配不补给攻击者。可切换下方「贡献分配 / 逐击证据」。')
        elif self.lane == 'skill':
            lines.append('施放记录（无伤害补录）')
        else:
            if self.buff_states:
                lines.append(buff_state_text(self.buff_states))
                lines.append(f'同种 BUFF 共用一行；{len(self.events)} 次状态观测（刷新不等于叠层）。')
                for state in self.buff_states:
                    lines.append(f"{state['start_ms']/1000:.3f}–{state['end_ms']/1000:.3f}s："
                                 + buff_state_text([state], state['start_ms']))
            actual = first.get('actual_duration_ms')
            if actual is not None:
                lines.append(f'实际持续时间：{float(actual) / 1000:.3f} 秒（图中仅显示战斗内区间）')
            if first.get('effects'):
                lines.append('效果：' + json.dumps(first['effects'], ensure_ascii=False))
        lines.append('代码：' + str(first.get('event_key') or ''))
        return '\n'.join(lines)


def timeline_blocks(snapshot: dict) -> list[TimelineBlock]:
    participants = {str(p['character_key']) for p in snapshot.get('participants') or []}
    blocks: dict[tuple, TimelineBlock] = {}
    casts_by_start = {}
    for index, cast in enumerate(snapshot.get('casts') or []):
        owner = str(cast.get('character_key') or '')
        if owner not in participants or str(cast.get('skill_source') or '').lower() == 'summon':
            continue
        raw = str(cast.get('skill_key') or '')
        label = skill_label(raw, str(cast.get('skill_name') or raw))
        category = _timeline_category(raw, label.category, cast.get('recovers_energy'))
        if category is None:
            continue
        start = float(cast.get('ts_ms_from_start') or 0)
        end = number(cast.get('end_ms_from_start'))
        event = dict(event_type='cast', lane_type='skill', event_key=raw, event_name=label.name,
                     source_character_key=owner, ts_ms_from_start=start)
        block = TimelineBlock(owner, 'skill', start, max(start, end if end is not None else start),
                              label.name, category, [event], cast_evidence=cast)
        blocks[('cast', index)] = block
        casts_by_start.setdefault((owner, start), []).append(block)
    for index, event in enumerate(snapshot.get('timeline_events') or []):
        source = str(event.get('source_character_key') or '')
        target = str(event.get('target_character_key') or '')
        lane = str(event.get('lane_type') or '')
        if lane != 'skill':
            continue
        owner = (target if target in participants else source) if lane == 'buff' else source
        if owner not in participants:
            continue
        start = float(event.get('ts_ms_from_start') or 0)
        duration = max(0, float(event.get('duration_ms') or 0))
        raw = str(event.get('event_key') or '')
        name = str(event.get('event_name') or raw)
        label = skill_label(raw, name)
        actual_start = number(event.get('actual_start_ms_from_start'))
        candidates = casts_by_start.get((owner, actual_start if actual_start is not None else start), [])
        matches = [b for b in candidates if _same_skill(raw, str(b.cast_evidence['skill_key']))]
        if len(matches) == 1:
            if event.get('event_type') == 'damage':
                matches[0].events.append(event)
            continue  # The complete cast channel already includes this cast.
        category = _timeline_category(raw, label.category)
        if category is None:
            continue
        actual_end = number(event.get('actual_end_ms_from_start'))
        if actual_start is not None:
            start, duration = actual_start, max(0., (actual_end if actual_end is not None else actual_start)-actual_start)
        group = event.get('event_group_key') if event.get('event_type') == 'damage' else None
        key = (owner, lane, raw, actual_start) if actual_start is not None else (
            (owner, lane, str(group)) if group else (owner, lane, index))
        if key in blocks:
            block = blocks[key]
            block.start_ms = min(block.start_ms, start)
            block.end_ms = max(block.end_ms, start + duration)
            block.events.append(event)
            continue
        blocks[key] = TimelineBlock(owner, lane, start, start + duration,
                                   label.name, category, [event])
    for track, start, end, states, events in buff_tracks(
            e for e in snapshot.get('timeline_events') or [] if e.get('lane_type') == 'buff'):
        first = events[0]
        source, target = str(first.get('source_character_key') or ''), str(first.get('target_character_key') or '')
        owner = target if target in participants else source
        if owner in participants:
            blocks[('buff', track, start)] = TimelineBlock(owner, 'buff', start, end,
                buff_display_name(first), 'BUFF', events, track, states)
    result = sorted(blocks.values(), key=lambda b: (b.start_ms, b.character_key, b.lane))
    for block in result:
        block.frame_reference = skill_frame_reference(block)
    return result


def _same_skill(first, second):
    # Use exact identifiers or the existing supplied skill family dictionary;
    # never pair different skills merely because their timestamps coincide.
    if first == second:
        return True
    a, b = skill_label(first), skill_label(second)
    return bool(a.group_key and a.group_key == b.group_key)


def _timeline_category(raw, category, recovers_energy=False):
    if category == '普攻':
        # A named power_attack or core-proven ATB recovery identifies heavy
        # attacks. Do not guess an unknown attackN is the combo finisher.
        return '重击' if '_power_attack' in raw or recovers_energy else None
    return category


def skill_rows(snapshot: dict, character: str = '') -> list[dict]:
    totals = {str(p['character_key']): float(p.get('total_damage') or 0) for p in snapshot.get('participants') or []}
    result = []
    for row in snapshot.get('role_skill_stats') or []:
        key = str(row.get('character_key') or '')
        if character and key != character:
            continue
        label = skill_label(str(row.get('skill_key') or ''), str(row.get('skill_name') or ''))
        result.append({**row, 'display_character': character_name(key, str(row.get('character_name') or '')),
                       'display_skill': label.name, 'category': label.category,
                       'damage_percent': 100 * float(row.get('total_damage') or 0) / totals[key] if totals.get(key, 0) > 0 else 0})
    return result
