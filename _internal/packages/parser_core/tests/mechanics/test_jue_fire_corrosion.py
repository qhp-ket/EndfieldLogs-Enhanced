"""Synthetic fire-route corrosion uses the existing strict dynamic contract."""
from parser_test_support.paths import FIXTURES
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import pytest
from parser_core import battle_log_parser as parser
from parser_core.live import LiveOverlayBattleParser
from parser_core.unified import parse_overlay_battle_snapshot_text, parse_hit_viewer_log_text

FIXTURE = FIXTURES/'synthetic_fire_corrosion.log'
BUFF = 'buff_common_natural_fire_triggered'
UID = '8001'
PROVIDER = 'chr_0032_lizhiyan'


def fixture():
    manifest=json.loads(FIXTURE.with_suffix('.json').read_text(encoding='utf8'))
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == manifest['fixtureSha256']
    return FIXTURE.read_text(encoding='utf8')


def parse(text):
    return parser.parse_raw_battle_log_text(text,include_rdps_debug=True)


def test_synthetic_fire_route_credits_observed_corrosion_in_all_four_entries():
    text=fixture()
    result=parse(text)
    assert result['battle']['total_damage'] == 420
    hit=result['debug_hits'][0]
    zone=next(z for z in hit['zones'] if z['zone']=='res')
    external=next(c for c in zone['contributors'] if c['scope']=='external')
    assert external['rdps_whitelist_keys'] == [BUFF]
    assert external['source_character_key'] == PROVIDER
    # Counterfactual removes only the observed corrosion resistance points.
    points=Decimal(str(external['rate']))
    expected_credit=hit['hit_value']*(1-100/(100+float(points)))
    values={c['character_key']:c['value'] for c in hit['rdps_contributions']}
    assert values[PROVIDER] == pytest.approx(expected_credit, abs=.02)
    assert sum(values.values()) == pytest.approx(hit['hit_value'])
    assert result['battle']['rdps_damage_basis']['rdps_conservation_ok']
    viewer=parse_hit_viewer_log_text(text)
    assert viewer['hits'][0]['rdps_contributions'] == hit['rdps_contributions']
    overlay=parse_overlay_battle_snapshot_text(text)
    # The subset intentionally omits intervening hits. Keep its observation
    # window open so live idle segmentation does not turn it into two fights.
    live=LiveOverlayBattleParser(align_to_data_watermark=True, idle_split_ms=300000)
    live.feed_lines(text.splitlines())
    current=live.snapshot()
    for snapshot in (overlay,current):
        assert snapshot['battle']['total_damage'] == 420
        expected={r['character_key']:r['total_rd'] for r in result['participants']}
        actual={r['character_key']:r['total_rd'] for r in snapshot['participants']}
        assert actual == pytest.approx(expected)
    for r in result['buff_events']:
        if r.get('event_key') == BUFF and r['uid'] == UID:
            assert all(s['status']=='attribute_parameters_observed' for s in r['attribute_refresh_snapshots'])


@pytest.mark.parametrize('mutation',['no_refresh','foreign_session','wrong_owner','wrong_uid','missing_creation','missing_origin','wrong_creator_action','missing_additional'])
def test_bad_evidence_never_enables_external_corrosion(mutation):
    lines=[]
    for line in fixture().splitlines():
        if UID in line:
            if mutation=='no_refresh' and ' BUFF_ATTR_REFRESH ' in line: continue
            if mutation=='missing_creation' and ' BUFF_CREATE_OBSERVED ' in line: continue
            if mutation=='missing_origin' and ' BUFF_ORIGIN ' in line: continue
            if mutation=='missing_additional':
                if ' BB[' in line: line=line.replace(' additional_def_decrease=0','')
                if ' BUFF_CREATE_OBSERVED ' in line:
                    prefix,payload=line.split(' BUFF_CREATE_OBSERVED ',1)
                    obj=json.loads(payload)
                    obj['assignedItems']=[i for i in obj['assignedItems'] if i['target_key']!='additional_def_decrease']
                    line=prefix+' BUFF_CREATE_OBSERVED '+json.dumps(obj)
            if ' BUFF_ATTR_REFRESH ' in line and mutation in {'foreign_session','wrong_owner','wrong_uid'}:
                prefix,payload=line.split(' BUFF_ATTR_REFRESH ',1)
                obj=json.loads(payload)
                obj[{'foreign_session':'sessionId','wrong_owner':'ownerId','wrong_uid':'buffUid'}[mutation]]='foreign'
                line=prefix+' BUFF_ATTR_REFRESH '+json.dumps(obj)
            if mutation=='wrong_creator_action' and ' BUFF_ORIGIN ' in line:
                prefix,payload=line.split(' BUFF_ORIGIN ',1)
                obj=json.loads(payload); obj['actionId']=9999
                line=prefix+' BUFF_ORIGIN '+json.dumps(obj)
        lines.append(line)
    result=parse('\n'.join(lines))
    assert result['battle']['total_damage']==420
    assert all(not any(c['character_key']==PROVIDER for c in h['rdps_contributions']) for h in result['debug_hits'][:1])


def test_synthetic_high_then_low_creation_is_preserved_without_inventing_refresh():
    result=parse(fixture())
    records=[r for r in result['buff_events'] if r.get('event_key')==BUFF]
    low=next(r for r in records if r['uid']=='8003')
    assert low['bb_values']['count']==2
    assert low['bb_values']['def_decrease'] < low['bb_values']['max_def_decrease']
    # This invented instance deliberately has no refresh. Do not manufacture
    # one from a lower count, a duration, tick integration, or a previous UID.
    assert not low.get('attribute_refresh_snapshots')
    assert parser._extract_dynamic_effect_specs(deepcopy(low)) == []
    high=next(r for r in records if r['uid']=='8002')
    latest=high['attribute_refresh_snapshots'][-1]
    assert latest['bb_values']['def_decrease']==pytest.approx(-40.0)
    assert latest['status']=='attribute_parameters_observed'
    specs=parser._extract_dynamic_effect_specs(deepcopy(high))
    assert specs and all('tick_rate' not in spec for spec in specs)


def test_observed_strength_is_neither_integrated_nor_clamped_to_configuration():
    high=next(r for r in parse(fixture())['buff_events'] if r.get('uid')=='8002')
    specs=parser._extract_dynamic_effect_specs(deepcopy(high))
    snapshot=high['attribute_refresh_snapshots'][-1]
    for spec in specs:
        # Synthetic variation of configuration only: the observed runtime
        # value remains the stronger value, as defined in the synthetic low-count blackboard.
        spec['parameter_snapshots'][-1]['bb_values'].update(max_def_decrease=-30.9135,def_decrease_tick=-999)
    window={'dynamic_effects':specs}
    kwargs=dict(packet_seq_id=snapshot['operation_seq']+1,packet_session_id=snapshot['identity']['sessionId'])
    for elapsed in (1,1000,100000):
        effects=parser._window_effects_at_ts(deepcopy(window),snapshot['ts_ms']+elapsed,**kwargs)
        assert len(effects)==5
        assert all(e['rate']==pytest.approx(40.0) for e in effects)
