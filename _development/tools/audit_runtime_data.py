"""Inventory retained runtime data; no parser changes or speculative deletion."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / '_internal/data/resource-manifest.json'
BASELINE_SHA256 = 'dbddebee37320fa3da91b2e1e747c30b16c66e893d9a1387d52fbbee0dc74571'
DATASETS = {
    'akedata': dict(purpose='Character, skill, buff, weapon, equipment and enemy definitions; dynamic per-ID lookups and fallback',
                    readers=['battle_log_parser.py', 'hit_debug.py', 'battle_payload_builder.py', 'buff_display.py', 'loadout_static.py', 'battle_buff_labels.py']),
    'local_semantics': dict(purpose='Typed skill/buff semantics, classifier hints, team-energy and skill-frame presentation rules',
                            readers=['battle_log_parser.py', 'battle_energy_evidence.py', 'skill_frame_reference.py']),
    'local_static': dict(purpose='Static skill catalogues, typed buff roots, element masks and attribute-zone configuration',
                         readers=['battle_log_parser.py']),
    'local_tables': dict(purpose='Character/weapon/equipment/dungeon tables, localization and numeric ID mapping',
                         readers=['battle_log_parser.py', 'hit_debug.py', 'battle_payload_builder.py', 'packet_resolver.py', 'game_data.py', 'loadout_static.py', 'trace_bridge.py']),
    'packet_semantics': dict(purpose='Packet resolver bundle, numeric mappings, mechanism and approved rDPS semantic registries',
                             readers=['packet_resolver.py', 'battle_log_parser.py', 'hit_debug.py']),
    'public': dict(purpose='Contract tag labels; rotation assets are excluded from the runtime projection',
                   readers=['battle_log_parser.py']),
    'message_ids': dict(purpose='Client/server message ID registries and generated-source provenance', readers=['message_registry.py']),
    'jsondata': dict(purpose='Character names, actor image mapping and dungeon fallback metadata',
                     readers=['game_data.py', 'gui_main.py', 'service.py', 'trace_bridge.py']),
}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def resources():
    for folder in ('data', 'jsondata'):
        for path in sorted((ROOT / '_internal' / folder).rglob('*')):
            if path.is_file() and path != MANIFEST and path.name != 'runtime-data.zip' and path.suffix.lower() != '.md':
                yield path


def generate(archive):
    if json.loads(MANIFEST.read_text(encoding='utf8')).get('schema_version') == 2:
        raise ValueError('Use extract_runtime_data.py with local raw inputs to rebuild the runtime projection')
    if digest(archive) != BASELINE_SHA256:
        raise ValueError('Expected the verified complete official 3.0.12 archive')
    rows = []
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        for path in resources():
            relative = path.relative_to(ROOT / '_internal').as_posix()
            baseline = 'EndfieldLogsClient/_internal/' + relative
            sha = digest(path)
            origin = ('official_3_0_12_unchanged' if hashlib.sha256(bundle.read(baseline)).hexdigest() == sha else
                      'modified_from_official_3_0_12') if baseline in names else 'development_addition'
            parts = relative.split('/')
            dataset = 'jsondata' if parts[0] == 'jsondata' else parts[1] if parts[1] in DATASETS else 'message_ids'
            rows.append(dict(path=relative, bytes=path.stat().st_size, sha256=sha, dataset=dataset, origin=origin))
    result = dict(schema_version=1, root='_internal', source_release='ZMDLogs 3.0.12 (2026-10-16)',
                  source_archive_sha256=BASELINE_SHA256,
                  source_url='https://zmdlogs.com/downloads/EndfieldLogsClient_3.0.12_20261016.zip',
                  policy='Retained resources; inventory does not grant redistribution rights or prove unused files removable.',
                  datasets=DATASETS, files=rows)
    MANIFEST.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps(dict(files=len(rows), bytes=sum(r['bytes'] for r in rows),
                         origins=dict(Counter(r['origin'] for r in rows))), indent=2))


def verify():
    result = json.loads(MANIFEST.read_text(encoding='utf8'))
    expected = set()
    for row in result['files']:
        path = (ROOT / '_internal' / row['path']).resolve()
        if not path.is_relative_to(ROOT / '_internal'):
            raise ValueError('Resource path escapes _internal')
        if row['path'] in expected:
            raise ValueError('Duplicate resource path: ' + row['path'])
        expected.add(row['path'])
        if not path.is_file() or path.stat().st_size != row['bytes'] or digest(path) != row['sha256']:
            raise ValueError('Missing or changed resource: ' + row['path'])
    actual = {p.relative_to(ROOT / '_internal').as_posix() for p in resources()}
    if actual != expected:
        raise ValueError('Resource file set changed; review inventory rather than silently accepting it')
    print(f'Verified {len(expected)} retained runtime resources and SHA-256 hashes.')


def exercise():
    sys.path.insert(0, str(ROOT / '_internal/src'))
    from endfield_pcap.environment_paths import configure_paths
    handles = configure_paths(ROOT)
    os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(ROOT / '_internal')
    observed = defaultdict(set)
    current = ['imports']

    def audit(event, args):
        if event != 'open' or not isinstance(args[0], (str, os.PathLike)):
            return
        path = Path(args[0]).absolute()
        if path.is_relative_to(ROOT / '_internal/data') or path.is_relative_to(ROOT / '_internal/jsondata'):
            observed[path.relative_to(ROOT / '_internal').as_posix()].add(current[0])

    sys.addaudithook(audit)
    from parser_core.battle_log_parser import parse_raw_battle_log_text
    from parser_core.unified import parse_overlay_battle_snapshot_text, parse_hit_viewer_log_text
    from parser_core.live import LiveOverlayBattleParser
    from uploader_core.battle_payload_builder import build_battle_upload_payloads_from_log
    for path in sorted((ROOT / '_internal/packages/parser_core/tests/fixtures').glob('*.log')):
        text = path.read_text(encoding='utf8')
        for name, call in [('raw', lambda: parse_raw_battle_log_text(text, include_rdps_debug=True)),
                           ('viewer', lambda: parse_hit_viewer_log_text(text)),
                           ('overlay', lambda: parse_overlay_battle_snapshot_text(text)),
                           ('live', lambda: (lambda p: (p.feed_lines(text.splitlines()), p.snapshot()))(LiveOverlayBattleParser())),
                           ('uploader_payload', lambda: build_battle_upload_payloads_from_log(str(path), fast_unverified=True))]:
            current[0] = name
            call()
    current[0] = 'live_packet_resolver'
    from endfield_pcap.packet_resolver import PacketResolver
    PacketResolver(ROOT / '_internal')
    current[0] = 'gui_presenters'
    from endfield_pcap.battle_buff_labels import _manifest_names
    from endfield_pcap.battle_energy_evidence import energy_rules
    from endfield_pcap.skill_frame_reference import frame_rules
    _manifest_names(); energy_rules(); frame_rules()
    output = ROOT / '_development/verification/runtime-data-observations.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(dict(scope='Representative synthetic cases only. Unobserved does not mean unused.',
                      observed={k: sorted(v) for k, v in sorted(observed.items())}), indent=2) + '\n', encoding='utf8')
    print(f'Observed {len(observed)} runtime resource reads across parser entries, uploader payload, packet resolver and GUI presenters.')


def references():
    """Record candidate IO sites and data-path expressions, including dynamic lookups.

    This is an inspection index, not whole-program dependency analysis. It also
    includes non-resource IO so an indirect helper cannot silently disappear.
    """
    roots = [ROOT / '_internal/src/endfield_pcap',
             ROOT / '_internal/packages/parser_core/parser_core',
             ROOT / '_internal/packages/uploader_core/uploader_core']
    sites = []
    for folder in roots:
        for path in sorted(folder.rglob('*.py')):
            if 'proto_generated' in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                kind = None
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, 'id', '')
                    if name in {'open', 'read_text', 'read_bytes', 'load', 'loads', 'glob', 'rglob',
                                '_read_json', '_load_json', '_iter_json_entries'}:
                        kind = 'io_candidate'
                if isinstance(node, (ast.BinOp, ast.Constant)):
                    literals = [child.value for child in ast.walk(node)
                                if isinstance(child, ast.Constant) and isinstance(child.value, str)]
                    if any(text in {'data', 'jsondata'} or text.startswith(('data/', 'jsondata/')) for text in literals):
                        kind = 'data_path'
                if kind:
                    sites.append(dict(file=path.relative_to(ROOT).as_posix(), line=node.lineno,
                                      kind=kind, expression=ast.unparse(node)))
    manifest = json.loads(MANIFEST.read_text(encoding='utf8'))
    groups = defaultdict(lambda: dict(files=0, bytes=0))
    for row in manifest['files']:
        parts = row['path'].split('/')
        group = 'jsondata' if parts[0] == 'jsondata' else parts[1] if parts[1] in DATASETS else 'message_ids'
        groups[group]['files'] += 1
        groups[group]['bytes'] += row['bytes']
    output = ROOT / '_development/verification/runtime-data-references.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(dict(
        scope='Static IO/path candidates, not proof that unobserved fields or resources are unused.',
        datasets={key: dict(**DATASETS[key], **value) for key, value in sorted(groups.items())},
        largest=sorted(manifest['files'], key=lambda row: row['bytes'], reverse=True)[:20],
        sites=sites), ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(f'Indexed {len(sites)} IO/path candidates; report: {output.relative_to(ROOT)}')
    for key, value in sorted(groups.items()):
        print(f"{key}: {value['files']} files, {value['bytes']:,} bytes")


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--refresh', type=Path, metavar='OFFICIAL_ZIP')
    parser.add_argument('--exercise', action='store_true')
    parser.add_argument('--references', action='store_true', help='Inventory source IO/path candidates and resource sizes')
    args = parser.parse_args()
    if args.refresh:
        generate(args.refresh)
    verify()
    if args.exercise:
        exercise()
    if args.references:
        references()


if __name__ == '__main__':
    main()
