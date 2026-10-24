"""Read-only presentation model for the optional local website-style analysis.

Reuse the native analysis adapters, including their evidence boundaries. This
module never parses logs, infers casts, or allocates damage contributions.
"""
from __future__ import annotations
import json
import math
from bisect import bisect_right
from endfield_pcap.analysis.battle.detail import timeline_blocks, skill_rows
from endfield_pcap.analysis.battle.enemy import (
    enemy_observations,
    enemy_label,
    hit_resistance,
    ELEMENT_NAMES,
    number,
)
from endfield_pcap.analysis.battle.energy import energy_series, control_segments, energy_value_at
from endfield_pcap.analysis.battle.buffs.states import buff_state_text
from endfield_pcap.analysis.battle.layout import CATEGORY_ORDER, CATEGORY_NAMES
from endfield_pcap.data.skill_frames import display_bounds
from endfield_pcap.data.skill_names import character_name
from endfield_pcap.analysis.battle.time import format_time


def display_number(value):
    value = number(value)
    return f'{value:,.2f}' if value is not None else '未知'


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_safe(v) for v in value]
    return value


class WebBattleModel:
    def __init__(self, snapshot, label):
        self.snapshot, self.label = snapshot, label
        self.blocks = timeline_blocks(snapshot)
        self.enemies, self.observations = enemy_observations(snapshot)
        self.energy = energy_series(snapshot)
        self.controls = control_segments(snapshot)
        self._details = {}
        self._descriptions = {}

    def description(self, index, unit):
        key = (index, unit)
        if key not in self._descriptions:
            self._descriptions[key] = self.blocks[index].description(unit)
        return self._descriptions[key]

    def block_details(self, index):
        """Fetch original evidence only when inspected; never alter the snapshot."""
        if not 0 <= index < len(self.blocks):
            return '{}'
        if index not in self._details:
            block = self.blocks[index]
            self._details[index] = json.dumps(json_safe(dict(
                description={unit: self.description(index, unit) for unit in ('seconds', 'frames')},
                summary=block.contribution_summary(), events=block.events)),
                ensure_ascii=False, allow_nan=False, default=str)
        return self._details[index]

    def payload(self):
        participants = [dict(p, display_name=character_name(str(p['character_key']), str(p.get('character_name') or '')))
                        for p in self.snapshot.get('participants') or []]
        blocks = []
        for index, block in enumerate(self.blocks):
            hits = [dict({k: e.get(k) for k in ('ts_ms_from_start', 'value', 'rdps_basis_value',
                         'rdps_contributions', 'poise_damage')}, target_label=enemy_label(e), resistance=hit_resistance(e),
                         element_name=ELEMENT_NAMES.get(e.get('damage_element'), '未知属性'))
                    for e in block.events if e.get('event_type') == 'damage']
            blocks.append(dict(id=index, owner=block.character_key, lane=block.lane,
                category=block.category, name=block.name, start=block.start_ms, end=block.end_ms,
                bounds=display_bounds(block), reference=bool(block.frame_reference.get('end_ms') is not None),
                track=block.buff_track, states=block.buff_states, buff_text=buff_state_text(block.buff_states),
                hits=hits))
        names = {p['character_key']: p['display_name'] for p in participants}
        for block in self.blocks:
            names.setdefault(block.character_key, character_name(block.character_key))
        enemy_rows = []
        for obs in self.observations:
            ts = number(obs.get('target_stats_snapshot_ts_ms'))
            stamp = f'{int(ts)//3600000%24:02}:{int(ts)//60000%60:02}:{ts/1000%60:06.3f}' if ts is not None else '未知'
            enemy_rows.append([obs['name'], stamp, display_number(obs.get('target_defense')),
                *[display_number((obs.get('target_resistance_points') or {}).get(k)) for k in ELEMENT_NAMES],
                f"{obs.get('target_resistance_points_source') or '抗性未知'} · 解析段行 {obs.get('target_stats_snapshot_line_no', '未知')}"])
        observed = {tuple(obs['key']) for obs in self.observations}
        for enemy in self.enemies:
            if tuple(enemy['key']) not in observed:
                enemy_rows.append([enemy['name'], *(['未知']*8), '缺少可绑定的 ENTITY_STATS'])
        return json_safe(dict(label=self.label, battle=self.snapshot.get('battle') or {},
            quality=self.snapshot.get('snapshot_quality') or {}, participants=participants, names=names,
            blocks=blocks, skills=skill_rows(self.snapshot), enemies=self.enemies, enemy_rows=enemy_rows,
            damage_events=[{k: e.get(k) for k in ('ts_ms_from_start', 'value', 'source_character_key', 'rdps_contributions')}
                           for e in self.snapshot.get('timeline_events') or [] if e.get('event_type') == 'damage'],
            energy=self.energy, controls=self.controls, categories=CATEGORY_ORDER, category_names=CATEGORY_NAMES))

    def json(self):
        return json.dumps(self.payload(), ensure_ascii=False, allow_nan=False, default=str)

    def hover(self, kind, index, stamp, unit):
        unit = 'frames' if unit == 'frames' else 'seconds'
        prefix = format_time(stamp, unit)
        if kind == 'block' and 0 <= index < len(self.blocks):
            return self.description(index, unit)
        if kind == 'buff' and 0 <= index < len(self.blocks):
            block = self.blocks[index]
            return f'{prefix} · {block.name}\n{buff_state_text(block.buff_states, stamp)}\n'+self.description(index, unit)
        if kind == 'poise' and 0 <= index < len(self.enemies):
            enemy = self.enemies[index]
            samples = enemy['samples']
            i = bisect_right([p['time_ms'] for p in samples], stamp)-1
            if i < 0:
                return f"{prefix} · {enemy['name']} · 失衡值未知（此前没有观测）"
            point = samples[i]
            note = '实测' if abs(point['time_ms']-stamp) < .001 else (
                '最近观测 '+format_time(point['time_ms'], unit)+'；不推算期间变化')
            return f"{prefix} · {enemy['name']} · 失衡观测值 {point['value']:g}（{note}）"
        value, quality = energy_value_at(self.energy, stamp)
        text = f'全队技力 {value:.2f} · {quality}' if value is not None else f'全队技力 {quality}'
        main = next((s['name'] for s in self.controls if s['start_ms'] <= stamp < s['end_ms']), '未知')
        result = f'{prefix} · {text} · 主控观测 {main}'
        point = next((p for p in self.energy['samples'] if abs(p['time_ms']-stamp) < .5), None)
        if point is not None:
            result += (f"\n变化 {display_number(point.get('delta'))} · 恢复速度 {display_number(point.get('recovery_speed'))} / 秒"
                       f"\n{point.get('reason') or '未知原因'} · {point.get('source') or ''}")
        return result
