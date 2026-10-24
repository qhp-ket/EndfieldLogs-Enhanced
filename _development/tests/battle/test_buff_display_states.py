"""BUFF state views merge observations without changing canonical combat data."""
from app_test_support.scenarios.buffs import buff
from copy import deepcopy
from endfield_pcap.analysis.battle.buffs.states import buff_tracks
from endfield_pcap.analysis.battle.buffs.states import buff_state_text
from endfield_pcap.analysis.battle.detail import timeline_blocks

def test_refresh_extends_and_shortens_expiry_without_old_state_resurrection():
    rows = [buff(0, 10000), buff(2000, 12000, 'b'), buff(4000, 6000, 'c')]
    before = deepcopy(rows)
    tracks = list(buff_tracks(rows))
    assert len(tracks) == 1
    _, start, end, states, evidence = tracks[0]
    assert (start, end) == (0, 6000)
    assert [s['stacks'] for s in states] == [1, 1, 1]
    assert '剩余 1.00s' in buff_state_text(states, 5000)
    assert buff_state_text(states, 7000) == '未生效'
    assert rows == before

def test_distinct_stack_uids_count_once_and_aliases_never_add_layers():
    rows = [buff(0, 10000, 'a', 'Stack', stack_limit=3),
            buff(1000, 10000, 'a', 'Stack', stack_limit=3),
            buff(2000, 8000, 'b', 'Stack', stack_limit=3, buff_uid_aliases=['mirror']),
            buff(2000, 8000, 'mirror', 'Stack', stack_limit=3)]
    states = list(buff_tracks(rows))[0][3]
    assert [s['stacks'] for s in states] == [1, 2, 1]
    assert '峰值 2 层' in buff_state_text(states)

def test_gaps_preserved_same_row_and_distinct_source_target_instances_separate():
    rows = [buff(0, 1000), buff(2000, 3000, 'b')]
    tracks = list(buff_tracks(rows))
    assert len(tracks) == 2 and tracks[0][0] == tracks[1][0]
    rows += [{**buff(), 'target_actor_id': 'other'}, {**buff(), 'source_actor_id': 'other'}]
    assert len({t[0] for t in buff_tracks(rows)}) == 3

def test_unknown_stacking_is_explicit_and_observation_end_is_not_expiry():
    states = list(buff_tracks([buff(uid='a', policy=None, end_is_observation_boundary=True),
                               buff(uid='b', policy=None)]))[0][3]
    assert states[0]['stacks'] is None
    assert '层数未知' in buff_state_text(states, 1000)
    assert '持续时间未知' in buff_state_text(states, 1000)

def test_repeated_windows_become_one_block_but_keep_raw_updates():
    snapshot = {'participants': [{'character_key': 'target'}],
                'timeline_events': [buff(), buff(2000, 15000, 'b')]}
    before = deepcopy(snapshot)
    blocks = timeline_blocks(snapshot)
    assert len(blocks) == 1
    assert len(blocks[0].events) == 2
    assert blocks[0].end_ms == 15000
    assert snapshot == before

def test_recorded_enable_updates_override_alive_instance_counts():
    rows = [buff(policy='Stack', buff_enable_observations=[
        {'at_ms': 0, 'enabled': True}, {'at_ms': 2000, 'enabled': False},
        {'at_ms': 4000, 'enabled': True}])]
    tracks = list(buff_tracks(rows))
    assert [(t[1], t[2]) for t in tracks] == [(0, 2000), (4000, 10000)]
    assert tracks[0][0] == tracks[1][0]

def test_priority_instances_are_not_arbitrarily_replaced_by_newest():
    rows = [buff(0, 10000, policy='HighPriority', buff_enable_observations=[{'at_ms': 0, 'enabled': True}]),
            buff(2000, 5000, 'b', 'HighPriority', buff_enable_observations=[{'at_ms': 2000, 'enabled': False}])]
    tracks = list(buff_tracks(rows))
    assert len(tracks) == 1 and tracks[0][2] == 10000

def test_expiry_uses_recorded_lifetime_instead_of_snapshot_cut():
    row = buff(end=2000, buff_lifetime={'expiry_ms_from_start': 10000})
    states = list(buff_tracks([row]))[0][3]
    assert '剩余 9.00s' in buff_state_text(states, 1000)
    states = list(buff_tracks([{**row, 'buff_lifetime': {'expiry_ms_from_start': None}}]))[0][3]
    assert '持续时间未知' in buff_state_text(states, 1000)

def test_canonical_projection_preserves_uid_actor_stacking_and_recorded_lifetime():
    from app_test_support.ui.qt import snapshot_message
    snapshot = snapshot_message()['snapshot']
    rows = [e for e in snapshot['timeline_events'] if e.get('lane_type') == 'buff']
    assert rows
    assert all(e['buff_uid'] == '9007199254740993' for e in rows)
    assert all(e['source_actor_id'] == '2001' and e['target_actor_id'] == '1001' for e in rows)
    assert all(e['buff_enable_observations'] for e in rows)
    # First snapshot is cut by a refresh before its advertised 10-second life.
    assert rows[0]['buff_lifetime']['expiry_ms_from_start'] > rows[0]['actual_end_ms_from_start']
    assert snapshot['battle']['total_damage'] == 760
    assert sum(p['total_rd'] for p in snapshot['participants']) == 760
