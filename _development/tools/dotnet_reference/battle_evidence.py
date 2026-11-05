"""固定 Qt 技能详情的 canonical 分配汇总。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import random
import sys
from report_projection import canonical


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    root = args.reference.resolve()
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    relatives = ['_internal/src/endfield_pcap/' + name for name in (
        'analysis/battle/detail.py', 'analysis/battle/enemy.py', 'data/skill_names.py', 'data/assets/skill_names_zh.json')]
    dependencies = {}
    for relative in relatives:
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        if digest != manifest['files'][relative]['sha256']:
            raise ValueError('固定详情参考已变化：' + relative)
        dependencies[relative] = digest
    sys.path.insert(0, str(root / '_internal/src'))
    from endfield_pcap.analysis.battle.detail import TimelineBlock
    cases = []

    def add(name, rows):
        block = TimelineBlock('a', 'skill', 0, 1000, '技能', '战技', copy.deepcopy(rows))
        cases.append(dict(name=name, config_json=json.dumps(rows, ensure_ascii=True), expected=canonical(block.contribution_summary())))

    add('empty', [])
    add('partial-basis', [dict(event_type='damage', value=100, rdps_basis_value=100, rdps_contributions=[dict(character_key='a', value=10)]), dict(event_type='damage', value=50)])
    add('invalid-contributions', [dict(event_type='damage', value=50, rdps_contributions=[dict(character_key='a', value='unknown'), dict(character_key='', value=100), dict(character_key='a', value='25.5')])])
    add('cast-only', [dict(event_type='cast', value=500, rdps_basis_value=123, rdps_contributions=[dict(character_key='x', value=500)])])
    rng = random.Random(20261030)
    for index in range(40):
        events = []
        for number in range(12):
            events.append(dict(event_type=rng.choice(['damage', 'damage', 'cast']), value=rng.choice([0, 1.25, 10, 100, '15.5']), rdps_basis_value=rng.choice([0, None, 10, '20.25', 'unknown']),
                rdps_contributions=[dict(character_key=rng.choice(['a', 'b', '', 'unknown']), character_name=rng.choice(['已观测名称', '']), value=rng.choice([0, -5, .25, 12.5, '8.125', 'unknown', None])) for _ in range(rng.randrange(4))]))
        add('allocations-' + str(index), events)
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/battle-evidence.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases), dependencies=dependencies), indent=2), encoding='utf8')
    print('Battle evidence:', len(cases))


if __name__ == '__main__':
    main()
