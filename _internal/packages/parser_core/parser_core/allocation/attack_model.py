"""Classify active attack dependence from the existing calculation evidence."""
from __future__ import annotations

from parser_core.catalog.skill_damage import _load_skill_action_damage_units
from parser_core.ingestion.fields import _coerce_optional_float
from typing import Any


def observed_attack_dependence(hit: dict[str, Any]) -> tuple[str, Any]:
    """Classify active attack dependence from the existing calculation evidence."""
    calculation = hit.get('damage_calculation')
    calculations = [calculation] if isinstance(calculation, dict) else []
    if not calculations and 'damage_calculation' in hit:
        calculations = [unit['damage_calculation'] for units in
                        _load_skill_action_damage_units(str(hit.get('skill_key') or '')).values()
                        for unit in units if unit.get('damage_attribute_type') == 'hp'
                        and isinstance(unit.get('damage_calculation'), dict)]
    attack_kinds = []
    for candidate in calculations:
        if candidate.get('source') != 'current_typed_damage_unit':
            attack_kinds.append('unknown')
            continue
        custom = candidate.get('atkCalculation') or {}
        kind = custom.get('$type')
        if candidate.get('simpleCalculation') is True:
            attack_kinds.append('linear')
        elif candidate.get('simpleCalculation') is not False:
            attack_kinds.append('unknown')
        elif kind in {'Beyond.Gameplay.Core.AtkScaleCalculation', 'Beyond.Gameplay.Core.BreakingAttackCalculation'}:
            attack_kinds.append('linear')
        elif kind in {'Beyond.Gameplay.Core.DefiniteValueCalculation', 'Beyond.Gameplay.Core.PrimaryAttrCalculation'}:
            attack_kinds.append('independent')
        elif kind == 'Beyond.Gameplay.Core.MultiplyAttributeCalculation':
            if custom.get('attributeType') != 'Atk' or custom.get('valueSource') != 'AttackerOrHealer':
                attack_kinds.append('independent')
            else:
                addition = custom.get('addition') or {}
                attack_kinds.append('linear' if addition.get('useBlackboardKey') is False
                                    and _coerce_optional_float(addition.get('value')) == 0.0 else 'affine')
        else:
            attack_kinds.append('unknown')
    attack_kind = (attack_kinds[0] if attack_kinds and len(set(attack_kinds)) == 1 else
                   'linear' if 'damage_calculation' not in hit else 'unknown')
    if attack_kind == 'affine' and not isinstance(calculation, dict):
        attack_kind = 'unknown'  # Different units cannot borrow one set of BB parameters.
    hit['attack_damage_dependency'] = attack_kind
    return attack_kind, calculation
