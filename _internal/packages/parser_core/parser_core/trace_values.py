"""Normalize instance identities and retain only layout needed by legacy export."""
from __future__ import annotations

from math import isfinite


INSTANCE_FIELDS = frozenset({'attacker_id', 'target_id', 'event_inst_id', 'event_owner_id',
                             'part_inst_id', 'buff_inst_id', 'entity_id', 'object_id',
                             'weapon_id', 'gem_id', 'gem_weapon_id', 'owner_id', 'skill_inst_id', 'source_actor_id', 'operation_owner_id', 'environment_inst_id', 'projectile_id',
                             'game_inst_id', 'game_unique_id', 'interactive_obj_id', 'npc_proxy_id', 'npc_obj_id', 'battle_inst_id'})


def project_value(value, *, identity=False, ordered=False):
    if identity:
        kind = {int: 'integer', float: 'real', str: 'text', bool: 'boolean', type(None): 'null'}.get(type(value))
        if kind is None:
            raise ValueError('Instance identity must be a scalar')
        try:
            number = int(value) if value is not None else None
        except (ValueError, TypeError, OverflowError):
            number = None
        normalized = str(number) if number is not None and number >= 0 else None
        layout = {'scalar': kind}
        if kind == 'integer':
            if normalized is None:
                layout['raw'] = str(value)
        elif kind == 'text':
            if value != normalized:
                layout['raw'] = value
        elif kind in ('real', 'boolean'):
            layout['raw'] = str(value)
        return normalized, layout
    if isinstance(value, float) and not isfinite(value):
        status = 'nan' if value != value else 'positive_infinity' if value > 0 else 'negative_infinity'
        return {'number_status': status}, {'nonfinite': status}
    if isinstance(value, dict):
        result, children = {}, {}
        for key, child in value.items():
            result[key], layout = project_value(child, identity=key in INSTANCE_FIELDS,
                                                 ordered=ordered or key in ('modifier_args', 'observation'))
            if layout:
                children[key] = layout
        layout = {'keys': list(value)} if ordered else {}
        if children:
            layout['children'] = children
        return result, layout
    if isinstance(value, list):
        result, children = [], {}
        for index, child in enumerate(value):
            projected, layout = project_value(child, ordered=ordered)
            result.append(projected)
            if layout:
                children[str(index)] = layout
        return result, {'items': children} if children else {}
    return value, {}


def restore_value(value, layout):
    if not layout:
        return value
    kind = layout.get('scalar')
    if kind:
        raw = layout.get('raw', value)
        if kind == 'null':
            return None
        if kind == 'integer':
            return int(raw)
        if kind == 'real':
            return float(raw)
        if kind == 'boolean':
            return raw == 'True'
        if kind == 'text':
            return raw
        raise ValueError('Unknown legacy scalar kind')
    if 'nonfinite' in layout:
        status = layout['nonfinite']
        if value != {'number_status': status}:
            raise ValueError('Numeric evidence status differs from layout')
        return {'nan': float('nan'), 'positive_infinity': float('inf'), 'negative_infinity': -float('inf')}[status]
    if isinstance(value, dict):
        keys = layout.get('keys', list(value))
        if len(keys) != len(value) or set(keys) != set(value):
            raise ValueError('Legacy key order does not match evidence')
        children = layout.get('children', {})
        return {key: restore_value(value[key], children.get(key, {})) for key in keys}
    if isinstance(value, list):
        children = layout.get('items', {})
        return [restore_value(child, children.get(str(index), {})) for index, child in enumerate(value)]
    return value
