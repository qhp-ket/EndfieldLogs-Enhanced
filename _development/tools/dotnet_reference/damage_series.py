"""固定应用参考的伤害曲线投影；仅使用合成报告。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import random


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    relative = '_internal/src/endfield_pcap/analysis/battle/damage.py'
    source = args.reference.resolve() / relative
    manifest = json.loads(args.manifest.read_text(encoding='utf8'))
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != manifest['files'][relative]['sha256']:
        raise ValueError('固定的伤害曲线参考已变化')
    spec = importlib.util.spec_from_file_location('fixed_damage_series', source)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    cases = []

    def add(name, snapshot):
        for metric in ['rdmg', 'dmg', 'rdps', 'dps']:
            for character in ['', 'a']:
                cases.append(dict(name=f'{name}-{metric}-{character or "all"}',
                    config_json=json.dumps(dict(snapshot=snapshot, metric=metric, character=character), ensure_ascii=True),
                    expected=reference.damage_series(snapshot, metric, character)))

    for duration in [0, -1, 1, 1000, 1001, 2500, '2500', None]:
        add(f'boundary-{duration}', dict(battle=dict(duration_ms=duration), participants=[dict(character_key='a'), dict(character_key='b')],
            timeline_events=[dict(event_type='damage', ts_ms_from_start=stamp, source_character_key='a', value=10,
                rdps_contributions=[dict(character_key='a', value=6), dict(character_key='b', value=4)])
                for stamp in [-1, 0, 999, 1000, 1001, 2500, 2501]]))
    rng = random.Random(20261029)
    for index in range(8):
        rows = []
        for _ in range(25):
            row = dict(event_type=rng.choice(['damage', 'damage', 'buff']), ts_ms_from_start=rng.choice([None, -1, 0, 1, 999, 1000, 1500, 2500, 2501]),
                source_character_key=rng.choice(['a', 'b']), value=rng.choice([0, 10, 10.5, '25', None]))
            if rng.randrange(3):
                row['rdps_contributions'] = [dict(character_key=key, value=rng.choice([None, 0, 12.5, '5.5'])) for key in ['a', 'b']]
            rows.append(row)
        add(f'sparse-{index}', dict(battle=dict(duration_ms=2500), participants=[dict(character_key='a'), dict(character_key='b')], timeline_events=rows))
    output = Path(__file__).resolve().parents[3] / '_internal/dotnet/Specs/Fixtures/damage-series.json'
    output.write_text(json.dumps(cases, ensure_ascii=True, separators=(',', ':')), encoding='utf8')
    output.with_suffix('.reference.json').write_text(json.dumps(dict(source_head=manifest['head'], cases=len(cases), dependencies={relative: digest}), indent=2), encoding='utf8')
    print('伤害曲线参考：', len(cases))


if __name__ == '__main__':
    main()
