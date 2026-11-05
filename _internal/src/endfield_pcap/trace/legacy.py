"""Independent legacy export, shared by file export and compatibility checks."""
from endfield_pcap.trace.legacy_damage import damage_legacy_lines
from endfield_pcap.trace.legacy_entity import entity_legacy_lines
from endfield_pcap.trace.legacy_identity import identity_legacy_lines
from endfield_pcap.trace.legacy_loadout import loadout_legacy_lines
from endfield_pcap.trace.legacy_skill import skill_legacy_lines
from endfield_pcap.trace.legacy_buff import buff_legacy_lines
from endfield_pcap.trace.legacy_buff_packet import buff_packet_legacy_lines
from endfield_pcap.trace.legacy_dynamic import dynamic_legacy_lines
from endfield_pcap.trace.legacy_blackboard import blackboard_legacy_lines
from endfield_pcap.trace.legacy_clock import clock_legacy_lines
from endfield_pcap.trace.legacy_timer import timer_legacy_lines
from endfield_pcap.trace.legacy_context import context_legacy_lines
from endfield_pcap.trace.legacy_stage import stage_legacy_lines
from endfield_pcap.trace.legacy_historical import historical_legacy_lines


_EXPORTERS = {}
for _exporter, _types in (
    (damage_legacy_lines, ('damage',)),
    (historical_legacy_lines, ('damage_raw', 'damage_baseline', 'legacy_attribute_modifier', 'legacy_damage_modifier')),
    (entity_legacy_lines, ('entity_stats', 'entity_attributes', 'entity_value', 'entity_die', 'ability_spawn')),
    (identity_legacy_lines, ('squad', 'actor_mapping', 'character_skills', 'identity_inference')),
    (loadout_legacy_lines, ('loadout_group', 'loadout_slot', 'loadout_stats')),
    (skill_legacy_lines, ('skill_cast', 'atb', 'poise')),
    (buff_legacy_lines, ('buff_start', 'buff_end', 'buff_blackboard')),
    (buff_packet_legacy_lines, ('buff_creation', 'buff_origin', 'buff_enable', 'buff_keyword', 'buff_unresolved')),
    (dynamic_legacy_lines, ('blackboard_dynamic', 'buff_attribute_refresh', 'blackboard_skill_setting')),
    (blackboard_legacy_lines, ('blackboard_calculation', 'blackboard_modify', 'blackboard_preset', 'ink_release')),
    (clock_legacy_lines, ('clock_tick', 'clock_sync', 'time_freeze_request', 'time_freeze_state')),
    (timer_legacy_lines, ('battle_timer', 'official_timer', 'battle_phase', 'battle_timer_missing')),
    (context_legacy_lines, ('game_instance', 'game_mechanics', 'scene_battle', 'battle_reset', 'session_warning')),
    (stage_legacy_lines, ('dungeon', 'contracts', 'battle_result')),
):
    _EXPORTERS.update(dict.fromkeys(_types, _exporter))


def legacy_lines(event, *, timezone_offset_minutes):
    try:
        exporter = _EXPORTERS[event.type]
    except KeyError:
        raise NotImplementedError('Independent export is not connected for ' + event.type) from None
    return exporter(event, timezone_offset_minutes=timezone_offset_minutes)


def legacy_text(chain):
    from parser_core.trace_volumes import read_events
    offset = chain.volumes[0].header.timezone_offset_minutes
    return ''.join(line for event in read_events(chain)
                   for line in legacy_lines(event, timezone_offset_minutes=offset))
