"""Compare parser reports and ordered ingestion with a fixed source reference."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def canonical(value):
    """Preserve scalar types, map-key types and ordered evidence without tolerances."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        return {'float': value.hex()}
    if isinstance(value, (date, datetime)):
        return {type(value).__name__: value.isoformat()}
    if isinstance(value, dict):
        rows = [(canonical(key), canonical(item)) for key, item in value.items()]
        return {'map': sorted(rows, key=lambda pair: json.dumps(pair[0], sort_keys=True))}
    if isinstance(value, (set, frozenset)):
        return {'set': sorted((canonical(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))}
    if isinstance(value, (tuple, list)):
        return {type(value).__name__: [canonical(item) for item in value]}
    raise TypeError(f'Unsupported comparison value: {type(value).__name__}')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf8')).hexdigest()


def inventory(root):
    package = root/'_internal/packages/parser_core'
    paths = [*package.rglob('*.py'), root/'_internal/data/resource-manifest.json']
    return {str(path.relative_to(root)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths) if '__pycache__' not in path.parts}


def dependency_inventory(directory):
    return ({str(path.relative_to(directory)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(directory.rglob('*')) if path.is_file() and '__pycache__' not in path.parts}
            if directory else {})


def outcome(call):
    try:
        return {'value': canonical(call())}
    except Exception as error:
        return {'error': type(error).__name__, 'message': str(error)}


def worker(root, fixtures):
    sys.path.insert(0, str(root/'_internal/packages/parser_core'))
    os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(root/'_internal')
    from parser_core import battle_log_parser as parser
    from parser_core.incremental import IncrementalBattleParser

    results = {}
    for path in sorted(fixtures.glob('*.log')):
        text = path.read_text(encoding='utf8')
        lines = text.splitlines(keepends=True)
        scenarios = results[path.name] = {}
        for debug in (False, True):
            scenarios[f'report/debug={debug}'] = outcome(lambda: parser.parse_raw_battle_log_text(
                text, file_name=path.name, reference_date=date(2026, 10, 27), include_rdps_debug=debug))
        for width in (1, 7, 64):
            stream = parser._raw_battle_ingestion(text, reference_date=date(2026, 10, 27))
            snapshots = []
            try:
                next(stream)
                for start in range(0, len(lines), width):
                    snapshot = stream.send(enumerate(lines[start:start+width], start+1))
                    # This cache is indexed by process-local id(root). Compare
                    # its complete values, excluding only allocation addresses.
                    values = snapshot.get('buff_root_action_indices', {})
                    snapshot = dict(snapshot, buff_root_action_indices=sorted(
                        (canonical(row) for row in values.values()), key=digest))
                    snapshots.append(canonical(snapshot))
            finally:
                stream.close()
            scenarios[f'ingestion/chunk={width}'] = snapshots
            for summary in (False, True):
                engine = IncrementalBattleParser(allow_empty=True)
                reports = []
                for end in range(width, len(lines)+width, width):
                    prefix = lines[:end]
                    reports.append(outcome(lambda: engine.snapshot(prefix, summary=summary)))
                    # Repeating a snapshot must retain its externally visible result.
                    reports.append(outcome(lambda: engine.snapshot(prefix, summary=summary)))
                scenarios[f'incremental/chunk={width}/summary={summary}'] = reports
    return results


def first_difference(left, right, path='$'):
    if type(left) is not type(right):
        return path+' (type)'
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path+' (keys)'
        return next((difference for key in left
                     if (difference := first_difference(left[key], right[key], path+'/'+str(key)))), None)
    if isinstance(left, list):
        if len(left) != len(right):
            return path+' (length)'
        return next((difference for index, (a, b) in enumerate(zip(left, right))
                     if (difference := first_difference(a, b, path+'/'+str(index)))), None)
    return None if left == right else path+' (value)'


def main():
    arguments = argparse.ArgumentParser(description=__doc__)
    arguments.add_argument('--reference', type=Path, required=True)
    arguments.add_argument('--candidate', type=Path, default=Path(__file__).resolve().parents[2])
    arguments.add_argument('--output', type=Path, required=True)
    arguments.add_argument('--dependencies', type=Path, help='Fixed directory containing the reference dependencies')
    arguments.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = arguments.parse_args()
    reference, candidate = args.reference.resolve(), args.candidate.resolve()
    if args.dependencies:
        args.dependencies = args.dependencies.resolve()
        sys.path.insert(0, str(args.dependencies))
    fixtures = reference/'_internal/packages/parser_core/tests/fixtures'
    if args.worker:
        args.output.write_text(json.dumps(worker(candidate, fixtures), ensure_ascii=False), encoding='utf8')
        return 0
    if reference == candidate or not fixtures.is_dir():
        arguments.error('A separate, fixed reference with public synthetic fixtures is required')
    output = args.output.resolve()
    if output.is_relative_to(reference):
        arguments.error('Comparison output must be outside the fixed reference')
    output.parent.mkdir(parents=True, exist_ok=True)
    before = {'reference': inventory(reference), 'candidate': inventory(candidate)}
    dependency_hashes = dependency_inventory(args.dependencies)
    sources, results = {}, {}
    for label, root in [('reference', reference), ('candidate', candidate)]:
        target = output.with_name(output.stem+'-'+label+'.json')
        command = [sys.executable, '-B', str(Path(__file__).resolve()), '--worker',
                   '--reference', str(reference), '--candidate', str(root), '--output', str(target)]
        if args.dependencies:
            command += ['--dependencies', str(args.dependencies)]
        subprocess.run(command,
                       check=True, cwd=root, timeout=300)
        sources[label] = target.name
        results[label] = json.loads(target.read_text(encoding='utf8'))
    after = {'reference': inventory(reference), 'candidate': inventory(candidate)}
    if before != after or dependency_hashes != dependency_inventory(args.dependencies):
        raise RuntimeError('Source, dependency or resource manifest changed during comparison')
    differences = []
    for name, expected in results['reference'].items():
        actual = results['candidate'].get(name, {})
        for scenario, value in expected.items():
            if difference := first_difference(value, actual.get(scenario)):
                differences.append({'fixture': name, 'scenario': scenario, 'path': difference})
    report = {'passed': not differences, 'fixtures': len(results['reference']),
              'scenarios': sum(len(rows) for rows in results['reference'].values()),
              'differences': differences, 'sources': before, 'outputs': sources,
              'dependencies': dependency_hashes,
              'report_errors': {label: sum('error' in value for scenarios in rows.values()
                                          for name, value in scenarios.items() if name.startswith('report/'))
                                for label, rows in results.items()},
              'float_comparison': 'exact binary value',
              'cache_normalization': 'buff_root_action_indices: compare all values, omit process-local id keys'}
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(f"Parser reference: {report['fixtures']} fixtures, {report['scenarios']} scenarios, {len(differences)} differences")
    return int(bool(differences))


if __name__ == '__main__':
    raise SystemExit(main())
