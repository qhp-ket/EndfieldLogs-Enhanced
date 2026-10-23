"""BUFF names and recorded sources for display; no inferred ownership."""
from functools import lru_cache
import json
import re

from .runtime_paths import bundle_root
from .skill_names import character_name, skill_label


_EFFECT_LABELS = {'增伤', '独立增伤', '攻击提升', '攻击力提升', '暴击', '暴击率',
    '暴击伤害', '易伤', '脆弱', '减抗', '减防', '防御降低', '抗性降低',
    '连击增伤', '技能增伤', '受伤增加', '物理增伤', '法术增伤', '增幅',
    '承伤易伤', '物理脆弱', '碎甲', '加速', '缓速'}


def _human_name(value, key=''):
    text = str(value or '').strip()
    if not text or '\ufffd' in text or text in {key, key.removeprefix('buff_')}:
        return ''
    if re.fullmatch(r'[A-Za-z0-9_./-]+', text) and '_' in text:
        return ''
    return text


@lru_cache(maxsize=1)
def _manifest_names():
    path = bundle_root()/'data/akedata/buff/manifest.json'
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding='utf-8-sig'))
    # The shipped manifest mostly contains code names, not localized names.
    # Do not label an ID with its underscore-stripped spelling as a real name.
    return {row['id']: name for row in rows
            if (name := _human_name(row.get('name'), str(row.get('id') or '')))}


def buff_source_text(event):
    key = str(event.get('source_character_key') or '')
    raw_name = str(event.get('source_character_name') or '')
    owner = character_name(key, raw_name) if key or raw_name else ''
    skill = str(event.get('source_skill_key') or '')
    label = skill_label(skill).name if skill else ''
    if label == skill:
        label = ''
    weapon = _human_name(event.get('source_weapon_name'))
    parts = list(dict.fromkeys(p for p in (owner, label, weapon) if p))
    return ' · '.join(parts) or '未知来源'


def buff_display_name(event):
    key = str(event.get('event_key') or '')
    for field in ('buff_display_name', 'buff_name'):
        if name := _human_name(event.get(field), key):
            return name
    if name := _manifest_names().get(key):
        return name
    name = _human_name(event.get('event_name'), key)
    # Canonical event_name may only describe modifier categories. Such a
    # category is useful after the source, but is not the BUFF's actual name.
    parts = [part.strip() for part in name.split('/') if part.strip()]
    if parts and not all(part in _EFFECT_LABELS for part in parts):
        return name
    source = buff_source_text(event)
    return source + (' · ' + name if name else '')
