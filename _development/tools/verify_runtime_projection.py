"""Compare canonical results from raw and extracted data in separate processes."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def fingerprint(value):
    def encode(item):
        if isinstance(item, (set, frozenset)):
            return sorted(item)
        raise TypeError(type(item).__name__)
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), default=encode).encode('utf8')).hexdigest()


def collect(data_root):
    sys.path.insert(0, str(ROOT / '_internal/src'))
    from endfield_pcap.environment_paths import configure_paths
    handles = configure_paths(ROOT)
    os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(data_root)
    from parser_core import battle_log_parser as p, hit_debug
    hit_debug._REPO_ROOT = data_root
    results = {}
    # All normalized no-argument parser catalogues, including strict proofs.
    # Internal raw-entry loaders intentionally have a reduced schema.
    excluded = {'_load_classifier_hints', '_load_local_skill_semantic_entries',
                '_load_local_buff_semantic_entries'}
    for name, fn in vars(p).items():
        if name.startswith('_load_') and callable(fn) and hasattr(fn, 'cache_info') and name not in excluded:
            if not inspect.signature(fn).parameters:
                results['catalogue:' + name] = fingerprint(fn())
    skill_ids = [path.stem for path in (data_root / 'data/akedata/skill/items').glob('*.json')]
    results['all_skill_metadata'] = fingerprint({key: p._load_skill_item_metadata(key) for key in skill_ids})
    results['all_skill_action_damage_units'] = fingerprint({key: p._load_skill_action_damage_units(key)
                                                           for key in p._load_official_skill_damage_catalog()})
    buff_ids = list(p._load_local_buff_semantic_entries())
    results['all_enhanced_child_specs'] = fingerprint({key: p._enhanced_action_child_effect_specs(key) for key in buff_ids})
    results['all_buff_stack_limits'] = fingerprint({key: p._buff_stack_limit(key) for key in buff_ids})
    results['all_wrapper_decisions'] = fingerprint({key: p._is_effectless_wrapper_record({'event_key': key}) for key in buff_ids})
    from parser_core.unified import parse_overlay_battle_snapshot_text, parse_hit_viewer_log_text
    from uploader_core.battle_payload_builder import build_battle_upload_payloads_from_log
    fixtures = ROOT / '_internal/packages/parser_core/tests/fixtures'
    for path in sorted(fixtures.glob('*.log')):
        text = path.read_text(encoding='utf8')
        results['raw:' + path.name] = fingerprint(p.parse_raw_battle_log_text(text, include_rdps_debug=True))
        results['overlay:' + path.name] = fingerprint(parse_overlay_battle_snapshot_text(text))
        results['viewer:' + path.name] = fingerprint(parse_hit_viewer_log_text(text))
        results['upload:' + path.name] = fingerprint(build_battle_upload_payloads_from_log(str(path), fast_unverified=True))
    from endfield_pcap.packet_resolver import PacketResolver
    resolver = PacketResolver(data_root)
    for attr in ('static_buff_by_numeric', 'static_skill_by_numeric', 'buff_by_numeric',
                 'skill_by_owner_numeric', 'skill_by_numeric_unique', 'known_buff_ids'):
        results['packet:' + attr] = fingerprint(getattr(resolver, attr))
    from endfield_pcap import loadout_static, battle_buff_labels, trace_bridge, battle_energy_evidence, skill_frame_reference
    for module in (loadout_static, battle_buff_labels, trace_bridge, battle_energy_evidence, skill_frame_reference):
        module.bundle_root = lambda: data_root
    for name in ('weapon_catalog', 'equip_piece_catalog', 'attribute_type_catalog'):
        results['gui:' + name] = fingerprint(getattr(loadout_static, name)())
    from endfield_pcap.game_data import load_name_index
    results['gui:character_names'] = fingerprint(load_name_index(data_root / 'jsondata/CharacterNameIndex.json'))
    results['gui:buff_names'] = fingerprint(battle_buff_labels._manifest_names())
    results['gui:energy_rules'] = fingerprint(battle_energy_evidence.energy_rules())
    results['gui:frame_rules'] = fingerprint(skill_frame_reference.frame_rules())
    results['live:dungeon_enemy_hints'] = fingerprint(trace_bridge._load_dungeon_enemy_hints())
    return dict(checks=results, skill_count=len(skill_ids), buff_count=len(buff_ids))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--collect', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.collect:
        args.output.write_text(json.dumps(collect(args.collect.resolve()), indent=2)+'\n', encoding='utf8')
        return
    args.output.mkdir(parents=True, exist_ok=True)
    values = []
    for label, path in [('raw', args.raw), ('runtime', args.runtime)]:
        if path is None:
            parser.error('--raw and --runtime are required')
        target = args.output / (label + '.json')
        subprocess.run([sys.executable, '-B', __file__, '--collect', str(path), '--output', str(target)], check=True)
        values.append(json.loads(target.read_text(encoding='utf8')))
    raw, runtime = values
    differences = [key for key in raw['checks'].keys() | runtime['checks'].keys()
                   if raw['checks'].get(key) != runtime['checks'].get(key)]
    report = dict(checks=len(raw['checks']), skill_count=raw['skill_count'], buff_count=raw['buff_count'],
                  differences=sorted(differences), passed=not differences)
    (args.output / 'comparison.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps(report, indent=2))
    if differences:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
