"""Persistent live ingestion and a conservative, contiguous allocation frontier.

The canonical allocator is unchanged. Report projection still visits history to
build complete display/export data; trace ingestion and finalized hit allocation
are incremental. A dependency changing behind the frontier requests a replay.
"""
from contextvars import ContextVar
from parser_core.realtime.live_copy import isolated_copy as deepcopy, changed_records, copy_ingestion_state
from parser_core.realtime.live_frozen import FrozenHitEvidence, FrozenBuffEvidence, FrozenMutation
from functools import wraps
import math
from time import perf_counter
from parser_core.realtime.live_metrics import ACTIVE_PHASES, mark

ACTIVE_ALLOCATION_CACHE = ContextVar('live_allocation_cache', default=None)


def memoize_live_record(function):
    """Reuse exact record analysis, including the function's record mutations.

    Metadata/rules are fixed for the lifetime of one live engine. Offline calls
    always execute normally. Equality uses the full input record, not UID alone.
    """
    @wraps(function)
    def call(record, *, root_lookup_cache=None):
        cache = ACTIVE_ALLOCATION_CACHE.get()
        if cache is None:
            return function(record, root_lookup_cache=root_lookup_cache)
        key = (function.__name__, _identity(record))
        entries = cache.record_analyses.setdefault(key, [])
        for before, output, removed, result in entries:
            if record == before:
                for field in removed:
                    record.pop(field, None)
                record.update(deepcopy(output))
                return deepcopy(result)
        before = deepcopy(record)
        result = function(record, root_lookup_cache=root_lookup_cache)
        output = {field: value for field, value in record.items()
                  if field not in before or before[field] != value}
        entries.append((before, deepcopy(output), before.keys()-record.keys(), deepcopy(result)))
        del entries[:-4]
        return result
    return call


class ReplayRequired(RuntimeError):
    pass


def _stamp(row, default=-math.inf):
    for key in ('ts_ms', 'start_ts_ms', 'snapshot_ts_ms'):
        value = row.get(key)
        if isinstance(value, (int, float)):
            return value
    return default


def _change_at(old, new, start):
    """Earliest possibly affected timestamp; unknown changes invalidate at start.

    Only append-only timestamped evidence and future lifetime boundaries receive
    narrower invalidation. This intentionally favors replay over stale credit.
    """
    if old == new:
        return math.inf
    if isinstance(old, dict) and isinstance(new, dict):
        start = _stamp(new, _stamp(old, start))
        changes = []
        for key in old.keys() | new.keys():
            a, b = old.get(key), new.get(key)
            if a == b:
                continue
            if key in {'_dynamic_pending_state', '_dynamic_seen_contexts', '_dynamic_unresolved_keys',
                       'packet_modifier_last_seen_ts_ms'}:
                # Ingestion bookkeeping. Derived snapshots/record membership
                # carry the actual allocator dependency and are compared too.
                continue
            if key in {'end_ts_ms', 'snapshot_end_ts_ms'}:
                changes.append(min(v for v in (a, b) if isinstance(v, (int, float))))
            elif key in {'duration_ms', 'end_line_no', 'snapshot_end_line_no', 'end_is_observation_boundary'}:
                # These describe the same end boundary, never a second effect.
                ends = [v for row in (old, new) for k in ('end_ts_ms', 'snapshot_end_ts_ms')
                        if isinstance(v := row.get(k), (int, float))]
                changes.append(min(ends) if ends else start)
            else:
                changes.append(_change_at(a, b, start))
        return min(changes, default=math.inf)
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return min((_change_at(a, b, start) for a, b in zip(old, new)), default=math.inf)
    if isinstance(old, list) and isinstance(new, list) and new[:len(old)] == old:
        added = new[len(old):]
        if added and all(isinstance(row, dict) and _stamp(row) != -math.inf for row in added):
            return min(_stamp(row) for row in added)
    return start


def _identity(row):
    return (row.get('uid'), row.get('event_key'), row.get('ts_ms', row.get('start_ts_ms')),
            row.get('line_no', row.get('start_line_no')), row.get('target_actor_id'))


class AllocationFrontier:
    def __init__(self):
        from parser_core.realtime.live_totals import LiveDamageTotals
        self.damage_totals = LiveDamageTotals()
        self.summary_mode = False
        self.dependencies = None
        self.record_analyses = {}
        self.finalized = []
        self.previous = []
        self.pending_start_line = None
        self.allocated_hits = self.reused_hits = 0
        self.total_allocated_hits = self.total_reused_hits = 0
        self.ink = None
        self.ink_lines = []
        self.ink_outputs = {}
        self.last_hit_outputs = {}
        self.ink_bindings = {}
        self.replays = 0
        self.last_replay_reason = ''
        self.replay_reasons = {}
        self.relevant_lines = None
        self.ink_replays = 0
        self.last_ink_replay_reason = ''
        self.static_classifications = {}
        self.contribution_rows = []
        self.contribution_prefix = []
        self.maxima_prefix = []

    def begin(self, hits, windows, records, text):
        try:
            self._begin(hits, windows, records, text)
        except ReplayRequired as error:
            # Ingestion is still valid; this projection already contains the
            # entire current battle. Rebuild ALL allocations and ink ledgers
            # from it, instead of parsing those identical raw lines a second
            # time. A changed raw prefix takes the separate stream-replay path.
            self.replays += 1
            self.last_replay_reason = str(error)
            self.replay_reasons[str(error)] = self.replay_reasons.get(str(error), 0)+1
            self.dependencies = None
            self.finalized = self.previous = []
            self.record_analyses.clear()
            if self.ink is not None:
                self.ink.close()
            self.ink = None
            self.ink_lines = []
            self.ink_outputs = {}
            self.last_hit_outputs = {}
            self.ink_bindings = {}
            self._begin(hits, windows, records, text)

    def _begin(self, hits, windows, records, text):
        self.allocated_hits = self.reused_hits = 0
        dependencies = [changed_records(self.dependencies[index] if self.dependencies else [], rows)
                        for index, rows in enumerate((records or [], windows))]
        cutoff = math.inf
        if self.dependencies is not None and self.previous:
            if self.finalized and any(hit['ts_ms'] < self.finalized[-1]['input']['ts_ms']
                                      for hit in hits[len(self.previous):]):
                raise ReplayRequired('late damage arrived behind the finalized frontier')
            for old_rows, new_rows in zip(self.dependencies, dependencies):
                # Preserve duplicate identity/order too. Ambiguity is not proof.
                old = {_identity(row): row for row in old_rows}
                new = {_identity(row): row for row in new_rows}
                shared = old.keys() & new.keys()
                if ([key for key in old if key in shared] != [key for key in new if key in shared]):
                    cutoff = -math.inf
                if len(old) != len(old_rows) or len(new) != len(new_rows):
                    if old_rows != new_rows:
                        cutoff = -math.inf
                    continue
                for key in old.keys() | new.keys():
                    a, b = old.get(key), new.get(key)
                    start = _stamp(b or a)
                    cutoff = min(cutoff, _change_at(a, b, start))
            if any(row['input']['ts_ms'] >= cutoff for row in self.finalized):
                raise ReplayRequired('semantic evidence changed behind the finalized frontier')
            for index, cached in enumerate(self.finalized):
                if index >= len(hits) or cached['input'] != hits[index]:
                    raise ReplayRequired('finalized hit identity or hit-time context changed')
        # Memoization within the pending suffix does not move its frontier or
        # create committed islands. Any changed dependency invalidates a whole
        # suffix from its first affected damage node.
        self.reuse_limit = 0
        for index, cached in enumerate(self.previous):
            if index >= len(hits) or hits[index]['ts_ms'] >= cutoff or cached['input'] != hits[index]:
                break
            self.reuse_limit += 1
        self.dependencies = dependencies
        self.current = []
        self.text = text or ''

    def reuse(self, hit):
        index = len(self.current)
        if index < self.reuse_limit:
            cached = self.previous[index]
            self.current.append(cached)
            hit.update(deepcopy(cached['output']))
            self.reused_hits += 1
            self.total_reused_hits += 1
            return True
        return False

    def remember(self, original, hit):
        self.current.append(dict(input=original,
            output=deepcopy({key: value for key, value in hit.items()
                             if key not in original or value != original[key]})))
        self.allocated_hits += 1
        self.total_allocated_hits += 1

    def apply_ink(self, hits, records, *, root_lookup, extract_fields):
        from parser_core.ink_provenance import _ink_provenance_ingestion, EXPLOSION, BUFF
        # Only relevant lines are retained by the deferred ledger, independently
        # of the normal hit suffix. No damage is credited before an explosion.
        relevant = self.relevant_lines if self.relevant_lines is not None else [(number, line) for number, line in enumerate(self.text.splitlines(), 1)
                    if any(tag in line for tag in (' HP_V2 ', ' INK_RELEASE ', ' BB_MODIFY_DYNAMIC ',
                        ' BB_SIMPLE_CALC ', ' ACTOR_MAP ', ' SKILL_CAST_START '))]
        normal = {hit['line_no']: dict(hit.get('rdps_contributions') or {}) for hit in hits
                  if hit.get('skill_key') != EXPLOSION}
        changed = any(normal.get(line) != value for line, value in self.last_hit_outputs.items())
        binding_keys = ('packet_creation_contexts', 'source_actor_id', 'source_character_key',
                        'target_actor_id', 'rdps_live_identity_conflict', 'end_line_no')
        bindings = {_identity(row): deepcopy({key: row.get(key) for key in binding_keys})
                    for row in records if row.get('event_key') == BUFF}
        rebinding = any(bindings.get(key) != value for key, value in self.ink_bindings.items())
        if self.ink is None or changed or rebinding or relevant[:len(self.ink_lines)] != self.ink_lines:
            if self.ink is not None:
                self.ink_replays += 1
                self.last_ink_replay_reason = 'original contribution changed' if changed else 'ink binding changed' if rebinding else 'ink input prefix changed'
                self.ink.close()
            self.ink = _ink_provenance_ingestion(root_lookup=root_lookup, extract_fields=extract_fields)
            next(self.ink)
            self.ink_lines = []
            self.ink_outputs = {}
        summary = self.ink.send((relevant[len(self.ink_lines):], hits, records))
        self.ink_lines = list(relevant)
        self.last_hit_outputs = normal
        self.ink_bindings = bindings
        keys = ('_ink_allocation', 'ink_provenance', 'rdps_contributions', 'rdps_unresolved_effect_conditions')
        for hit in hits:
            if hit.get('skill_key') != EXPLOSION:
                continue
            line = hit['line_no']
            if '_ink_allocation' in hit:
                self.ink_outputs[line] = deepcopy({key: hit[key] for key in keys if key in hit})
            elif line in self.ink_outputs:
                hit.update(deepcopy(self.ink_outputs[line]))
        return dict(summary) if summary.get('explosions') else {}

    def finish(self, hits):
        # Only damage nodes can stop the frontier. Keep the last observed frame
        # open for follow-up BB/proof lines; all later hits form one suffix.
        latest = max((hit['ts_ms'] for hit in hits), default=-math.inf)
        count = 0
        for hit in hits:
            unresolved = any(value for key, value in hit.items()
                             if key.startswith('rdps_unresolved_') and key != 'rdps_unresolved_static_multiplier_sources')
            if unresolved or hit['ts_ms'] >= latest:
                break
            count += 1
        self.finalized = self.current[:count]
        self.previous = self.current
        self.pending_start_line = hits[count]['line_no'] if count < len(hits) else None

    def contribution_totals(self, hits):
        # Restoring a prefix before the first changed allocation retracts old
        # values and maxima, while preserving canonical float summation order.
        rows = [dict(hit.get('rdps_contributions') or {}) for hit in hits]
        first = 0
        while first < min(len(rows), len(self.contribution_rows)) and rows[first] == self.contribution_rows[first]:
            first += 1
        totals = dict(self.contribution_prefix[first-1]) if first else {}
        maxima = dict(self.maxima_prefix[first-1]) if first else {}
        del self.contribution_prefix[first:]
        del self.maxima_prefix[first:]
        for row in rows[first:]:
            for key, value in row.items():
                totals[key] = totals.get(key, 0.0)+value
                maxima[key] = max(maxima.get(key, 0.0), round(value, 4))
            self.contribution_prefix.append(dict(totals))
            self.maxima_prefix.append(dict(maxima))
        self.contribution_rows = rows
        return totals


class IncrementalBattleParser:
    def __init__(self, *, allow_empty=False):
        self.allow_empty = allow_empty
        self.stream = None
        self.lines = []
        self.input_lines = []
        self.text = ''
        self.relevant_lines = []
        self.timer_lines = []
        self.state = None
        self.frontier = AllocationFrontier()
        self.ingested_lines = 0
        self.replays = 0
        self.last_replay_reason = ''
        self.phases = {}
        self.report_builds = 0
        self.clock_projections = 0
        self.trace_replay_reasons = {}
        self.archived_allocation_reloads = 0
        self.archived_ink_replays = 0
        self.archived_allocation_reasons = {}
        self.archived_allocated_hits = self.archived_reused_hits = 0
        self.archived_ink_reason = ''
        self.raw_replayed_lines = 0
        self.last_raw_replayed_lines = 0
        self._replaying = False
        self.frozen_evidence = FrozenHitEvidence()
        self.frozen_buffs = FrozenBuffEvidence()
        self.freeze_disabled = False

    @property
    def diagnostics(self):
        return dict(phases=dict(self.phases), report_builds=self.report_builds, clock_projections=self.clock_projections,
            ingested_lines=self.ingested_lines, replay_count=self.replays+self.archived_allocation_reloads+self.frontier.replays,
            trace_replays=self.replays, allocation_reloads=self.archived_allocation_reloads+self.frontier.replays,
            raw_replayed_lines=self.raw_replayed_lines, last_raw_replayed_lines=self.last_raw_replayed_lines,
            trace_replay_reasons=dict(self.trace_replay_reasons), allocation_replay_reasons={
                reason: self.archived_allocation_reasons.get(reason, 0)+self.frontier.replay_reasons.get(reason, 0)
                for reason in self.archived_allocation_reasons.keys() | self.frontier.replay_reasons.keys()},
            immutable_evidence_enabled=not self.freeze_disabled,
            last_replay_reason=self.frontier.last_replay_reason or self.last_replay_reason,
            finalized_hits=len(self.frontier.finalized),
            pending_start_line=self.frontier.pending_start_line,
            allocated_hits=self.frontier.allocated_hits, reused_hits=self.frontier.reused_hits,
            total_allocated_hits=self.archived_allocated_hits+self.frontier.total_allocated_hits,
            total_reused_hits=self.archived_reused_hits+self.frontier.total_reused_hits,
            damage_updated_hits=self.frontier.damage_totals.updated_hits,
            damage_reused_hits=self.frontier.damage_totals.reused_hits,
            ink_replays=self.archived_ink_replays+self.frontier.ink_replays,
            last_ink_replay_reason=self.frontier.last_ink_replay_reason or self.archived_ink_reason)

    def _restart(self, reason):
        if self.stream is not None:
            self.stream.close()
        self.stream = self.state = None
        self.lines = []
        self.input_lines = []
        self.text = ''
        self.relevant_lines = []
        self.timer_lines = []
        self.archived_allocation_reloads += self.frontier.replays
        self.archived_ink_replays += self.frontier.ink_replays
        for reason, count in self.frontier.replay_reasons.items():
            self.archived_allocation_reasons[reason] = self.archived_allocation_reasons.get(reason, 0)+count
        self.archived_allocated_hits += self.frontier.total_allocated_hits
        self.archived_reused_hits += self.frontier.total_reused_hits
        self.archived_ink_reason = self.frontier.last_ink_replay_reason or self.archived_ink_reason
        self.frontier = AllocationFrontier()
        self.frozen_evidence = FrozenHitEvidence()
        self.frozen_buffs = FrozenBuffEvidence()
        self.replays += 1
        self.last_replay_reason = reason
        self.trace_replay_reasons[reason] = self.trace_replay_reasons.get(reason, 0)+1
        self._replaying = True

    def snapshot(self, lines, timer_line=None, *, summary=False, clock_previous=None):
        phases = {'phases': {}, 'last': perf_counter()}
        token = ACTIVE_PHASES.set(phases)
        try:
            try:
                return self._snapshot(lines, timer_line, summary=summary, clock_previous=clock_previous)
            except FrozenMutation:
                self.freeze_disabled = True
                self._restart('immutable evidence mutation; independent graph replay')
                return self._snapshot(lines, timer_line, summary=summary)
        finally:
            mark('output_projection_ms')
            self.phases = phases['phases']
            ACTIVE_PHASES.reset(token)

    def _snapshot(self, lines, timer_line=None, *, summary=False, clock_previous=None):
        from parser_core.ingestion.identity import _apply_short_actor_aliases
        from parser_core.reporting.battle import _build_raw_battle_report
        from parser_core.ingestion.fields import _coerce_int
        from parser_core.ingestion.fields import _extract_fields
        from parser_core.ingestion.fields import _parse_prefixed_timestamp_ms
        from parser_core.ingestion.stream import _raw_battle_ingestion
        from parser_core.unified import overlay_snapshot_from_report
        if lines[:len(self.input_lines)] != self.input_lines:
            self._restart('trace prefix or actor aliases changed')
        # Current canonical aliases are identity-only. Keep a conservative full
        # normalization path if a future/embedded alias transform is installed.
        alias_identity = (getattr(_apply_short_actor_aliases, '_live_identity', False)
                          and (not self.input_lines or self.input_lines[-1].endswith(('\n', '\r'))))
        if alias_identity:
            added_text = ''.join(lines[len(self.input_lines):])
            self.text += added_text
            normalized = self.lines + added_text.splitlines()
            text = self.text
        else:
            text = _apply_short_actor_aliases(''.join(lines))
            normalized = text.splitlines()
            if normalized[:len(self.lines)] != self.lines:
                self._restart('trace prefix or actor aliases changed')
            self.text = text
        if self.stream is None:
            self.stream = _raw_battle_ingestion(text)
            self.state = next(self.stream)
        added = normalized[len(self.lines):]
        if added:
            self.timer_lines.extend((number, line) for number, line in enumerate(added, len(self.lines)+1)
                if any(tag in line for tag in ('OFFICIAL_TIMER_', 'GAME_TIMER_', 'GAME_INST_', 'GAME_MECHANICS_TIME_FREEZE')))
            self.relevant_lines.extend((number, line) for number, line in enumerate(added, len(self.lines)+1)
                if any(tag in line for tag in (' HP_V2 ', ' INK_RELEASE ', ' BB_MODIFY_DYNAMIC ',
                    ' BB_SIMPLE_CALC ', ' ACTOR_MAP ', ' SKILL_CAST_START ')))
            self.state = self.stream.send(enumerate(added, len(self.lines)+1))
            self.ingested_lines += len(added)
            self.lines = normalized
        self.last_raw_replayed_lines = len(added) if self._replaying else 0
        self.raw_replayed_lines += self.last_raw_replayed_lines
        self._replaying = False
        self.input_lines = list(lines)
        self.frontier.relevant_lines = self.relevant_lines
        self.frontier.timer_lines = self.timer_lines
        self.frontier.line_count = len(normalized)+(1 if timer_line else 0)
        mark('new_input_ms')
        if summary and clock_previous is not None:
            from parser_core.realtime.live_summary import clock_summary
            projected = clock_summary(clock_previous, self.state, timer_line)
            if projected is not None:
                self.clock_projections += 1
                return projected
        # Root action indices retain immutable metadata roots by identity. Do
        # not deepcopy those roots or feed finalization changes back to state.
        roots = self.state['buff_root_action_indices']
        presentation_only = {'atb_gain_ms_by_char': {}, 'atb_observations': [],
                             'poise_damage_events': [], 'buff_attribute_refresh_events': [],
                             'char_skill_levels': {}} if summary else {}
        source = {key: value for key, value in self.state.items()
                  if key != 'buff_root_action_indices' and key not in presentation_only}
        evidence = buff_evidence = None
        if summary and not self.freeze_disabled:
            source, evidence = self.frozen_evidence.prepare(source)
            source, buff_evidence = self.frozen_buffs.prepare(source)
        state = copy_ingestion_state(source)
        if evidence is not None:
            for hit, fields in zip(state['hits'], evidence):
                hit.update(fields)
            for record, fields in zip(state['buff_starts'], buff_evidence):
                record.update(fields)
        state.update(presentation_only)
        state['buff_root_action_indices'] = roots
        mark('state_copy_ms')
        if timer_line:
            fields = _extract_fields(timer_line)
            elapsed = _coerce_int(fields.get('elapsedMs'), default=0)
            stamp = _parse_prefixed_timestamp_ms(timer_line)
            origin = state.get('timestamp_clock_origin')
            if stamp is not None and origin is not None:
                stamp = origin+(stamp-origin) % 86_400_000
                state['last_context_ms'] = stamp
                state['timer_observed_times'][len(normalized)+1] = stamp
            if elapsed > 0:
                state.update(live_timer_elapsed_ms=elapsed, game_timer_end_ms=stamp,
                    game_timer_elapsed_ms=elapsed, game_timer_window_elapsed_ms=elapsed)
            text += timer_line
        token = ACTIVE_ALLOCATION_CACHE.set(self.frontier)
        self.frontier.summary_mode = summary
        try:
            self.report_builds += 1
            report = _build_raw_battle_report(state, text, file_name='live-overlay.log', summary=summary, allow_empty=self.allow_empty)
        finally:
            ACTIVE_ALLOCATION_CACHE.reset(token)
        return report if summary or report is None else overlay_snapshot_from_report(report)
