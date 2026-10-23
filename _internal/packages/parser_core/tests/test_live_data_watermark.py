"""DPS numerator/time consistency, without changing the official timer policy.

The three complete recorded lines below are a sparse excerpt, not a complete
battle or a recreation of the screenshot totals. Source: trace_20261015-205200.log,
SHA256 f50b4ffa84cd798f5b7c420bbc6b311e21035f5f595432e1ca8a13fb8ecedc88,
lines 27336, 27383 and 31098. They retain the real 22.598-second observation.
Full-prefix screenshot-total verification uses the original file outside Git.
Other clock and boundary inputs in this module are explicit synthetic controls.
"""
from __future__ import annotations

import pytest

from parser_core import live as live_module
from parser_core.live import LiveOverlayBattleParser


RECORDED_LINES = (
    "[21:04:10.882] DUNGEON_CONTEXT dungeonId=indie_battletower015_ex source=SC_SELF_SCENE_INFO scene=430 sceneId=4617108682646749208 isReward=0 isCalc=0 isPass=0",
    "[21:04:13.371] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower015_ex challengeStartTs=1792069453332 challengeExpireTs=1792070053332",
    '[21:04:35.969] HP_V2 #1035 hit=11930 cum=11930 raw=11930.20 packetFinalValue=11930.203769187438 pHP=0 eHP=6951453 skill="chr_0027_tangtang_normal_skill" hits=1 skillLv=12 templateIntId=2045 templateType=Skill actionId=19 origTemplateIntId=2045 damageUnitIndex=0 partInstId=unknown dynBB=63:-2.22519,64:-0.242935,65:0.286343,68:0.275,76:1,76:2,39:-1.30791 calcBB=unknown src=chr_0027_tangtang tgt=eny_0120_klbear_tower015 atk=chr_0027_tangtang atkId=101722 tgtId=101806 seg=0 shared=2 critFlag=0 critDmg=-1.0000 eventInstId=101724 eventOwnerId=101722 packetSeq=17908 clientTick=299382 packetSessionId="b79f6462-9f66-4dac-9bfd-a949272e773d" packetOwnerId=101722 packetGeneration=52 ',
)
OBSERVED_MS = ((21 * 60 + 4) * 60 + 35) * 1000 + 969


def recorded_parser(*, aligned=True, min_reparse_interval_ms=0):
    parser = LiveOverlayBattleParser(align_to_data_watermark=aligned,
                                     min_reparse_interval_ms=min_reparse_interval_ms)
    parser.feed_lines(RECORDED_LINES)
    return parser


def damage(report):
    return {row["character_key"]: row["total_damage"] for row in report["participants"]}


def synthetic_hit(timestamp, value=100, sequence=1):
    return (f'[{timestamp}] HP_V2 #{sequence} hit={value} cum={value} raw={value} '
            'pHP=0 eHP=900000 skill="chr_0027_tangtang_normal_skill" hits=1 '
            'src=chr_0027_tangtang tgt=eny_0120_klbear_tower015 atk=chr_0027_tangtang '
            'atkId=101722 tgtId=101806 seg=0 shared=2 critFlag=0 critDmg=-1')


def synthetic_parser():
    parser = LiveOverlayBattleParser(align_to_data_watermark=True)
    parser.feed_lines([
        "[10:00:00.000] DUNGEON_CONTEXT dungeonId=indie_battletower015_ex source=SC_SELF_SCENE_INFO",
        "[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower015_ex challengeStartTs=100000",
        synthetic_hit("10:00:01.000"),
    ])
    return parser


def test_recorded_excerpt_keeps_22598ms_with_unchanged_damage_under_synthetic_60s_delay(monkeypatch):
    parser = recorded_parser()
    monkeypatch.setattr(live_module, "_current_clock_ms", lambda: OBSERVED_MS)
    first = parser.snapshot()
    monkeypatch.setattr(live_module, "_current_clock_ms", lambda: OBSERVED_MS + 60_000)
    # An explicit state toggle forces a real parse rather than only testing a
    # previously cached report. It must not override data-watermark alignment.
    parser.set_live_clock_enabled(False)
    parser.set_live_clock_enabled(True)
    delayed = parser.snapshot()
    assert first["battle"]["duration_ms"] == delayed["battle"]["duration_ms"] == 22_598
    assert damage(first) == damage(delayed) == {"chr_0027_tangtang": 11_930}
    assert delayed["participants"][0]["dps"] == round(11_930 / 22.598, 2)


def test_default_callers_retain_their_existing_wall_clock_semantics(monkeypatch):
    parser = recorded_parser(aligned=False)
    monkeypatch.setattr(live_module, "_current_clock_ms", lambda: OBSERVED_MS + 60_000)
    report = parser.snapshot()
    assert report["battle"]["duration_ms"] == 82_598
    assert damage(report) == {"chr_0027_tangtang": 11_930}


def test_no_new_input_reuses_the_report_without_reparsing_or_consulting_wall_time(monkeypatch):
    calls = []
    original = live_module.IncrementalBattleParser.snapshot

    def parse(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    def forbidden_wall_clock():
        raise AssertionError("a DPS data-watermark report must not consult wall time")

    monkeypatch.setattr(live_module.IncrementalBattleParser, "snapshot", parse)
    monkeypatch.setattr(live_module, "_current_clock_ms", forbidden_wall_clock)
    parser = recorded_parser()
    first = parser.snapshot()
    for _ in range(5):
        assert parser.snapshot() is first
    assert len(calls) == 1


@pytest.mark.parametrize("line,elapsed", [
    # Complete real line 31125 from the same trace, after the excerpt's HP row.
    ("[21:04:36.020] ENTITY_STATS id=2305843009213698884 template=abilityentity_chr_0027_tangtang_normal_skill_03 kind=summon level=unknown hp=1.0 attrs=[]", 22_649),
    # Synthetic non-damage observation: elapsed may advance without a new hit.
    ("[21:04:36.969] PING source=SYNTHETIC_WATERMARK_TEST", 23_598),
])
def test_a_processed_timestamp_advances_both_report_time_and_dps_without_adding_damage(line, elapsed, monkeypatch):
    calls = []
    original = live_module.IncrementalBattleParser.snapshot

    def parse(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(live_module.IncrementalBattleParser, "snapshot", parse)
    parser = recorded_parser()
    before = parser.snapshot()
    parser.feed_line(line)
    after = parser.snapshot()
    assert len(calls) == 2
    assert after["battle"]["duration_ms"] == elapsed
    assert damage(after) == damage(before)
    assert after["participants"][0]["dps"] == round(11_930 / (elapsed / 1000), 2)
    assert parser.snapshot() is after
    assert len(calls) == 2


def test_explicit_observer_clock_is_preserved_without_poisoning_later_watermark_calls(monkeypatch):
    monkeypatch.setattr(live_module, "_current_clock_ms", lambda: OBSERVED_MS + 120_000)
    parser = recorded_parser(min_reparse_interval_ms=500)
    explicit = parser.snapshot(now_ms=OBSERVED_MS + 60_000)
    assert explicit["battle"]["duration_ms"] == 82_598
    assert parser.snapshot(refresh=False) is explicit
    normal = parser.snapshot()
    assert normal["battle"]["duration_ms"] == 22_598
    assert damage(normal) == damage(explicit)
    assert parser.snapshot() is normal


def test_live_capture_enable_cannot_override_alignment(monkeypatch):
    monkeypatch.setattr(live_module, "_current_clock_ms", lambda: OBSERVED_MS + 60_000)
    parser = recorded_parser()
    for enabled in [False, True, False, True]:
        parser.set_live_clock_enabled(enabled)
        assert parser.snapshot()["battle"]["duration_ms"] == 22_598


def test_synthetic_reset_clears_the_report_and_new_official_start_begins_a_new_window():
    parser = synthetic_parser()
    assert parser.snapshot()["battle"]["duration_ms"] == 1000
    parser.feed_line("[10:00:02.000] GAME_TIMER_RESET source=SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST")
    assert parser.snapshot() is None
    assert parser.snapshot(refresh=False) is None
    parser.feed_lines([
        "[10:00:03.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower015_ex challengeStartTs=103000",
        synthetic_hit("10:00:03.500", value=200, sequence=2),
    ])
    report = parser.snapshot()
    assert report["battle"]["duration_ms"] == 500
    assert damage(report) == {"chr_0027_tangtang": 200}


def test_synthetic_phase_boundaries_and_official_completion_keep_the_existing_authority():
    parser = synthetic_parser()
    parser.feed_lines([
        "[10:00:01.500] GAME_TIMER_END source=PacketBattleState elapsedMs=1500 official=1",
        "[10:00:02.000] GAME_TIMER_START source=PacketBattleState startMs=2000 official=1",
        synthetic_hit("10:00:03.000", value=200, sequence=2),
    ])
    phase = parser.snapshot()
    assert phase["battle"]["duration_ms"] == 3000
    assert damage(phase) == {"chr_0027_tangtang": 300}
    parser.feed_line("[10:00:06.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId=indie_battletower015_ex isPass=1 passTime=4000")
    final = parser.snapshot()
    assert final["battle"]["duration_ms"] == 4000
    parser.feed_line("[10:00:20.000] PING source=SYNTHETIC_WATERMARK_TEST")
    assert parser.snapshot()["battle"]["duration_ms"] == 4000
    assert damage(parser.snapshot()) == damage(final)


def test_synthetic_midnight_progression_adds_one_day_and_remains_stable():
    parser = LiveOverlayBattleParser(align_to_data_watermark=True)
    parser.feed_lines([
        "[23:59:59.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower015_ex challengeStartTs=100000",
        synthetic_hit("00:00:00.250"),
    ])
    assert parser.snapshot()["battle"]["duration_ms"] == 1250
    parser.feed_line("[00:00:02.000] PING source=SYNTHETIC_WATERMARK_TEST")
    first = parser.snapshot()
    assert first["battle"]["duration_ms"] == 3000
    assert parser.snapshot() is first
    assert parser.snapshot(now_ms=3000)["battle"]["duration_ms"] == 4000
    assert parser.snapshot()["battle"]["duration_ms"] == 3000


def test_empty_and_unparseable_timestamp_input_cannot_read_wall_time_or_advance_the_watermark(monkeypatch):
    def forbidden_wall_clock():
        raise AssertionError("missing log time has no wall-clock fallback in this mode")

    monkeypatch.setattr(live_module, "_current_clock_ms", forbidden_wall_clock)
    parser = LiveOverlayBattleParser(align_to_data_watermark=True)
    assert parser.snapshot() is None
    parser.feed_line("[not-a-time] PING source=SYNTHETIC_WATERMARK_TEST")
    assert parser.snapshot() is None
    parser = recorded_parser()
    before = parser.snapshot()
    for line in ["", "[not-a-time] PING", "[21:04:broken] PING"]:
        parser.feed_line(line)
        after = parser.snapshot()
        assert after["battle"]["duration_ms"] == 22_598
        assert damage(after) == damage(before)


@pytest.mark.parametrize("transition", ["reset", "new_official_start"])
def test_inflight_old_generation_cannot_restore_a_report_after_a_timer_boundary(monkeypatch, transition):
    parser = synthetic_parser()
    original = live_module.IncrementalBattleParser.snapshot

    def parse(engine, lines, timer_line=None):
        monkeypatch.setattr(live_module.IncrementalBattleParser, "snapshot", original)
        if transition == "reset":
            parser.feed_line("[10:00:02.000] GAME_TIMER_RESET source=SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST")
        else:
            parser.feed_lines([
                "[10:00:03.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId=indie_battletower015_ex challengeStartTs=103000",
                synthetic_hit("10:00:03.500", value=200, sequence=2),
            ])
        return original(engine, lines, timer_line)

    monkeypatch.setattr(live_module.IncrementalBattleParser, "snapshot", parse)
    assert parser.snapshot() is None
    assert parser.snapshot(refresh=False) is None
    if transition == "reset":
        assert parser.snapshot() is None
    else:
        report = parser.snapshot()
        assert report["battle"]["duration_ms"] == 500
        assert damage(report) == {"chr_0027_tangtang": 200}
