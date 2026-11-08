"""Independent rendering of context evidence, retaining the old optional field ordering."""
from datetime import datetime, timedelta, timezone
from endfield_pcap.trace.export_values import export_data
from parser_core.ingestion.structured_context import CONTEXT_TYPES, MECHANICS
from endfield_pcap.trace.formatting import _intish


def context_legacy_lines(event, *, timezone_offset_minutes):
    if event.type not in CONTEXT_TYPES:
        raise ValueError('Expected context event with legacy layout')
    data = export_data(event)
    if event.type in ('game_instance', 'game_mechanics'):
        source = data['source']
        parts = [MECHANICS[source][2], f'source={source}']
        if data.get('game_id'):
            parts.append(f"gameId={data['game_id']}")
        for key, target in (('game_inst_id', 'gameInstId'), ('game_unique_id', 'gameUniqueId'), ('is_hunter_mode', 'isHunterMode'),
                            ('interactive_obj_id', 'interactiveObjId'), ('npc_proxy_id', 'npcProxyId'), ('npc_obj_id', 'npcObjId')):
            value = data.get(key)
            if value is not None and value != '':
                parts.append(f'{target}={int(bool(value)) if key == "is_hunter_mode" else value}')
        freezes = data.get('time_freeze_infos')
        if data['action'] == 'time_freeze' and isinstance(freezes, list):
            parts.append(f'count={len(freezes)}')
            rows = [(_intish(row.get('time_key')) or 0, _intish(row.get('total_freeze_time_in_ms')) or 0)
                    for row in freezes if isinstance(row, dict)]
            if rows:
                parts.append('freezeInfos=[' + ','.join(f'{key}:{value}' for key, value in rows) + ']')
                parts.append('totalFreezeMs=' + str(max([0, *(value for _, value in rows)])))
    elif event.type == 'scene_battle':
        parts = ['SCENE_BATTLE_STATE', f"source={data['source']}", f"inBattle={int(bool(data.get('in_battle')))}"]
    elif event.type == 'battle_reset':
        parts = ['BATTLE_RESET_STATUS']
        for key, target in (('reason', 'reason'), ('event_inst_id', 'inst'), ('battle_inst_id', 'battleInst')):
            if data.get(key) is not None:
                parts.append(f'{target}={data[key]}')
    else:
        present = lambda key: data[key] if data.get(key) is not None else 'unknown'
        parts = ['SESSION_WARNING', f"kind={data.get('kind') or 'unknown'}", f"direction={data.get('direction') or 'unknown'}",
                 f"missingBytes={present('missing_bytes')}", f"gapCount={present('startup_tcp_gap_count')}"]
    local = datetime.fromtimestamp(event.captured_at_ms / 1000, timezone(timedelta(minutes=timezone_offset_minutes)))
    return [f"[{local.strftime('%H:%M:%S.%f')[:-3]}] {' '.join(parts)}\n"]
