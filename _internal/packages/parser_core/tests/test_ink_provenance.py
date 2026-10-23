"""Recorded-hit shares survive buff changes, release/reset, and explosion replay."""
from copy import deepcopy
import json
from math import log, log1p
from pathlib import Path

import pytest

from parser_core import battle_log_parser as core
from parser_core.ink_provenance import BUFF, EXPLOSION, OWNER, apply_ink_provenance

ATTACKER = 'chr_0004_pelica'
SUPPORT = 'chr_0035_liino'


def ink_shares(amount, rate, multiplier):
    owner = amount * log1p(rate) / (log1p(rate) + log(multiplier))
    return {OWNER: owner, SUPPORT: amount - owner}


class Trace:
    def __init__(self):
        self.lines = ['[10:00:00.000] CONTEXT']
        self.hits = []
        self.records = [dict(event_key=BUFF, uid='7001', source_character_key=OWNER, source_actor_id='4001',
            target_actor_id='3001', line_no=1, packet_creation_contexts=[dict(session_id='test', operation_seq=1)])]

    def line(self, body):
        self.lines.append('[10:00:00.000] ' + body)
        return len(self.lines)

    def source(self, seq, value, shares, *, tick=1000, session='test'):
        hit = dict(line_no=self.line('SOURCE'), seq=len(self.hits)+1, character_key=ATTACKER,
            packet_session_id=session, packet_seq_id=seq, client_tick_ms=tick, target_actor_id='3001',
            packet_final_value=value, rdps_contributions=shares)
        self.hits.append(hit)
        return hit

    def dynamic(self, seq, action, value, *, tick=1000, session='test'):
        identity = dict(schemaVersion=1, sessionId=session, operationSeq=seq, ownerType='1',
            ownerId='3001', environmentInstId='7001', templateType='Buff', actionId=action,
            clientTickMs=str(tick), triggerType=0, actionType=7,
            actionRuntimeCase='modify_dynamic_blackboard_action', operationPayloadCase='trigger_action_op_data')
        return self.line(f'BB_MODIFY_DYNAMIC seq={seq} tick={tick} inst=7001 ownerId=3001 skill={BUFF} '
            f'actionId={action} value={value!r} identity=' + json.dumps(identity, separators=(',', ':')))

    def add(self, seq, previous, increment, *, tick=1000):
        self.line(f'BB_SIMPLE_CALC seq={seq} tick={tick} inst=7001 ownerId=3001 skill={BUFF} '
            f'actionId=47 key=EntityBB_ink_damage valueA={previous} valueB={increment} final={previous+increment}')

    def release(self, seq=130, *, projectile='8001', legacy=False):
        if legacy:
            self.dynamic(seq-1, 13, 0)
            self.line(f'ACTOR_MAP id={projectile} template={OWNER} source=launch_projectile skill=None')
            self.line(f'SKILL_CAST_START seq={seq+1} startMs=1000 inst=8002 ownerId={projectile} skill={EXPLOSION}')
        else:
            self.line('INK_RELEASE ' + json.dumps(dict(schema_version=1, template_key=BUFF, action_id=14,
                session_id='test', operation_seq=seq, buff_uid='7001', owner_id='3001', source_actor_id='4001',
                projectile_id=projectile, client_tick_ms=1000)))
        self.dynamic(seq+2, 15, 0)

    def explosion(self, value, *, seq=140, effective=None, projectile='8001', session='test'):
        hit = dict(line_no=self.line('EXPLOSION'), seq=len(self.hits)+1, character_key=OWNER,
            target_actor_id='3001', source_actor_id='4001', packet_session_id=session, packet_seq_id=seq,
            event_owner_id=projectile, event_inst_id='8002', client_tick_ms=1000,
            skill_key=EXPLOSION, packet_final_value=value, hit_value=value if effective is None else effective,
            rdps_contributions={OWNER: value}, damage_calculation=dict(atkCalculation=dict(
                value=dict(blackboardKey='EntityBB_ink_damage', useBlackboardKey=True))))
        self.hits.append(hit)
        return hit

    def run(self, roots=None):
        return apply_ink_provenance('\n'.join(self.lines), self.hits, self.records,
            root_lookup=roots if roots is not None else core._load_current_buff_roots(), extract_fields=core._extract_fields)


@pytest.mark.parametrize('legacy', [False, True])
@pytest.mark.parametrize('effective', [72, 36])
def test_different_record_multipliers_and_original_external_shares(legacy, effective):
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)  # Optional 46 is absent; observed 47 contains the actual increment.
    trace.source(110, 300, {ATTACKER: 200, SUPPORT: 100})
    trace.dynamic(111, 45, 300)
    trace.add(112, 12, 60)  # A different recording rate must not reuse the first rate.
    trace.release(legacy=legacy)
    hit = trace.explosion(72, effective=effective)
    summary = trace.run()
    assert summary['paired_records'] == 2 and summary['resolved'] == 1
    first, second = ink_shares(12, .1, 1.2), ink_shares(60, .2, 1.5)
    assert hit['rdps_contributions'] == pytest.approx({key: (first[key]+second[key])*effective/72 for key in first})
    assert sum(hit['rdps_contributions'].values()) == pytest.approx(effective)
    assert trace.hits[0]['rdps_contributions'] == {ATTACKER: 100, SUPPORT: 20}
    allocation = core._allocate_rdps_for_hit(hit, [], include_debug=True)
    assert allocation['contributions_map'] == hit['rdps_contributions']
    assert allocation['zones'] == [] and allocation['product_external_multiplier'] is None


@pytest.mark.parametrize('fault', ['missing', 'ambiguous', 'wrong_tick', 'wrong_session', 'rounded_value'])
def test_unpaired_records_preserve_damage_but_do_not_invent_external_credit(fault):
    trace = Trace()
    if fault != 'missing':
        trace.source(100, 120.000004 if fault == 'rounded_value' else 120, {ATTACKER: 100, SUPPORT: 20},
            tick=999 if fault == 'wrong_tick' else 1000, session='other' if fault == 'wrong_session' else 'test')
    if fault == 'ambiguous':
        trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    trace.release()
    hit = trace.explosion(12)
    summary = trace.run()
    assert summary['unpaired_records'] == 1
    assert summary['partial'] == 1 and hit['rdps_contributions'] == {OWNER: 12}
    assert hit['rdps_unresolved_effect_conditions']


def test_reset_keeps_inflight_release_and_does_not_contaminate_next_release():
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    trace.release(130)
    trace.source(150, 200, {ATTACKER: 200})
    trace.dynamic(151, 45, 200)
    trace.add(152, 0, 20)
    trace.release(160, projectile='9001')
    first = trace.explosion(12, seq=170)
    second = trace.explosion(20, seq=180, projectile='9001')
    assert trace.run()['resolved'] == 2
    assert first['rdps_contributions'] == pytest.approx(ink_shares(12, .1, 1.2))
    assert second['rdps_contributions'] == {OWNER: 20}


@pytest.mark.parametrize('fault', ['missing_release', 'amount', 'session', 'projectile', 'target', 'source', 'typed_formula'])
def test_invalid_release_or_explosion_evidence_keeps_owner_baseline(fault):
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    if fault != 'missing_release': trace.release()
    hit = trace.explosion(13 if fault == 'amount' else 12,
        session='other' if fault == 'session' else 'test', projectile='wrong' if fault == 'projectile' else '8001')
    if fault == 'target': hit['target_actor_id'] = 'wrong'
    if fault == 'source': hit['source_actor_id'] = 'wrong'
    roots = {} if fault == 'typed_formula' else None
    assert trace.run(roots)['unresolved'] == 1
    assert hit['rdps_contributions'] == {OWNER: hit['hit_value']}


def test_duplicate_operations_are_idempotent_and_conflicts_reject_ledger():
    for conflict in [False, True]:
        trace = Trace()
        trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
        trace.dynamic(101, 45, 120)
        trace.add(102, 0, 12)
        trace.add(102, 0, 13 if conflict else 12)
        trace.release()
        hit = trace.explosion(12)
        summary = trace.run()
        if conflict:
            assert summary['unresolved'] == 1 and hit['rdps_contributions'] == {OWNER: 12}
        else:
            assert summary['resolved'] == 1 and hit['rdps_contributions'] == pytest.approx(ink_shares(12, .1, 1.2))


def test_missing_initial_records_are_retained_as_unknown_owner_component():
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 30, 12)
    trace.release()
    hit = trace.explosion(42)
    assert trace.run()['partial'] == 1
    expected = ink_shares(12, .1, 1.2)
    expected[OWNER] += 30
    assert hit['rdps_contributions'] == pytest.approx(expected)


def test_cannot_consume_same_projectile_twice():
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    trace.release()
    trace.explosion(12)
    repeated = trace.explosion(12, seq=150)
    summary = trace.run()
    assert summary['resolved'] == 1 and summary['unresolved'] == 1
    assert repeated['ink_provenance']['reason'] == 'ink_projectile_already_consumed'


def test_whole_explosion_contract_matches_raw_viewer_overlay_and_live():
    from parser_core.live import LiveOverlayBattleParser
    from parser_core.unified import (parse_hit_viewer_log_text, parse_overlay_battle_snapshot_text,
        rdps_totals_from_hit_debug, rdps_totals_from_raw_report)
    text = (Path(__file__).parent / 'fixtures/ink_recording_contract.log').read_text(encoding='utf8')
    raw = core.parse_raw_battle_log_text(text, include_rdps_debug=True)
    viewer = parse_hit_viewer_log_text(text)
    overlay = parse_overlay_battle_snapshot_text(text)
    live = LiveOverlayBattleParser(align_to_data_watermark=True)
    live.feed_lines(text.splitlines(keepends=True))
    ink = ink_shares(12, .1, 1.2)
    expected = {ATTACKER: 100, OWNER: ink[OWNER], SUPPORT: 20+ink[SUPPORT]}
    for report in (raw, overlay, live.snapshot()):
        assert report['battle']['total_damage'] == 132
        assert rdps_totals_from_raw_report(report) == pytest.approx(expected, abs=1e-4)
        assert report['rdps_damage_basis']['ink_provenance']['resolved'] == 1
        assert report['rdps_damage_basis']['rdps_conservation_ok']
        assert report['snapshot_quality']
    assert rdps_totals_from_hit_debug(viewer) == pytest.approx(expected, abs=1e-4)


def test_multiple_external_sources_and_si_support_merge_log_weights():
    trace = Trace()
    # Original independent zones 1.2 and 1.5, external pool 80: log weighting.
    external = 80
    support_credit = external * log(1.2) / log(1.8)
    trace.source(100, 180, {ATTACKER: 100, SUPPORT: support_credit, OWNER: external-support_credit})
    trace.dynamic(101, 45, 180)
    trace.add(102, 0, 18)
    trace.release()
    hit = trace.explosion(18)
    assert trace.run()['resolved'] == 1
    total = log(1.1)+log(1.2)+log(1.5)
    assert hit['rdps_contributions'] == pytest.approx({OWNER: 18*(log(1.1)+log(1.5))/total,
        SUPPORT: 18*log(1.2)/total})
    assert ATTACKER not in hit['rdps_contributions']


def test_unverified_nested_ink_and_kill_bonus_stay_partial_and_conserved():
    trace = Trace()
    source = trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    source['_ink_allocation'] = dict(source['rdps_contributions'])
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    trace.line(f'BB_SIMPLE_CALC seq=110 tick=1000 inst=7001 ownerId=3001 skill={BUFF} '
        'actionId=66 key=EntityBB_ink_damage valueA=12 valueB=3 final=15')
    trace.release()
    hit = trace.explosion(15)
    assert trace.run()['partial'] == 1
    assert hit['rdps_contributions'] == {OWNER: 15}
    assert set(hit['ink_provenance']['reasons']) == {
        'source_hit_attribution_unavailable', 'kill_bonus_provenance_unresolved'}
