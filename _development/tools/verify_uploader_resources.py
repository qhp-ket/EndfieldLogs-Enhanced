"""Check every official uploader resource and compare original-parser payloads.

No login, upload, capture or GUI automation. Uses synthetic logs only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def payloads(data_root, output):
    # Test the unmodified official parser/uploader sources, not our development
    # parser. Each data root gets a fresh process so all lru caches are isolated.
    official = ROOT / '_development/official-release/EndfieldLogsClient/_internal'
    sys.path[:0] = [str(official / 'packages/parser_core'), str(official / 'packages/uploader_core')]
    os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(data_root)
    from uploader_core.battle_payload_builder import build_battle_upload_payloads_from_log
    from uploader_core.upload_document import build_raw_log_upload_document
    result = {}
    fixtures = ROOT / '_internal/packages/parser_core/tests/fixtures'
    for name in ('synthetic_fire_corrosion.log', 'synthetic_corrosion_packet.log',
                 'synthetic_combo_skill.log', 'synthetic_combo_ultimate.log',
                 'rdps_snapshot_contract.log', 'ink_recording_contract.log'):
        path = fixtures / name
        result[name] = dict(payloads=build_battle_upload_payloads_from_log(str(path), include_source_metadata=True),
                            document=build_raw_log_upload_document(str(path)))
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding='utf8')


def verify(stage, output, runtime_root=None):
    sys.path.insert(0, str(ROOT / '_development/tools'))
    from build_portable import excluded
    original = ROOT / 'Uploader'
    packaged = stage / 'Uploader'
    expected = {p.relative_to(original).as_posix(): p for p in original.rglob('*')
                if p.is_file() and not excluded(p.relative_to(original))}
    actual = {p.relative_to(packaged).as_posix() for p in packaged.rglob('*') if p.is_file()}
    assert actual == expected.keys()
    changed = saved = binary_count = 0
    for relative, source in expected.items():
        data = source.read_bytes()
        target = (packaged / relative).read_bytes()
        assert target == data, relative
        if target != data:
            changed += 1
            saved += len(data)-len(target)
        if source.suffix.lower() in {'.dll', '.pyd', '.exe'}:
            binary_count += 1
    output.mkdir(parents=True, exist_ok=True)
    for label, data_root in [('original', original / 'EndfieldLogsUploader/_internal'),
                             ('packaged', packaged / 'EndfieldLogsUploader/_internal')]:
        env = dict(os.environ)
        for key in list(env):
            if key.upper().startswith(('PYTHON', 'ENDFIELD_')):
                env.pop(key)
        program = (runtime_root or stage) / '_internal/python/python.exe'
        command = [str(program), '-B', str(Path(__file__).resolve()), '--payloads',
                   '--stage', str(data_root), '--output', str(output / (label+'.json'))]
        # The isolated worker needs only the packaged dependency groups.
        subprocess.run(command, env=env, check=True, timeout=180)
    left = json.loads((output / 'original.json').read_text(encoding='utf8'))
    right = json.loads((output / 'packaged.json').read_text(encoding='utf8'))
    assert left == right, 'Official uploader payloads differ'
    result = dict(files=len(expected), changed_json_files=changed, saved_bytes=saved,
                  unchanged_native_files=binary_count, synthetic_logs=len(left),
                  exact_official_payload_and_upload_document_equality=True)
    (output / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--payloads', action='store_true')
    parser.add_argument('--runtime-root', type=Path, help='Main app staging used for isolated payload verification')
    args = parser.parse_args()
    if args.payloads:
        # ._pth intentionally blocks external site-packages; add only the
        # dependencies of the staged app, never the developer's installation.
        app = Path(sys.executable).resolve().parents[2]
        sys.path[:0] = [str(app / '_internal/python_deps/common'), str(app / '_internal/python_deps/gui')]
        payloads(args.stage.resolve(), args.output.resolve())
    else:
        verify(args.stage.resolve(), args.output.resolve(), args.runtime_root.resolve() if args.runtime_root else None)
