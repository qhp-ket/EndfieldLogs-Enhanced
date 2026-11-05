"""Exercise the fixed Python coroutine across complete, ordered trace batches."""
from datetime import date
from pathlib import Path
from types import ModuleType
import argparse
import base64
import copy
import hashlib
import importlib
import json
import os
import random
import struct
import sys
import tempfile
import zipfile


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--reference', type=Path, required=True)
    cli.add_argument('--manifest', type=Path, required=True)
    cli.add_argument('--output', type=Path)
    cli.add_argument('--bundled', action='store_true')
    args = cli.parse_args()
    if args.bundled and args.output is None:
        cli.error('--bundled requires an explicit local --output')
    root = Path(__file__).resolve().parents[3]
    args.output = args.output or root/'_internal/dotnet/Specs/Fixtures/battle-ingestion.json'
    metadata = json.loads(args.manifest.read_text(encoding='utf8'))
    prefix = '_internal/packages/parser_core/parser_core/'
    dependencies = {}
    for relative, expected in metadata['files'].items():
        if relative.startswith(prefix) and relative.endswith('.py'):
            digest = hashlib.sha256((args.reference/relative).read_bytes()).hexdigest()
            if digest != expected['sha256']:
                raise ValueError('Fixed ingestion reference changed: '+relative)
            dependencies[relative] = digest
    files = {}
    binary_files = {}
    if args.bundled:
        relative = '_internal/data/runtime-data.zip'
        archive_path = args.reference/relative
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        if metadata['files'][relative]['sha256'] != digest:
            raise ValueError('Fixed runtime bundle changed')
        dependencies[relative] = digest
        temporary = tempfile.TemporaryDirectory(prefix='endfield-bundled-ingestion-')
        data_root = Path(temporary.name)/'_internal'
        data_root.mkdir()
        os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(data_root)
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                target = (data_root/entry.filename).resolve()
                if not target.is_relative_to(data_root):
                    raise ValueError('Unsafe fixed resource path')
                contents = archive.read(entry)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(contents)
                if entry.filename.endswith('.json'):
                    files['_internal/'+entry.filename] = contents.decode('utf8')
                else:
                    binary_files['_internal/'+entry.filename] = base64.b64encode(contents).decode('ascii')
    package = ModuleType('parser_core')
    package.__path__ = [str(args.reference/prefix)]
    sys.modules['parser_core'] = package
    def module(name):
        return importlib.import_module('parser_core.'+name)
    stream = module('ingestion.stream')
    hits = module('ingestion.hits')
    loadout = module('ingestion.loadout')
    names = module('catalog.names')
    resources = module('catalog.resources')
    identity = module('ingestion.skill_identity')
    mapping = module('effects.packet_mapping')
    status = module('effects.enemy_status')
    buffs = module('ingestion.buff_observations')
    dynamic = module('ingestion.dynamic_evidence')
    config = json.loads(json.loads((root/'_internal/dotnet/Specs/Fixtures/loadout-snapshots.json').read_text(encoding='utf8'))[0]['config_json'])
    config.update(buffs={}, roots={}, numeric={})
    if not args.bundled:
        module('ingestion.state')._resolve_dungeon_context = lambda key: None
        names._load_num_id_str_skill_map = lambda: config['skills']
        identity._load_num_id_str_buff_map = lambda: {}
        identity._load_official_skill_damage_catalog = lambda: {}
        hits._load_skill_action_damage_units = lambda key: {}
        module('effects.damage_types')._load_skill_action_damage_units = lambda key: {}
        hits._resolve_skill_profile = lambda key: None
        for field in ('_resolve_character_name', '_resolve_enemy_name', '_resolve_skill_name'):
            setattr(hits, field, lambda key: config['names'].get(key))
        for target in (hits, status, buffs, dynamic):
            target._load_current_buff_roots = lambda: {}
        buffs._load_num_id_str_buff_map = lambda: {}
        buffs._rdps_registry_matching_effect_entry = lambda *a, **k: None
        dynamic._load_num_id_str_buff_map = lambda: {}
        dynamic._load_skill_item_metadata = lambda key: {'dynamic_action_keys': {}}
        mapping._load_packet_numeric_buff_map = lambda: {}
        mapping._load_packet_canonical_buff_map = lambda: {}
        mapping._load_mechanism_registry_by_buff_id = lambda: {}
        mapping._load_num_id_str_buff_map = lambda: {}
        loadout._load_weapon_catalog = lambda: config['weapons']
        loadout._load_equip_item_catalog = lambda: config['equipment']
        loadout._load_weapon_refine_catalog = lambda: config['refinement']
        loadout._resolve_character_name = lambda key: config['names'].get(key)
        resources._load_suit_catalog = lambda: config['suits']

    def encode(value):
        if type(value) is int: return {'int': str(value)}
        if type(value) is float: return {'f64': struct.pack('>d', value).hex()}
        if isinstance(value, (list, tuple)): return [encode(item) for item in value]
        if isinstance(value, dict): return {str(key): encode(item) for key, item in value.items()}
        if isinstance(value, set): return [encode(item) for item in sorted(value)]
        return value

    timer_fields = ('game_timer_start_ms game_timer_end_ms game_timer_elapsed_ms game_timer_window_elapsed_ms '
        'official_timer_start_ms official_timer_end_ms official_timer_elapsed_ms live_timer_elapsed_ms '
        'packet_timer_elapsed_ms timer_start_seen timer_end_seen timer_window_valid challenge_pass_confirmed '
        'official_pass_confirmed completion_source dungeon_context_id dungeon_context contract_tag_ids contract_tag_score').split()
    skill_fields = ('atb_observations atb_gain_ms_by_char skill_casts active_skill_casts_by_inst '
                    'recent_skill_casts_by_char first_party_action_ms').split()
    def snapshot(state):
        def index(record):
            return next((i for i, row in enumerate(state.buff_starts) if row is record), None)
        hit_state = dict(hits=state.hits, unresolved=state.unresolved_hits,
            indices={str(key): next(i for i, row in enumerate(state.hits) if row is value) for key, value in state.hits_by_seq.items()},
            enemies=dict(state.enemy_counter), hp=state.last_enemy_hp_by_target, roster=state.roster_order,
            participants=dict(state.participant_totals), skills=list(state.skill_totals.values()),
            baselines=state.baseline_by_character, modifier_last_seen=state.packet_modifier_last_seen_by_uid,
            loadouts=state.loadout_by_char, suits=state.active_suits_by_char, weapons=state.active_weapons_by_char,
            buffs=dict(records=[{key: value for key, value in row.items() if not key.startswith('_')} for row in state.buff_starts],
                active={key: index(value) for key, value in state.active_buff_starts_by_uid.items()},
                pending=index(state.pending_buff_record), pending_modifiers=dict(state.pending_attr_mods),
                unresolved=state.unresolved_buff_actions))
        return encode(dict(context=dict(origin=state.timestamp_clock_origin, first=state.first_context_ms,
                last=state.last_context_ms, timer_times=state.timer_observed_times,
                party_ids=state.party_actor_ids, squad=state.squad_actor_keys),
            timers={key: getattr(state, key) for key in timer_fields},
            skills={key: getattr(state, key) for key in skill_fields},
            entities=dict(entity_stats_timelines=state.entity_stats_timelines, critical_stats_by_actor=state.critical_stats_by_actor),
            loadouts=dict(loadouts=state.loadout_by_char, groups=state.loadout_groups,
                current_group=state.current_loadout_group['index'] if state.current_loadout_group is not None else None,
                active_weapons=state.active_weapons_by_char, active_suits=state.active_suits_by_char, skills=state.char_skill_levels),
            hits=hit_state, poise=state.poise_damage_events, dynamics=state.dynamic_bb_events,
            refreshes=state.buff_attribute_refresh_events))

    cases = []
    def add(name, rows, chunks=None):
        generator = stream._raw_battle_ingestion('', reference_date=date(2026, 10, 27))
        next(generator)
        batches = []
        start = 0
        for count in chunks or [1]*len(rows):
            batch = [dict(number=i+1, text=rows[i]) for i in range(start, start+count)]
            batches.append(batch)
            start += count
        assert start == len(rows)
        expected = []
        try:
            for batch in batches:
                generator.send([(row['number'], row['text']) for row in batch])
                expected.append(snapshot(generator.gi_frame.f_locals['ingestion']))
        finally:
            generator.close()
        resources_input = dict(files=files,binary_files=binary_files) if args.bundled else dict(config_json=json.dumps(config))
        cases.append(dict(name=name, **resources_input, batches=batches, expected=expected))

    def at(stamp, text):
        h, remainder = divmod(stamp, 3_600_000)
        m, remainder = divmod(remainder, 60_000)
        s, ms = divmod(remainder, 1000)
        return f'[{h:02}:{m:02}:{s:02}.{ms:03}] '+text.strip()

    slot = ' LOADOUT slot=0 char=chr_0001_alpha potential=2 weaponInstId=11 weaponTemplate=wpn_test weaponLv=2 refine=0 equipSuit={[suit_test]=3} skillIntIds=[5 101] equips={[0]=equip_test}'
    templates = [
        ' SQUAD members=[chr_0001_alpha_11 chr_0002_beta_12]',
        ' ENTITY_STATS id=11 template=chr_0001_alpha kind=character level=2 attrs=[1:40 9:0.2 10:0.5]',
        ' LOADOUT reason=SC_SELF_SCENE_INFO', slot,
        ' LOADOUT_STATS char=chr_0001_alpha weaponTemplate=wpn_test weaponLv=2 weaponInstId=11 weaponSourceSkills={101:level=2}',
        ' CHAR_SKILLS owner=chr_0001_alpha ownerId=11 skills=[101:2]',
        ' OFFICIAL_TIMER_START gameId=unknown source=Official',
        ' SKILL_CAST_START skill=chr_0001_alpha_normal_skill owner=chr_0001_alpha ownerId=11 inst=50',
        ' BUFF_START uid=7 id=buff_test owner=eny_0001_test ownerId=22 src=chr_0001_alpha srcId=11 dur=2',
        ' BB[ rate=0.2 ]',
        ' HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_test atkId=11 tgtId=22 skill=skill_test hit=100 eHP=1000',
        ' BASELINE #1 1=40 9=0.2', ' PKT_MOD #1 atk=[7] def=[]',
        ' SKILL_CAST_END inst=50',
        ' ATB_UPDATE owner=chr_0001_alpha ownerId=11 atb=2 delta=1 reason=AddValue recoverySpeed=0.1',
        ' BUFF_END uid=7', ' LIVE_TIMER_TICK elapsedMs=1500',
        ' OFFICIAL_TIMER_END isPass=1 passTime=1700 source=Official',
        ' CONTRACT_TAGS dungeonId=unknown tagIds=[1,2] score=50',
        ' DUNGEON_CONTEXT dungeonId=unknown', ' GAME_MECHANICS_TIME_FREEZE state=1',
        ' ENTITY_ATTR_UPDATE id=11 template=chr_0001_alpha kind=character attrs=[9:0.4]',
        ' GAME_TIMER_RESET source=CAPTURE_SESSION_START',
        ' BUFF_ACTION_UNRESOLVED uid=7 seq=1 actionId=2 triggerType=0 ownerId=22 srcId=11',
    ]
    canonical = [at(1000+i*100, row) for i, row in enumerate(templates)]
    if args.bundled:
        canonical = [row.replace('chr_0001_alpha','chr_0023_antal').replace('skill_test','chr_0023_antal_combo_skill') for row in canonical]
    add('ordered/all-stages', canonical)
    add('ordered/whole-batch', canonical, [len(canonical)])
    add('ordered/empty-batches', canonical, [0, 3, 0, 7, 0, len(canonical)-10, 0])
    add('clock/midnight-late-replay', [at(time, templates[10]) for time in (86_399_000, 100, 86_399_500, 100, 200)])
    add('clock/invalid-and-reset', [canonical[1], 'invalid row', 'GAME_TIMER_RESET source=CAPTURE_SESSION_START', canonical[10]])
    add('squad/duplicate-actors', [at(10, templates[0]), at(20, ' SQUAD [chr_0001_alpha_11 chr_0002_beta_11]'), at(30, ' SQUAD []')])
    add('pending/rejected-and-accepted-hits', [canonical[8], canonical[9], at(3000, ' HP_V2 #2 src=eny_0001_test atk=eny_0001_test tgt=chr_0001_alpha hit=20'), canonical[10]])
    add('loadout/outsider-invalidates', [canonical[3], at(2000, templates[10].replace('chr_0001_alpha', 'chr_0002_beta')), canonical[8]])
    # Multiple markers in one row exercise early-return priorities between stages.
    for i, left in enumerate(templates):
        right = templates[(i+3) % len(templates)]
        add('priority/'+str(i), [canonical[8], at(4000, left+' '+right), canonical[10]])
    rng = random.Random(2601027)
    for index in range(0 if args.bundled else 60):
        rows = [at(rng.choice([1000, 1001, 1100, 900, 2000]), rng.choice(templates)) for _ in range(rng.randrange(4, 13))]
        add('mixed/'+str(index), rows)
        if index < 10:
            add('mixed/batched/'+str(index), rows, [2, 0, len(rows)-2])
    if args.bundled:
        # The complete real bundle is encoded once per case; keep the large
        # resource run local while ordinary synthetic dispatch remains in CI.
        cases = cases[:3]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    args.output.with_suffix('.reference.json').write_text(json.dumps(dict(cases=len(cases),
        steps=sum(len(row['batches']) for row in cases), source_head=metadata['head'], dependencies=dependencies), indent=2), encoding='utf8')
    print('Battle ingestion fixtures:', len(cases))


if __name__ == '__main__':
    main()
