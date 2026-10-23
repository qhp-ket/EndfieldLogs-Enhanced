"""Recorded ink damage: preserve source-hit attribution through an explicit ledger.

The ledger redistributes an observed explosion; it never adds damage, integrates
timers, or reapplies the explosion-time buff windows. Unknown ledger components
remain with the ink skill owner and keep strict quality unresolved.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from math import isclose, isfinite, log, log1p
import json

BUFF = 'buff_chr_0036_jsspsi_xianjing_inkhurteffect'
EXPLOSION = 'chr_0036_jsspsi_normal_skill_inkmark_projhit'
OWNER = 'chr_0036_jsspsi'
POLICY = 'whole_ink_damage_log_zones_v1'


def _record_weights(source, increment):
    """Recover original external log weights, then add the ink recording zone.

    The normal allocator's external pool is already distributed in proportion
    to each source's log weight (including within-zone coefficient sharing).
    Inverting that distribution retains the exact source-time convention.
    Unlike a normal hit, the WHOLE recorded component is shared over these
    weights; there is no reserved attacker/skill-owner baseline.
    """
    shares = source.get('rdps_contributions') or {}
    basis = sum(shares.values())
    baseline = shares.get(source['character_key'], 0)
    raw = abs(source.get('packet_final_value') or 0)
    if (source.get('_ink_allocation') is not None or raw <= 0 or increment <= 0
            or baseline <= 0 or basis < baseline or not isfinite(basis)):
        return None
    weights = defaultdict(float)
    weights[OWNER] = log1p(increment / raw)
    pool = basis - baseline
    if pool > 0:
        external_log = log(basis) - log(baseline)
        for key, credit in shares.items():
            if key != source['character_key'] and credit > 0:
                weights[key] += external_log * credit / pool
    return weights if all(isfinite(value) for value in weights.values()) else None


def _number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _integer(value):
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return None


def _close(a, b):
    # Legacy BB_SIMPLE_CALC lines retain six significant digits. This budget
    # covers that text precision and float32 server arithmetic, not source-hit
    # pairing, which separately requires the unrounded double at 1e-8.
    return a is not None and b is not None and isclose(a, b, rel_tol=1e-5, abs_tol=2e-5)


def _actions(root):
    result = defaultdict(list)
    def visit(node, enabled=True):
        if isinstance(node, dict):
            enabled = enabled and ('serverActionIndex' not in node or node.get('isEnable') is True)
            if enabled and type(node.get('serverActionIndex')) is int:
                result[node['serverActionIndex']].append(node)
            for value in node.values():
                visit(value, enabled)
        elif isinstance(node, list):
            for value in node:
                visit(value, enabled)
    visit(root)
    return result


def _profile(root):
    actions = _actions(root)
    def exact(index, kind, **values):
        rows = actions.get(index, [])
        return len(rows) == 1 and rows[0].get('$type') == 'Beyond.Gameplay.Core.' + kind + '.Data' and all(
            rows[0].get(key) == value for key, value in values.items())
    valid = (exact(45, 'SaveDamageContext', saveTo='ink_damage', valueType='RealValue')
        and exact(46, 'SimpleCalcBBAction', key='ink_damage2', operation='Multiply')
        and exact(47, 'SimpleCalcBBAction', key='EntityBB_ink_damage', operation='Add')
        and exact(14, 'LaunchProjectile')
        and exact(15, 'ModifyDynamicBlackboard', key='EntityBB_ink_damage', operation='Assign'))
    def operand(index, key, name):
        value = actions[index][0].get(key) or {}
        return value.get('useBlackboardKey') is True and value.get('blackboardKey') == name
    return valid and (operand(46, 'value1', 'ink_damage') and operand(46, 'value2', 'ink_damage_rate')
        and operand(47, 'value1', 'EntityBB_ink_damage') and operand(47, 'value2', 'ink_damage2')
        and _number((actions[15][0].get('value') or {}).get('value')) == 0)


@dataclass
class Ledger:
    record: dict
    session: str
    total: float = 0.0
    shares: dict = field(default_factory=lambda: defaultdict(float))
    pending: tuple | None = None
    last_seq: int = -1
    seen: dict = field(default_factory=dict)
    used_hits: set = field(default_factory=set)
    reasons: set = field(default_factory=set)
    source_hits: list = field(default_factory=list)

    def reset(self):
        self.total = 0.0
        self.shares = defaultdict(float)
        self.pending = None
        self.reasons = set()
        self.source_hits = []

    def freeze(self, projectile, sequence, mode):
        return dict(projectile_id=projectile, sequence=sequence, session=self.session,
            target_actor_id=str(self.record['target_actor_id']), source_actor_id=str(self.record['source_actor_id']),
            buff_uid=str(self.record['uid']), total=self.total, shares=dict(self.shares),
            reasons=set(self.reasons), source_hits=list(self.source_hits), binding=mode)


def apply_ink_provenance(text, hits, records, *, root_lookup, extract_fields):
    """Offline adapter for the same persistent state machine used by live."""
    if not any(hit.get('skill_key') == EXPLOSION for hit in hits):
        return {}
    stream = _ink_provenance_ingestion(root_lookup=root_lookup, extract_fields=extract_fields)
    next(stream)
    result = stream.send((enumerate(text.splitlines(), 1), hits, records))
    stream.close()
    return result


def _ink_provenance_ingestion(*, root_lookup, extract_fields):
    """Deferred per-instance ledgers survive ordinary live snapshot revisions."""
    summary = dict(policy=POLICY, explosions=0,
        resolved=0, partial=0, unresolved=0, paired_records=0, unpaired_records=0)
    profile_ok = _profile(root_lookup.get(BUFF))
    by_uid = defaultdict(list)
    registered = {}
    observed_sources = defaultdict(list)
    releases = {}
    release_preparation = None

    def bind(fields, line_no):
        candidates = [state for state in by_uid.get(fields.get('inst'), [])
            if str(state.record['target_actor_id']) == fields.get('ownerId')
            and state.record['line_no'] < line_no
            and (not state.record.get('end_line_no') or line_no < state.record['end_line_no'])]
        return candidates[0] if len(candidates) == 1 else None

    def fail(hit, reason):
        hit['_ink_allocation'] = {hit['character_key']: float(hit['hit_value'])}
        hit['rdps_contributions'] = dict(hit['_ink_allocation'])
        hit['ink_provenance'] = dict(status='unresolved', reason=reason)
        hit['rdps_unresolved_effect_conditions'] = True
        summary['unresolved'] += 1

    while True:
        numbered_lines, hits, records = yield summary
        for record in records:
            if record.get('event_key') != BUFF:
                continue
            sessions = {row.get('session_id') for row in record.get('packet_creation_contexts') or []}
            if (len(sessions) == 1 and None not in sessions and record.get('source_character_key') == OWNER
                    and record.get('source_actor_id') and record.get('target_actor_id')
                    and not record.get('rdps_live_identity_conflict')):
                key = (str(record.get('uid')), record.get('line_no'))
                existing = registered.get(key)
                if existing is None:
                    existing = Ledger(record, next(iter(sessions)))
                    registered[key] = existing
                    by_uid[key[0]].append(existing)
                else:
                    existing.record = record
        hits_by_line = {hit['line_no']: hit for hit in hits}
        for line_no, line in numbered_lines:
            hit = hits_by_line.get(line_no)
            if hit is not None:
                if hit.get('skill_key') == EXPLOSION:
                    summary['explosions'] += 1
                    release = releases.get(str(hit.get('event_owner_id')))
                    calculation = (hit.get('damage_calculation') or {}).get('atkCalculation') or {}
                    operand = calculation.get('value') or {}
                    if not profile_ok or operand.get('blackboardKey') != 'EntityBB_ink_damage' or operand.get('useBlackboardKey') is not True:
                        fail(hit, 'typed_ink_formula_unverified')
                    elif not release:
                        fail(hit, 'missing_ink_projectile_ledger')
                    elif (release['session'] != hit.get('packet_session_id')
                            or release['target_actor_id'] != str(hit.get('target_actor_id'))
                            or release['source_actor_id'] != str(hit.get('source_actor_id'))
                            or (release.get('cast_instance_id') is not None
                                and release['cast_instance_id'] != str(hit.get('event_inst_id')))
                            or hit.get('packet_seq_id') is None or hit['packet_seq_id'] <= release['sequence']):
                        fail(hit, 'ink_projectile_context_mismatch')
                    elif release.get('consumed'):
                        fail(hit, 'ink_projectile_already_consumed')
                    elif release['reasons'] & {'duplicate_projectile_release', 'conflicting_ink_operation',
                            'out_of_order_ink_operation', 'invalid_ink_accumulator', 'ink_operation_context_mismatch',
                            'invalid_ink_operation_identity', 'ink_operation_session_mismatch', 'missing_ink_operation_identity'}:
                        fail(hit, 'invalid_ink_ledger')
                    elif release['total'] <= 0 or not _close(abs(hit.get('packet_final_value') or 0), release['total']):
                        fail(hit, 'ink_explosion_amount_mismatch')
                    else:
                        release['consumed'] = True
                        total = sum(release['shares'].values())
                        if not _close(total, release['total']):
                            fail(hit, 'ink_ledger_not_conserved')
                        else:
                            amount = float(hit['hit_value'])
                            shares = {key: value * amount / total for key, value in release['shares'].items() if value > 0}
                            hit['rdps_contributions'] = shares
                            hit['_ink_allocation'] = shares
                            reasons = sorted(release['reasons'])
                            status = 'partial' if reasons else 'resolved'
                            hit['ink_provenance'] = dict(status=status, policy=summary['policy'],
                                buff_uid=release['buff_uid'], projectile_id=release['projectile_id'], binding=release['binding'],
                                recorded_total=release['total'], source_hits=release['source_hits'], reasons=reasons)
                            if reasons:
                                hit['rdps_unresolved_effect_conditions'] = True
                            summary[status] += 1
                key = (hit.get('packet_session_id'), str(hit.get('target_actor_id')), hit.get('client_tick_ms'), hit.get('packet_seq_id'))
                observed_sources[key].append(hit)
                continue

            if (' INK_RELEASE ' in line and profile_ok):
                try:
                    event = json.loads(line.split(' INK_RELEASE ', 1)[1])
                    fields = dict(inst=event['buff_uid'], ownerId=event['owner_id'])
                    state = bind(fields, line_no)
                    if (state and event.get('schema_version') == 1 and event['session_id'] == state.session
                            and event['template_key'] == BUFF and event['action_id'] == 14
                            and event['source_actor_id'] == str(state.record['source_actor_id'])
                            and type(event['operation_seq']) is int and event['operation_seq'] > state.last_seq):
                        projectile = event['projectile_id']
                        if projectile in releases:
                            releases[projectile]['reasons'].add('duplicate_projectile_release')
                        else:
                            releases[projectile] = state.freeze(projectile, event['operation_seq'], 'packet_projectile_id')
                except (ValueError, TypeError, KeyError, AttributeError):
                    pass
                continue

            # Legacy traces contain ACTOR_MAP inside the typed 13 -> launch 14 ->
            # reset 15 block. Require one mapping bracketed by that exact instance,
            # session, tick and order; never choose a nearby ledger by elapsed time.
            if ' ACTOR_MAP ' in line and release_preparation:
                fields = extract_fields(line)
                if fields.get('source') == 'launch_projectile' and fields.get('template') == OWNER:
                    release_preparation[2].append(dict(projectile=fields.get('id')))
                continue
            if ' SKILL_CAST_START ' in line and release_preparation:
                fields = extract_fields(line)
                for candidate in release_preparation[2]:
                    if (fields.get('ownerId') == candidate['projectile'] and fields.get('skill') == EXPLOSION
                            and _integer(fields.get('startMs')) == release_preparation[1][1]):
                        candidate.update(cast_instance_id=fields.get('inst'), cast_seq=_integer(fields.get('seq')))
                continue
            if not profile_ok or not any(tag in line for tag in (' BB_MODIFY_DYNAMIC ', ' BB_SIMPLE_CALC ')):
                continue
            fields = extract_fields(line.split(' identity=', 1)[0])
            if fields.get('skill') != BUFF:
                continue
            state = bind(fields, line_no)
            if state is None:
                continue
            sequence, tick, action = (_integer(fields.get(key)) for key in ('seq', 'tick', 'actionId'))
            if sequence is None or tick is None or action is None:
                state.reasons.add('missing_ink_operation_identity')
                continue
            if ' identity=' in line:
                try:
                    identity = json.loads(line.split(' identity=', 1)[1])
                    if (identity.get('schemaVersion') != 1 or identity.get('ownerType') not in (1, '1')
                            or identity.get('triggerType') != 0 or identity.get('actionType') != 7
                            or identity.get('actionRuntimeCase') != 'modify_dynamic_blackboard_action'
                            or identity.get('operationPayloadCase') != 'trigger_action_op_data'
                            or identity.get('sessionId') != state.session or identity.get('operationSeq') != sequence
                            or identity.get('ownerId') != fields.get('ownerId')
                            or identity.get('environmentInstId') != fields.get('inst')
                            or identity.get('templateType') != 'Buff' or identity.get('actionId') != action
                            or str(identity.get('clientTickMs')) != str(tick)):
                        state.reasons.add('ink_operation_context_mismatch')
                        state.pending = None
                        continue
                except (ValueError, TypeError, AttributeError):
                    state.reasons.add('invalid_ink_operation_identity')
                    continue
            elif fields.get('packetSessionId') not in (None, state.session):
                state.reasons.add('ink_operation_session_mismatch')
                continue
            signature = tuple(sorted(fields.items()))
            if sequence in state.seen:
                if state.seen[sequence] != signature:
                    state.reasons.add('conflicting_ink_operation')
                continue
            state.seen[sequence] = signature
            if sequence <= state.last_seq:
                state.reasons.add('out_of_order_ink_operation')
                continue
            state.last_seq = sequence
            if action == 45:
                value = _number(fields.get('value'))
                candidates = observed_sources.get((state.session, fields['ownerId'], tick, sequence - 1), [])
                matched = [source for source in candidates if value is not None and source.get('packet_final_value') is not None
                    and isclose(abs(source['packet_final_value']), value, rel_tol=1e-8, abs_tol=1e-6)
                    and source['line_no'] not in state.used_hits]
                source = matched[0] if len(matched) == 1 else None
                state.pending = (sequence, tick, source)
                if source:
                    state.used_hits.add(source['line_no'])
                    summary['paired_records'] += 1
                else:
                    summary['unpaired_records'] += 1
            elif action == 47 and fields.get('key') == 'EntityBB_ink_damage':
                previous, increment, final = (_number(fields.get(key)) for key in ('valueA', 'valueB', 'final'))
                if (None in (previous, increment, final) or min(previous, increment, final) < 0
                        or not _close(previous + increment, final) or previous < state.total and not _close(previous, state.total)):
                    state.reasons.add('invalid_ink_accumulator')
                    state.pending = None
                    continue
                if not _close(previous, state.total):
                    state.shares[OWNER] += max(0, previous - state.total)
                    state.total = previous
                    state.reasons.add('unobserved_ink_accumulation')
                # Attribute the observed float32 delta, including its rounding.
                delta = max(0, final - state.total)
                pending = state.pending
                source = pending[2] if pending and pending[1] == tick and 1 <= sequence - pending[0] <= 2 else None
                weights = _record_weights(source, increment) if source else None
                if not weights or sum(weights.values()) <= 0:
                    state.shares[OWNER] += delta
                    state.reasons.add('unpaired_ink_source_hit' if source is None else 'source_hit_attribution_unavailable')
                else:
                    weight_total = sum(weights.values())
                    for key, value in weights.items():
                        state.shares[key] += delta * value / weight_total
                    state.source_hits.append(source['seq'])
                    if source.get('rdps_unresolved_effect_conditions'):
                        state.reasons.add('source_hit_attribution_unresolved')
                state.total = final
                state.pending = None
            elif action == 66 and fields.get('key') == 'EntityBB_ink_damage':
                previous, final = (_number(fields.get(key)) for key in ('valueA', 'final'))
                if previous is not None and final is not None and final >= previous and _close(previous, state.total):
                    state.shares[OWNER] += max(0, final - state.total)
                    state.total = final
                    state.reasons.add('kill_bonus_provenance_unresolved')
            elif action == 13:
                release_preparation = [state, (sequence, tick), [], state.freeze('', sequence, 'legacy_typed_release_block')]
            elif action == 15 and _number(fields.get('value')) == 0:
                if release_preparation and release_preparation[0] is state and release_preparation[1][1] == tick:
                    projectiles = release_preparation[2]
                    if (len(projectiles) == 1 and projectiles[0].get('cast_instance_id')
                            and release_preparation[1][0] < (projectiles[0].get('cast_seq') or 0) < sequence
                            and projectiles[0]['projectile'] not in releases):
                        frozen = release_preparation[3]
                        frozen['projectile_id'] = projectiles[0]['projectile']
                        frozen['cast_instance_id'] = projectiles[0]['cast_instance_id']
                        releases[frozen['projectile_id']] = frozen
                release_preparation = None
                state.reset()


def ink_allocation_result(hit, *, include_debug=False):
    shares = hit.get('_ink_allocation')
    if shares is None:
        return None
    result = dict(allocation_policy=POLICY,
        allocation_policy_basis='accounting_convention', contributions_map=dict(shares),
        contributions_list=[dict(character_key=key, value=value) for key, value in
            sorted(shares.items(), key=lambda row: (-row[1], row[0]))])
    if include_debug:
        # A release mixes many source-time zones; no explosion-time multiplier
        # can represent their per-record distribution.
        result.update(zones=[], ignored_effects=[], attacker_share=shares.get(hit['character_key'], 0),
            external_pool=sum(value for key, value in shares.items() if key != hit['character_key']),
            product_external_multiplier=None, external_sources=[], zone_summary={}, buff_source_summary=[],
            ink_provenance=deepcopy(hit['ink_provenance']))
    return result
