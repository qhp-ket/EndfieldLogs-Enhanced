"""Missing character definitions must not erase packet damage or break views."""
from app_test_support.paths import ROOT
import json
import os
import shutil
import subprocess
import sys
import pytest
from app_test_support.runtime.tools import ROOT


@pytest.mark.parametrize('unknown', [False, True], ids=['missing-existing-records', 'future-character'])
def test_character_data_absence_preserves_damage_live_summary_and_analysis(tmp_path, unknown):
    internal = tmp_path / '_internal'
    for folder in ('data', 'jsondata'):
        shutil.copytree(ROOT / '_internal' / folder, internal / folder,
                        ignore=shutil.ignore_patterns('runtime-data.zip'))
    key = 'chr_0004_pelica'
    for parent in ('data/akedata/character/items', 'data/local_tables/character/items'):
        (internal / parent / (key+'.json')).unlink()
    for relative in ('data/akedata/character/manifest.json', 'data/local_tables/character/manifest.json'):
        path = internal / relative
        value = json.loads(path.read_text(encoding='utf8'))
        rows = value if isinstance(value, list) else value['entries']
        rows[:] = [row for row in rows if row.get('charId', row.get('id')) != key]
        path.write_text(json.dumps(value), encoding='utf8')
    path = internal / 'jsondata/CharacterNameIndex.json'
    value = json.loads(path.read_text(encoding='utf8'))
    value.pop(key, None)
    path.write_text(json.dumps(value), encoding='utf8')
    # A separate interpreter isolates the process-lifetime static data caches.
    script = r'''
import json, os, sys
from pathlib import Path
root, internal, unknown = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == 'True'
sys.path.insert(0, str(root/'_internal/src'))
from endfield_pcap.runtime.environment import configure_paths
handles = configure_paths(root)
os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(internal)
from parser_core.unified import parse_overlay_battle_snapshot_text
from parser_core.live import LiveOverlayBattleParser
from endfield_pcap.data.names import load_name_index
from endfield_pcap.analysis.battle.web_data import WebBattleModel
import endfield_pcap.data.skill_frames as skill_frame_reference
skill_frame_reference.bundle_root = lambda: internal
key = 'chr_9999_future' if unknown else 'chr_0004_pelica'
text = (root/'_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log').read_text(encoding='utf8')
text = text.replace('chr_0004_pelica', key)
assert key not in load_name_index(internal/'jsondata/CharacterNameIndex.json')
report = parse_overlay_battle_snapshot_text(text)
assert report['battle']['total_damage'] == 760
assert any(p['character_key'] == key and p['total_damage'] == 760 for p in report['participants'])
assert report['snapshot_quality']['status'] != 'verified'
assert report['rdps_preflight']['ok'] is False
assert report['battle']['rdps_damage_basis']['rdps_conservation_ok'] is True
model = WebBattleModel(report, 'missing-character')
assert json.loads(model.json())['blocks']
live = LiveOverlayBattleParser(summary=True, align_to_data_watermark=True)
live.feed_lines(text.splitlines())
summary = live.snapshot()
assert summary['battle']['total_damage'] == 760
assert any(p['character_key'] == key and p['total_damage'] == 760 for p in summary['participants'])
print('Damage, provisional quality, live summary and analysis remain available')
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT), str(internal), str(unknown)],
                            cwd=ROOT, env=dict(os.environ), capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
