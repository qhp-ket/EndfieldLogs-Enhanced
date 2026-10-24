"""Snapshot quality is additive evidence, never a second numeric authority."""
from parser_test_support.paths import FIXTURES
from copy import deepcopy
import json
import pytest
from parser_core.battle_log_parser import parse_raw_battle_log_text
from parser_core import live as live_module
from parser_core.live import LiveOverlayBattleParser
from parser_core.snapshot_quality import build_snapshot_quality
from parser_core.unified import (
    parse_hit_viewer_log_text, parse_overlay_battle_snapshot_text,
    parse_upload_battle_log_text, rdps_totals_from_hit_debug,
    rdps_totals_from_raw_report,
)

FIXTURE = FIXTURES.joinpath("rdps_snapshot_contract.log").read_text(encoding="utf-8")
EXPECTED_RD = {"chr_0004_pelica": 640, "chr_0035_liino": 120}
GAME = "dung01_bossrush01_04"
START = f"[10:00:00.000] OFFICIAL_TIMER_START source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START gameId={GAME} challengeStartTs=1"
END = f"[10:00:03.000] OFFICIAL_TIMER_END source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE gameId={GAME} isPass=1 passTime=3000"
READY = "[10:00:00.000] LOADOUT slot=0 char=chr_0004_pelica weaponTemplate=wpn_funnel_0001 equipSuit={}"


def four_reports(text):
    parser = LiveOverlayBattleParser(align_to_data_watermark=True)
    parser.set_live_clock_enabled(False)
    parser.feed_lines(text.splitlines())
    return {
        "raw": parse_raw_battle_log_text(text),
        "viewer": parse_hit_viewer_log_text(text),
        "overlay": parse_overlay_battle_snapshot_text(text),
        "live": parser.snapshot(),
    }


def verified_evidence():
    # Explicit positive control for the projection, independent of game tables.
    return {
        "battle": {"duration_ms": 2000, "time_source": "game_timer",
                   "timer_integrity_ok": True, "timer_integrity_reasons": [],
                   "timer_window_valid": True, "timer_start_inferred": False},
        "rdps_preflight": {"ok": True, "blocker_count": 0, "blockers": []},
        "rdps_damage_basis": {"hit_count": 1, "rdps_preflight_ok": True,
                              "rdps_strict_ok": True, "rdps_conservation_ok": True},
        "unresolved_hits": [], "unresolved_buff_actions": [],
    }


def test_four_entry_fixture_numbers_and_quality_are_identical():
    reports = four_reports(FIXTURE)
    baseline = reports["raw"]
    quality = baseline["snapshot_quality"]
    assert quality["schema_version"] == 1
    assert quality["status"] == "provisional"
    assert quality["rdps"]["status"] == "provisional"
    assert quality["timing"]["status"] == "provisional"
    assert baseline["rdps_preflight"]["ok"] is False
    assert baseline["rdps_damage_basis"]["rdps_conservation_ok"] is True
    for name, report in reports.items():
        numbers = report["summary"] if name == "viewer" else report["battle"]
        assert numbers["duration_ms"] == 2000
        assert numbers["total_damage"] == 760
        assert numbers["total_dps"] == 380
        assert report["snapshot_quality"] == quality
        for key in ("rdps_preflight", "rdps_damage_basis", "unresolved_hits", "unresolved_buff_actions"):
            assert report[key] == baseline[key]
        totals = rdps_totals_from_hit_debug(report) if name == "viewer" else rdps_totals_from_raw_report(report)
        assert totals == EXPECTED_RD
        assert {row["character_key"]: row["total_rd"] for row in report["participants"]} == EXPECTED_RD
        assert {row["character_key"]: row["rdps"] for row in report["participants"]} == {
            "chr_0004_pelica": 320, "chr_0035_liino": 60,
        }
        assert "rdps_available" not in numbers
    assert parse_upload_battle_log_text(FIXTURE) == baseline
    # Contract can be sent to JS without rounding the fixture's uint64 buff UID.
    encoded = json.dumps(quality, allow_nan=False)
    assert json.loads(encoded) == quality
    assert "9007199254740993" in encoded


@pytest.mark.parametrize("conflict", [False, True])
def test_four_entry_timing_preserves_official_validation_and_raw_reasons(conflict):
    text = START + "\n" + FIXTURE + "\n" + END
    if conflict:
        text += "\n" + END.replace("passTime=3000", "passTime=100")
    reports = four_reports(text)
    quality = reports["raw"]["snapshot_quality"]
    expected = "provisional" if conflict else "verified"
    assert quality["timing"]["status"] == expected
    # Missing action-unit evidence still prevents rDPS verification.
    assert quality["rdps"]["status"] == quality["status"] == "provisional"
    for report in reports.values():
        assert report["snapshot_quality"] == quality
        timing = quality["timing"]["evidence"]
        assert timing["timer_integrity_ok"] is (not conflict)
    if conflict:
        assert "conflicting_official_timer_events" in timing["timer_integrity_reasons"]


def test_verified_requires_both_dimensions_and_does_not_modify_source():
    report = verified_evidence()
    before = deepcopy(report)
    quality = build_snapshot_quality(report)
    assert report == before
    assert quality["status"] == quality["rdps"]["status"] == quality["timing"]["status"] == "verified"
    assert quality["rdps"]["reasons"] == quality["timing"]["reasons"] == []
    report["battle"]["timer_integrity_ok"] = None
    quality = build_snapshot_quality(report)
    assert quality["rdps"]["status"] == "verified"
    assert quality["timing"]["status"] == quality["status"] == "provisional"
    assert quality["timing"]["evidence"]["timer_integrity_ok"] is None


@pytest.mark.parametrize("section,field,value", [
    ("rdps_preflight", "ok", False), ("rdps_preflight", "ok", None),
    ("rdps_preflight", "ok", 1), ("rdps_preflight", "blocker_count", 1),
    ("rdps_preflight", "blockers", [{"reason": "original_negative_reason"}]),
    ("rdps_damage_basis", "rdps_preflight_ok", False),
    ("rdps_damage_basis", "rdps_strict_ok", False),
    ("rdps_damage_basis", "rdps_conservation_ok", False),
    ("rdps_damage_basis", "missing_packet_hit_count", 1),
    ("rdps_damage_basis", "unresolved_damage_actor_count", 1),
    ("rdps_damage_basis", "hit_conservation_mismatch_count", 1),
    ("rdps_damage_basis", "hit_count", None),
])
def test_rdps_negative_or_missing_evidence_cannot_be_verified(section, field, value):
    report = verified_evidence()
    report[section][field] = value
    quality = build_snapshot_quality(report)
    assert quality["rdps"]["status"] == quality["status"] == "provisional"
    assert quality["rdps"]["evidence"][section][field] == value
    assert quality["timing"]["status"] == "verified"


@pytest.mark.parametrize("field,value,expected", [
    ("timer_integrity_ok", None, "provisional"),
    ("timer_integrity_ok", False, "provisional"),
    ("timer_integrity_reasons", ["original_timer_reason"], "provisional"),
    ("timer_integrity_reasons", None, "provisional"),
    ("timer_window_valid", None, "provisional"),
    ("timer_window_valid", False, "unavailable"),
    ("timer_start_inferred", True, "provisional"),
    ("timer_start_inferred", None, "provisional"),
    ("time_source", None, "provisional"),
    ("duration_ms", None, "unavailable"), ("duration_ms", 0, "unavailable"),
    ("duration_ms", -1, "unavailable"), ("duration_ms", float("nan"), "unavailable"),
])
def test_timing_negative_or_missing_evidence_cannot_be_verified(field, value, expected):
    report = verified_evidence()
    report["battle"][field] = value
    quality = build_snapshot_quality(report)
    assert quality["timing"]["status"] == quality["status"] == expected
    assert quality["rdps"]["status"] == "verified"
    json.dumps(quality, allow_nan=False)


def test_missing_evidence_and_zero_have_distinct_contract_values():
    missing = build_snapshot_quality({})
    assert missing["status"] == missing["rdps"]["status"] == "unavailable"
    assert missing["rdps"]["evidence"]["rdps_preflight"] is None
    assert missing["timing"]["evidence"]["duration_ms"] is None
    report = verified_evidence()
    report["rdps_damage_basis"]["hit_count"] = 0
    report["battle"]["duration_ms"] = 0
    zero = build_snapshot_quality(report)
    assert zero["status"] == zero["rdps"]["status"] == "unavailable"
    assert zero["timing"]["evidence"]["duration_ms"] == 0


@pytest.mark.parametrize("section,field", [
    ("rdps_preflight", "ok"), ("rdps_preflight", "blocker_count"),
    ("rdps_preflight", "blockers"), ("rdps_damage_basis", "hit_count"),
    ("rdps_damage_basis", "rdps_preflight_ok"),
    ("rdps_damage_basis", "rdps_strict_ok"),
    ("rdps_damage_basis", "rdps_conservation_ok"),
    ("battle", "timer_integrity_ok"), ("battle", "timer_integrity_reasons"),
    ("battle", "timer_window_valid"), ("battle", "timer_start_inferred"),
    ("battle", "time_source"), ("battle", "duration_ms"),
])
def test_removing_required_verification_evidence_never_defaults_to_verified(section, field):
    report = verified_evidence()
    del report[section][field]
    assert build_snapshot_quality(report)["status"] != "verified"


def test_evidence_copy_preserves_reasons_and_json_safe_uint64_without_aliases():
    report = verified_evidence()
    uid = (1 << 64) - 1
    blocker = {"uid": uid, "reason": "unresolved_buff_action_phase", "operationSeq": 0}
    report["rdps_preflight"].update(ok=False, blocker_count=1, blockers=[blocker])
    report["unresolved_buff_actions"] = [blocker]
    report["battle"]["timer_evidence"] = {"start": {"challengeStartTs": uid}}
    quality = build_snapshot_quality(report)
    evidence = json.loads(json.dumps(quality, allow_nan=False))
    copied = evidence["rdps"]["evidence"]["rdps_preflight"]["blockers"][0]
    assert copied == {"uid": str(uid), "reason": "unresolved_buff_action_phase", "operationSeq": 0}
    assert evidence["timing"]["evidence"]["timer_evidence"]["start"]["challengeStartTs"] == str(uid)
    quality["rdps"]["evidence"]["unresolved_buff_actions"][0]["reason"] = "changed"
    quality["rdps"]["evidence"]["rdps_preflight"]["blockers"].clear()
    assert report["rdps_preflight"]["blockers"] == [blocker]
    assert report["unresolved_buff_actions"][0]["reason"] == "unresolved_buff_action_phase"
    assert report["rdps_preflight"]["blockers"][0]["uid"] == uid


def test_context_without_damage_keeps_zero_results_and_unavailable_quality():
    reports = four_reports(READY)
    quality = reports["raw"]["snapshot_quality"]
    for name, report in reports.items():
        numbers = report["summary"] if name == "viewer" else report["battle"]
        assert numbers["duration_ms"] == numbers["total_damage"] == 0
        assert report["snapshot_quality"] == quality
        assert quality["status"] == quality["rdps"]["status"] == quality["timing"]["status"] == "unavailable"
    assert reports["raw"]["participants"] == reports["viewer"]["participants"] == []
    assert reports["overlay"]["participants"][0]["total_rd"] == 0


@pytest.mark.parametrize("parse", [parse_raw_battle_log_text, parse_hit_viewer_log_text, parse_overlay_battle_snapshot_text])
def test_empty_input_keeps_existing_exception(parse):
    with pytest.raises(ValueError, match="HP_V2"):
        parse("")
    assert LiveOverlayBattleParser().snapshot() is None


def test_live_cached_quality_and_new_generation_do_not_reuse_old_evidence(monkeypatch):
    parser = LiveOverlayBattleParser(align_to_data_watermark=True, min_reparse_interval_ms=60_000)
    parser.set_live_clock_enabled(False)
    parser.feed_lines((START + "\n" + FIXTURE + "\n" + END).splitlines())
    first = parser.snapshot()
    assert first["snapshot_quality"]["timing"]["status"] == "verified"
    original_parse = live_module.IncrementalBattleParser.snapshot
    calls = []
    def counted(*args, **kwargs):
        calls.append(1)
        return original_parse(*args, **kwargs)
    monkeypatch.setattr(live_module.IncrementalBattleParser, "snapshot", counted)
    assert parser.snapshot() is parser.snapshot(refresh=False) is first
    assert calls == []
    parser.feed_line("[10:00:04.000] GAME_TIMER_RESET source=CAPTURE_SESSION_START")
    assert parser.snapshot(refresh=False) is parser.snapshot() is None
    parser.feed_lines(FIXTURE.splitlines())
    second = parser.snapshot()
    assert second is not first and len(calls) == 1
    assert second["snapshot_quality"] == parse_raw_battle_log_text(FIXTURE)["snapshot_quality"]
    assert second["snapshot_quality"]["timing"]["evidence"]["timer_integrity_ok"] is None
    assert rdps_totals_from_raw_report(second) == EXPECTED_RD


def test_live_consecutive_official_battles_preserve_current_quality_only():
    parser = LiveOverlayBattleParser(align_to_data_watermark=True)
    parser.set_live_clock_enabled(False)
    parser.feed_lines((START + "\n" + FIXTURE + "\n" + END).splitlines())
    assert parser.snapshot()["snapshot_quality"]["timing"]["status"] == "verified"
    next_start = START.replace("10:00:00.000", "10:01:00.000").replace("challengeStartTs=1", "challengeStartTs=60001")
    next_fixture = FIXTURE.replace("10:00:", "10:01:")
    parser.feed_lines((next_start + "\n" + next_fixture).splitlines())
    second = parser.snapshot()
    assert second["snapshot_quality"] == parse_overlay_battle_snapshot_text(next_start + "\n" + next_fixture)["snapshot_quality"]
    assert second["snapshot_quality"]["timing"]["status"] == "provisional"
    assert second["snapshot_quality"]["timing"]["evidence"]["official_timer_end_seen"] is False
    assert rdps_totals_from_raw_report(second) == EXPECTED_RD
