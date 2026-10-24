"""Incremental work bounds, canonical equality, replay, and deferred ledgers."""
from parser_test_support.hits import hit
from parser_test_support.paths import FIXTURES
from copy import deepcopy
import pytest
from parser_core import battle_log_parser as core
from parser_core.incremental import IncrementalBattleParser
from parser_core.live import LiveOverlayBattleParser
from parser_core.unified import parse_overlay_battle_snapshot_text
from parser_core.ink_provenance import _ink_provenance_ingestion, EXPLOSION
from parser_test_support.ink import Trace, ATTACKER, SUPPORT

def test_every_prefix_matches_offline_and_old_hits_are_not_reallocated():
    engine, lines = IncrementalBattleParser(), []
    first = None
    for index in range(1, 31):
        lines.append(hit(index))
        result = engine.snapshot(lines)
        assert result == parse_overlay_battle_snapshot_text(''.join(lines), file_name='live-overlay.log')
        if index == 1:
            first = deepcopy(result)
        assert engine.diagnostics['ingested_lines'] == index
        assert engine.diagnostics['allocated_hits'] == 1
        assert engine.diagnostics['reused_hits'] == index-1
        assert engine.diagnostics['replay_count'] == 0
    assert engine.diagnostics['finalized_hits'] == 29
    assert engine.diagnostics['pending_start_line'] == 30
    assert first['battle']['total_damage'] == 120  # Published objects are immutable across updates.

def test_late_semantics_behind_frontier_replays_entire_current_battle():
    engine = IncrementalBattleParser()
    lines = [hit(i) for i in range(1, 5)]
    engine.snapshot(lines)
    lines.append('[10:00:00.150] BUFF_START #9 id="buff_wpn_lance_0014_damageup" uid=99 '
                 'src=chr_0035_liino owner=chr_0004_pelica ownerId=1001 srcId=2001 dur=10\n')
    actual = engine.snapshot(lines)
    assert actual == parse_overlay_battle_snapshot_text(''.join(lines), file_name='live-overlay.log')
    assert engine.diagnostics['replay_count'] == 1
    assert engine.diagnostics['allocation_reloads'] == 1
    assert engine.diagnostics['ingested_lines'] == 5

def test_pending_damage_is_one_suffix_but_can_reuse_unchanged_computations(monkeypatch):
    original = core._allocate_rdps_for_hit
    def unresolved_second(hit, windows, **kwargs):
        result = original(hit, windows, **kwargs)
        if hit['seq'] == 2:
            hit['rdps_unresolved_effect_conditions'] = True
        return result
    monkeypatch.setattr(core, '_allocate_rdps_for_hit', unresolved_second)
    engine = IncrementalBattleParser()
    lines = [hit(i) for i in range(1, 5)]
    engine.snapshot(lines)
    assert engine.diagnostics['finalized_hits'] == 1
    assert engine.diagnostics['pending_start_line'] == 2
    lines.append(hit(5))
    engine.snapshot(lines)
    assert engine.diagnostics['finalized_hits'] == 1
    assert engine.diagnostics['pending_start_line'] == 2
    assert engine.diagnostics['reused_hits'] == 4
    assert engine.diagnostics['allocated_hits'] == 1

def test_long_battle_is_not_truncated_and_reset_discards_incremental_state():
    live = LiveOverlayBattleParser(max_lines=5, align_to_data_watermark=True)
    live.feed_lines(hit(i) for i in range(1, 21))
    assert live.snapshot()['battle']['total_damage'] == 2400
    live.reset()
    assert live.snapshot() is None
    live.feed_line(hit(1))
    assert live.snapshot()['battle']['total_damage'] == 120
    assert live.incremental_diagnostics['ingested_lines'] == 1

@pytest.mark.parametrize('fixture', ['rdps_snapshot_contract.log', 'ink_recording_contract.log'])
@pytest.mark.parametrize('batch_size', [1, 3, 7])
def test_proof_refresh_and_ink_intermediate_prefixes_match_complete_parser(fixture, batch_size):
    lines = FIXTURES.joinpath(fixture).read_text(encoding='utf8').splitlines(keepends=True)
    engine = IncrementalBattleParser()
    for count in range(batch_size, len(lines)+batch_size, batch_size):
        prefix = lines[:count]
        try:
            reference = parse_overlay_battle_snapshot_text(''.join(prefix), file_name='live-overlay.log')
        except ValueError:
            with pytest.raises(ValueError):
                engine.snapshot(prefix)
        else:
            assert engine.snapshot(prefix) == reference

def test_changed_trace_prefix_rebuilds_ingestion_as_well_as_allocation():
    engine = IncrementalBattleParser()
    lines = [hit(i) for i in range(1, 4)]
    engine.snapshot(lines)
    lines[0] = lines[0].replace('hit=120', 'hit=150').replace('packetFinalValue=120', 'packetFinalValue=150')
    assert engine.snapshot(lines) == parse_overlay_battle_snapshot_text(''.join(lines), file_name='live-overlay.log')
    assert engine.diagnostics['trace_replays'] == 1
    assert engine.diagnostics['ingested_lines'] == 6

def test_unexpected_incremental_error_reloads_battle_and_recovers_next_revision(monkeypatch):
    live = LiveOverlayBattleParser(align_to_data_watermark=True)
    lines = [hit(i) for i in range(1, 4)]
    live.feed_lines(lines)
    original = IncrementalBattleParser.snapshot
    failures = [True]

    def fail_once(self, *args, **kwargs):
        if failures:
            failures.pop()
            raise RuntimeError('injected incremental failure')
        return original(self, *args, **kwargs)

    monkeypatch.setattr(IncrementalBattleParser, 'snapshot', fail_once)
    assert live.snapshot() == parse_overlay_battle_snapshot_text(''.join(lines), file_name='live-overlay.log')
    assert live.incremental_diagnostics['trace_replays'] == 1
    lines.append(hit(4))
    live.feed_line(lines[-1])
    assert live.snapshot() == parse_overlay_battle_snapshot_text(''.join(lines), file_name='live-overlay.log')
    assert live.incremental_diagnostics['ingested_lines'] == 4
    assert live.incremental_diagnostics['allocated_hits'] == 4

def test_synthetic_timer_with_leading_comment_uses_same_clock_without_ingesting_tick():
    engine = IncrementalBattleParser()
    lines = ['# trace header\n',
             '[10:00:00.000] OFFICIAL_TIMER_START gameId=fixture\n', hit(1)]
    for second in (1, 2):
        timer = f'[10:00:0{second}.000] LIVE_TIMER_TICK source=LIVE_TIMER_TICK elapsedMs={second*1000}\n'
        assert engine.snapshot(lines, timer) == parse_overlay_battle_snapshot_text(
            ''.join(lines)+timer, file_name='live-overlay.log')
        assert engine.diagnostics['ingested_lines'] == len(lines)
    lines.append(hit(2, millis=2500))
    assert engine.snapshot(lines) == parse_overlay_battle_snapshot_text(''.join(lines), file_name='live-overlay.log')
    assert engine.diagnostics['ingested_lines'] == len(lines)

@pytest.mark.parametrize('legacy', [True, False])
def test_deferred_ink_ledger_survives_each_line_without_credit_before_explosion(legacy):
    trace = Trace()
    trace.source(100, 120, {ATTACKER: 100, SUPPORT: 20})
    trace.dynamic(101, 45, 120)
    trace.add(102, 0, 12)
    trace.release(legacy=legacy)
    trace.explosion(12)
    trace.source(200, 100, {ATTACKER: 100}, tick=2000)
    trace.dynamic(201, 45, 100, tick=2000)
    trace.add(202, 0, 10, tick=2000)
    trace.release(230, projectile='9001')
    trace.explosion(10, seq=240, projectile='9001')
    expected = deepcopy(trace)
    expected_summary = expected.run()
    stream = _ink_provenance_ingestion(root_lookup=core._load_current_buff_roots(), extract_fields=core._extract_fields)
    next(stream)
    for number, line in enumerate(trace.lines, 1):
        visible = [hit for hit in trace.hits if hit['line_no'] <= number]
        summary = stream.send(([(number, line)], visible, trace.records))
        observed_explosions = [hit for hit in visible if hit.get('skill_key') == EXPLOSION]
        assert summary['explosions'] == len(observed_explosions)
        if not observed_explosions:
            assert sum(h.get('_ink_allocation', {}).get('chr_0036_jsspsi', 0) for h in visible) == 0
    stream.close()
    assert summary == expected_summary
    assert trace.hits == expected.hits
