from copy import deepcopy
import pytest
from parser_core.live_frozen import FrozenHitEvidence, FrozenBuffEvidence, FrozenMutation
from parser_core.incremental import IncrementalBattleParser
from test_incremental_live import hit


def test_frozen_evidence_is_detached_and_reuses_only_exact_unchanged_contents():
    cache=FrozenHitEvidence()
    raw={'hits':[{'line_no':1,'packet_attr_details':{'attacker':[{'value':2}]}}]}
    slim,fields=cache.prepare(raw)
    frozen=fields[0]['packet_attr_details']
    assert 'packet_attr_details' not in slim['hits'][0]
    with pytest.raises(FrozenMutation): frozen['attacker'][0]['value']=3
    with pytest.raises(FrozenMutation): frozen['attacker'].append(3)
    assert deepcopy(frozen) is frozen
    assert cache.prepare(raw)[1][0]['packet_attr_details'] is frozen
    raw['hits'][0]['packet_attr_details']['attacker'][0]['value']=4
    fresh=cache.prepare(raw)[1][0]['packet_attr_details']
    assert fresh is not frozen and frozen['attacker'][0]['value']==2


def test_unexpected_evidence_write_falls_back_to_independent_copy(monkeypatch):
    from parser_core import battle_log_parser as core
    original=core._build_raw_battle_report
    def write_evidence(state,*args,**kwargs):
        state['hits'][0]['packet_modifier_uids']['attacker'].append('test')
        return original(state,*args,**kwargs)
    monkeypatch.setattr(core,'_build_raw_battle_report',write_evidence)
    engine=IncrementalBattleParser()
    result=engine.snapshot([hit(1)],summary=True)
    assert result['battle']['total_damage']==120
    assert engine.freeze_disabled and engine.diagnostics['trace_replays']==1
    assert engine.state['hits'][0]['packet_modifier_uids']['attacker']==[]


def test_buff_provenance_cache_replaces_late_creation_evidence():
    cache = FrozenBuffEvidence()
    state = {'buff_starts': [{'line_no': 1, 'uid': '7',
        'creation_observations': [{'operationSeq': 1}], 'origin_observations': []}]}
    slim, evidence = cache.prepare(state)
    old = evidence[0]['creation_observations']
    assert 'creation_observations' not in slim['buff_starts'][0]
    assert cache.prepare(state)[1][0]['creation_observations'] is old
    state['buff_starts'][0]['creation_observations'].append({'operationSeq': 2})
    new = cache.prepare(state)[1][0]['creation_observations']
    assert len(old) == 1 and len(new) == 2 and new is not old
    with pytest.raises(FrozenMutation): new[0]['operationSeq'] = 3
