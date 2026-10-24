"""Chinese display names verified against the pinned AKEData tables.

This is a view adapter. Keys, grouping and canonical analysis stay unchanged.
Unknown identifiers remain visible and are never matched by character alone.
"""
from __future__ import annotations
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def dictionary() -> dict:
    return json.loads((Path(__file__).parent / 'assets/skill_names_zh.json').read_text(encoding='utf-8'))


@dataclass(frozen=True, slots=True)
class SkillLabel:
    name: str
    category: str
    group_key: str = ''


def character_name(key: str, fallback: str = '') -> str:
    return dictionary()['chars'].get(key, {}).get('n') or fallback or key


def _category(key: str) -> str:
    if '_ultimate_skill' in key:
        return '大招'
    if re.search(r'_combo(?:_\d+)?_skill', key):
        return '连携'
    if re.search(r'_normal_skill|_skill$|_skill_\d+', key):
        return '战技'
    if re.search(r'_attack\d*(?:_|$)|_dash_attack|_plunging_attack|_power_attack', key):
        return '普攻'
    return '其他'


@lru_cache(maxsize=8192)
def skill_label(key: str, fallback: str = '') -> SkillLabel:
    data = dictionary()
    normalized = re.sub(r'_attack_(\d+)', r'_attack\1', key)
    index = data['skillIndex']
    groups = data['groups']
    matched, group = '', ''
    if key in groups:
        group = key
    else:
        parts = normalized.split('_')
        candidates = ['_'.join(parts[:n]) for n in range(len(parts), 2, -1)]
        for candidate in candidates:
            if candidate in index:
                matched, group = candidate, index[candidate]
                break
        if not group:
            for candidate in candidates:
                if not re.search(r'_(?:normal_skill|combo_skill|ultimate_skill|combo|attack\d*)$', candidate):
                    continue
                matches = [k for k in index if k.startswith(candidate + '_')]
                targets = {index[k] for k in matches}
                if len(targets) == 1:
                    matched, group = candidate, targets.pop()
                    break
    if not group:
        return SkillLabel(fallback or key or '未知技能', _category(normalized))
    name, category_index = groups[group]
    suffix = normalized[len(matched):].lstrip('_') if matched else ''
    action = ''
    attack = re.search(r'_attack(\d+)(?:_|$)', normalized)
    if attack:
        segment = int(attack[1])
        action = '①②③④⑤⑥⑦⑧⑨⑩'[segment-1] if 1 <= segment <= 10 else f'第{segment}段'
    elif '_power_attack' in normalized:
        action = '重击'
    elif '_plunging_attack' in normalized:
        action = '下落'
    elif '_dash_attack' in normalized:
        action = '闪避'
    suffixes = {'projhit':'弹体命中', 'abilityrange':'范围', 'laser':'激光', 'total':'合计',
                'seal':'印记', 'finisher':'收招', 'start':'起手', 'end':'收招', 'hit':'命中',
                'explode':'爆炸', 'explosion':'爆炸', 'boom':'爆炸'}
    suffix_match = re.fullmatch(r'([a-z]+)(?:_?(\d+))?', suffix)
    detail = suffix
    if suffix_match and suffix_match[1] in suffixes:
        detail = suffixes[suffix_match[1]] + (f'·{suffix_match[2]}' if suffix_match[2] else '')
    details = [s for s in (action, detail) if s]
    return SkillLabel(name + (' · ' + ' · '.join(details) if details else ''), data['cats'][category_index], group)
