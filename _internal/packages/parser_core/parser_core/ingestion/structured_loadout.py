"""Structured equipment observations enter the shared loadout state directly."""
import re

from parser_core.ingestion.fields import _parse_loadout_suits
from parser_core.ingestion.loadout import (
    apply_loadout_group, apply_loadout_snapshot, apply_active_loadout,
    loadout_slot_snapshot, loadout_stats_snapshot,
)
from parser_core.ingestion.loadout_wire import slot_observation, stats_observation, source_text
from parser_core.ingestion.structured_damage import _identity, _object
from parser_core.trace_values import restore_value


def consume_structured_loadout(ingestion, event, evidence_index):
    data = _object(event.data)
    if event.type == 'loadout_group':
        if not isinstance(data.get('reason'), str) or any(type(data.get(key)) is not int or data[key] < 0 for key in ('slot_count', 'member_count')):
            raise ValueError('Expected loadout group')
        roster = data.get('roster')
        if not isinstance(roster, list):
            raise ValueError('Expected loadout roster')
        for row in roster:
            if not isinstance(row, dict) or 'entity_id' not in row:
                raise ValueError('Expected loadout roster identity')
            _identity(row['entity_id'])
    elif event.type in ('loadout_slot', 'loadout_stats'):
        if not isinstance(data.get('template'), str):
            raise ValueError('Expected loadout character')
        for key in ('entity_id', 'weapon_id', 'gem_id', 'gem_weapon_id'):
            if key in data:
                _identity(data[key])
        if 'unplaced_equipment' in data:
            if not isinstance(data['unplaced_equipment'], list):
                raise ValueError('Expected unresolved equipment')
            for row in data['unplaced_equipment']:
                if not isinstance(row, dict) or 'entity_id' not in row:
                    raise ValueError('Expected unresolved equipment identity')
                _identity(row['entity_id'])
    else:
        raise ValueError('Expected loadout event')
    restored = restore_value(data, _object(data.get('legacy_layout', {})))
    if event.type == 'loadout_group':
        apply_loadout_group(ingestion, restored['reason'], evidence_index, event.captured_at_ms)
    elif event.type == 'loadout_slot':
        observation = slot_observation(restored)
        snapshot = loadout_slot_snapshot(observation)
        # The old active-binding rule requires a nonnegative slot, nonempty
        # scalar labels and an explicitly braced suit field, independently of chr_.
        suit = source_text(restored, 'equip_suit', '{}')
        active = observation.slot >= 0 and observation.character and observation.weapon and not re.search(r'\s', observation.character + observation.weapon)
        apply_loadout_snapshot(ingestion, snapshot, evidence_index, event.captured_at_ms)
        if active and suit.startswith('{') and '}' in suit:
            apply_active_loadout(ingestion, observation.character, observation.weapon, _parse_loadout_suits(suit))
    else:
        current = ingestion.current_loadout_group
        allow = bool(current and current['ts_ms'] == event.captured_at_ms and current['reason'] in {'SC_SYNC_CHAR_BAG_INFO', 'SC_SELF_SCENE_INFO'})
        snapshot = loadout_stats_snapshot(stats_observation(restored), allow_bound_gem=allow)
        apply_loadout_snapshot(ingestion, snapshot, evidence_index, event.captured_at_ms, stats=True)
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
