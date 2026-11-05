"""Skill/resource JSONL preserves lifecycle and observed-only analysis rules."""
import pytest

from parser_core.ingestion.structured import consume_trace_event
from endfield_pcap.trace.legacy_skill import skill_legacy_lines
from test_structured_entity import state
from test_structured_identity import event


OWNER = "chr_0001_alpha"


def cast(phase="start", *, timestamp=1000, instance=71, skill="chr_0001_alpha_skill", **fields):
    return event("skill_cast", {"phase": phase, "skill_inst_id": instance, "owner_id": 11,
        "owner": OWNER, "skill": skill, "skill_source": "CharacterSkill", **fields}, timestamp)


def test_casts_share_lifecycle_without_legacy_parsing(monkeypatch):
    import parser_core.ingestion.skills as skills
    monkeypatch.setattr(skills, "_extract_fields", lambda *_: pytest.fail("Typed cast used a legacy row"))
    stream = state()
    consume_trace_event(stream, cast(skill="skill_7"), 1)
    assert stream.first_party_action_ms is None
    original = stream.skill_casts[0]
    consume_trace_event(stream, cast(timestamp=2000), 2)
    replacement = stream.skill_casts[1]
    assert stream.active_skill_casts_by_inst["71"] is replacement
    consume_trace_event(stream, cast("end", timestamp=1500, client_tick_ms=999999), 3)
    assert original["end_ts_ms"] is None
    assert replacement["end_ts_ms"] == 1500 and replacement["end_line_no"] == 3
    assert not stream.active_skill_casts_by_inst and stream.first_party_action_ms == 2000
    consume_trace_event(stream, cast("end", timestamp=3000, instance=72), 4)
    assert len(stream.skill_casts) == 2


def test_recent_cast_limit_and_skill_owner_fallback():
    stream = state()
    for index in range(20):
        consume_trace_event(stream, cast(instance=index + 1, timestamp=1000 + index, owner=None), index + 1)
    assert len(stream.skill_casts) == 20 and len(stream.active_skill_casts_by_inst) == 20
    assert len(stream.recent_skill_casts_by_char[OWNER]) == 16
    assert stream.recent_skill_casts_by_char[OWNER][0]["ts_ms"] == 1004
    assert stream.first_party_action_ms == 1000 and not stream.party_actor_ids


@pytest.mark.parametrize("reason,delta,gain", [("AddValue", 1.23456789, True), ("AddValue", 0, False),
    ("AddValue", -1, False), ("Consume", 1, False), ("AddValue", float("inf"), False), ("AddValue", None, False)])
def test_atb_keeps_only_observed_values_and_positive_gains(reason, delta, gain, monkeypatch):
    import parser_core.ingestion.skills as skills
    monkeypatch.setattr(skills, "_extract_fields", lambda *_: pytest.fail("Typed ATB used a legacy row"))
    stream = state()
    item = event("atb", {"owner": OWNER, "owner_id": 9007199254740993, "reason": reason,
        "value": 12.3456789, "delta": delta, "recovery_speed": None, "client_tick_ms": 0}, 1000)
    consume_trace_event(stream, item, 7)
    observation = stream.atb_observations[0]
    assert item.data["value"] == 12.3456789 and observation["value"] == 12.3457
    assert observation["owner_actor_id"] == "9007199254740993"
    assert observation["recovery_speed"] is None and observation["client_tick_ms"] == 0
    assert bool(stream.atb_gain_ms_by_char) is gain
    assert len(stream.atb_observations) == 1


@pytest.mark.parametrize("modify_type,source,original,accepted", [("PoiseDamage", None, "skill_a", True),
    ("PoiseDamage", "skill_b", "skill_a", True), ("PoiseDamage", None, None, False),
    ("Recover", "skill_a", None, False)])
def test_poise_retains_unknown_target_and_original_source(modify_type, source, original, accepted, monkeypatch):
    import parser_core.reporting.poise as poise
    monkeypatch.setattr(poise, "_extract_fields", lambda *_: pytest.fail("Typed poise used a legacy row"))
    stream = state()
    item = event("poise", {"modify_type": modify_type, "source": source, "original_source": original,
        "source_int": 0, "original_source_int": 42, "value": 1.23456789, "current_value": 0}, 1000)
    consume_trace_event(stream, item, 9)
    assert bool(stream.poise_damage_events) is accepted
    if accepted:
        observation = stream.poise_damage_events[0]
        assert observation["source"] == (source or original) and observation["source_int"] is None
        assert observation["orig_source_int"] == 42 and observation["value"] == 1.23457
        assert observation["current_value"] == 0 and "target_id" not in observation


@pytest.mark.parametrize("broken", [{"phase": "invalid"}, {"skill_inst_id": 71}, {"skill_source": 3}])
def test_invalid_cast_is_rejected_before_state_mutation(broken):
    stream = state()
    item = cast()
    item.data.update(broken)
    with pytest.raises(ValueError):
        consume_trace_event(stream, item, 1)
    assert not stream.skill_casts and stream.first_context_ms is None


def test_independent_cast_export_preserves_end_owner_spelling_and_timezone():
    item = cast("end", timestamp=-1, instance=9007199254740993, owner_id="0011", operation_seq=0, client_tick_ms=0)
    assert item.data["owner_id"] == "11" and item.data["skill_inst_id"] == "9007199254740993"
    assert skill_legacy_lines(item, timezone_offset_minutes=330) == [
        "[05:29:59.999] SKILL_CAST_END seq=0 endMs=0 inst=9007199254740993 owner=chr_0001_alpha "
        "ownerId=0011 skill=chr_0001_alpha_skill skillSource=CharacterSkill\n"]


def test_business_skill_resource_events_keep_raw_fields_and_order():
    from endfield_pcap.trace.bridge import TraceBridge
    events, fallback = [], []
    bridge = TraceBridge(write_enabled=False, line_sink=fallback.append, event_sink=events.append)
    bridge.handle_event({"type": "BattleOpSkillAttach", "timestamp_ms": 1000,
        "skill_inst_id": 71, "src_inst_id": 11, "template_str_id": "chr_0001_alpha_skill"})
    bridge.handle_event({"type": "BattleOpSkillStartCast", "timestamp_ms": 1100, "skill_inst_id": 71, "owner_id": 11})
    atb = {"type": "BattleOpUpdateAtbInfo", "timestamp_ms": 1200, "owner_id": 11,
        "reason": "AddValue", "atb_value": 12.3456789, "delta_value": 0}
    bridge.handle_event(atb)
    bridge.handle_event({"type": "BattleOpModifyPoiseValue", "timestamp_ms": 1300,
        "modify_type": "PoiseDamage", "value": 0.123456789, "cur_poise_value": 0})
    assert not fallback
    assert [item.type for item in events] == ["actor_mapping", "skill_cast", "atb", "poise"]
    assert [item.sequence for item in events] == [1, 2, 3, 4]
    assert events[2].data["value"] == 12.3456789 and "recovery_speed" not in events[2].data
    assert events[3].data["current_value"] == 0 and "attacker_id" not in events[3].data
    atb["atb_value"] = 99
    assert events[2].data["value"] == 12.3456789
