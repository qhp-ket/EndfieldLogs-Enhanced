from pathlib import Path
from unittest.mock import patch

import pytest
from parser_core.incremental import IncrementalBattleParser
from parser_core.live import LiveOverlayBattleParser
from parser_core.live_summary import summary_from_report
from parser_core.unified import parse_overlay_battle_snapshot_text
from test_incremental_live import hit


@pytest.mark.parametrize('fixture', ['rdps_snapshot_contract.log', 'ink_recording_contract.log'])
@pytest.mark.parametrize('batch', [1, 7])
def test_summary_matches_canonical_every_prefix(fixture, batch):
    lines = Path(__file__).with_name('fixtures').joinpath(fixture).read_text(encoding='utf8').splitlines(keepends=True)
    engine = IncrementalBattleParser()
    for count in range(batch, len(lines)+batch, batch):
        prefix = lines[:count]
        try:
            full = parse_overlay_battle_snapshot_text(''.join(prefix), file_name='live-overlay.log')
        except ValueError:
            assert engine.snapshot(prefix, summary=True) is None
        else:
            assert engine.snapshot(prefix, summary=True) == summary_from_report(full)


def test_summary_does_not_build_display_details_or_copy_quality_evidence():
    with patch('parser_core.battle_log_parser._build_buff_events', side_effect=AssertionError), \
         patch('parser_core.battle_log_parser._build_role_skill_stats_from_timeline_groups', side_effect=AssertionError), \
         patch('parser_core.snapshot_quality._json_evidence', side_effect=AssertionError):
        result = IncrementalBattleParser().snapshot([hit(1), hit(2)], summary=True)
    assert set(result) == {'battle', 'participants', 'quality_summary'}
    assert 'evidence' not in result['quality_summary']['rdps']


@pytest.mark.parametrize('summary', [True, False])
def test_ended_heartbeats_do_not_build_or_allocate_but_late_evidence_does(summary):
    parser = LiveOverlayBattleParser(summary=summary, align_to_data_watermark=True)
    parser.feed_lines(['[10:00:00.000] OFFICIAL_TIMER_START gameId=test\n', hit(1), hit(2),
                       '[10:00:01.000] OFFICIAL_TIMER_END gameId=test passTimeMs=1000 isPass=1\n'])
    first = parser.snapshot()
    before = parser.incremental_diagnostics
    for index in range(10):
        parser.feed_line(f'[10:00:02.{index:03d}] GAME_CLOCK_TICK source=CS_BATTLE_OP tickMs={index}\n')
        assert parser.snapshot() is first
    assert parser.incremental_diagnostics['report_builds'] == before['report_builds']
    assert parser.incremental_diagnostics['total_allocated_hits'] == before['total_allocated_hits']
    parser.feed_line('[10:00:00.150] ENTITY_STATS id=1001 attr87=100\n')
    parser.snapshot()
    assert parser.incremental_diagnostics['report_builds'] == before['report_builds']+1


def test_clock_only_updates_match_full_semantics_without_reallocating():
    parser = LiveOverlayBattleParser(summary=True, align_to_data_watermark=True)
    full = LiveOverlayBattleParser(align_to_data_watermark=True)
    lines=['[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=test challengeStartTs=1\n',hit(1),hit(2)]
    parser.feed_lines(lines);full.feed_lines(lines)
    assert parser.snapshot()==summary_from_report(full.snapshot())
    before=parser.incremental_diagnostics['report_builds']
    for index in range(3,15):
        line=f'[10:00:0{index//10}.{index%10}00] GAME_CLOCK_TICK source=CS_BATTLE_OP tickMs={index*100}\n'
        parser.feed_line(line);full.feed_line(line)
        assert parser.snapshot()==summary_from_report(full.snapshot())
    assert parser.incremental_diagnostics['report_builds']==before
    assert parser.incremental_diagnostics['clock_projections']==12
    parser.feed_line('[10:00:00.150] UNKNOWN_LATE_EVIDENCE test=1\n')
    parser.snapshot()
    assert parser.incremental_diagnostics['report_builds']==before+1
