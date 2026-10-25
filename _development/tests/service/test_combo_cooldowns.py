from app_test_support.scenarios.combo import publisher, scene, trigger
from app_test_support.paths import TESTS
from copy import deepcopy
import json
import subprocess







def test_four_slots_unknown_then_captured_trigger_counts_down_with_capture_age():
    p, clock = publisher()
    assert len(p.current_message()["snapshot"]["slots"]) == 4
    p.feed_event(scene())
    assert all(row["status"] == "unknown" for row in p.current_message()["snapshot"]["slots"])
    clock.advance(500)
    p.feed_event(trigger())
    message = p.current_message()
    row = message["snapshot"]["slots"][0]
    assert row["total_ms"] == 20_000 and row["remaining_ms"] == 19_500
    assert row["battle_inst_id"] == "9007199254740993"
    assert row["evidence"]["timestamp_ms"] == "1000000"
    assert message["snapshot"]["quality"] == "provisional"
    clock.advance(1250)
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 18_300
    # Changing local wall time after the capture cannot change the countdown.
    clock.wall += 100_000
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 18_300
    clock.advance(20_000)
    assert p.current_message()["snapshot"]["slots"][0]["status"] == "ready"
    json.dumps(p.current_message(), allow_nan=False)

def test_retransmissions_and_multi_action_guard_never_extend_cd():
    p, clock = publisher()
    p.feed_event(scene())
    event = trigger()
    p.feed_event(event)
    clock.advance(1000)
    p.feed_event(trigger(seq_id=2, timestamp_ms=clock.wall))
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 19_000
    clock.advance(3000)
    p.feed_event(event)
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 16_000
    # A distinct action is still not evidence of a new cast.
    p.feed_event(trigger(seq_id=3, timestamp_ms=clock.wall))
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 16_000

def test_distribution_level_potential_refresh_and_reset_rules():
    p, clock = publisher()
    p.feed_event(scene())
    p.feed_event(trigger(133, slot=1, level=12))
    assert p.current_message()["snapshot"]["slots"][1]["total_ms"] == 12_000
    p.feed_event(trigger(612, slot=2))
    clock.advance(1000)
    p.feed_event(trigger(192, slot=2, timestamp_ms=clock.wall, seq_id=2))
    assert p.current_message()["snapshot"]["slots"][2]["status"] == "ready"
    p.feed_event(trigger(2257, slot=3, timestamp_ms=clock.wall))
    row = p.current_message()["snapshot"]["slots"][3]
    assert row["skill_id"] == 2256 and row["total_ms"] == 15_000

def test_roster_changes_reset_and_sessions_cannot_leak_cooldowns():
    p, clock = publisher()
    roster = scene()
    p.feed_event(roster)
    p.feed_event(trigger())
    p.feed_event(roster)
    assert p.current_message()["snapshot"]["slots"][0]["status"] == "cooldown"
    other = deepcopy(roster)
    other["char_list"][0]["battle_inst_id"] = 42
    p.feed_event(other)
    assert p.current_message()["snapshot"]["slots"][0]["status"] == "unknown"
    p.feed_event(trigger(owner_id=42))
    assert p.current_message()["snapshot"]["slots"][0]["status"] == "cooldown"
    p.feed_event({"type": "BattleOpModifyBattleState", "session_id": "s1", "is_in_battle": False})
    assert p.current_message()["snapshot"]["slots"][0]["status"] == "unknown"
    p.feed_event(trigger(owner_id=42))
    p.feed_event(scene("s2"))
    assert all(row["status"] == "unknown" for row in p.current_message()["snapshot"]["slots"])
    first = p.current_message()
    p.reset(new_stream=True)
    fresh = p.current_message()
    assert fresh["stream_id"] != first["stream_id"] and fresh["sequence"] == 0
    assert all(row["battle_inst_id"] is None for row in fresh["snapshot"]["slots"])

def test_non_skill_non_roster_and_unknown_skills_do_not_create_ready():
    p, clock = publisher()
    p.feed_event(trigger())
    p.feed_event(scene())
    for event in (trigger(template_type="Buff"), trigger(owner_id=42), trigger(999999)):
        p.feed_event(event)
    assert all(row["status"] == "unknown" for row in p.current_message()["snapshot"]["slots"])

def test_mifu_cast_uses_attached_instance_and_actions_never_restart_it():
    p, clock = publisher()
    p.feed_event(scene())
    owner = scene()["char_list"][0]["battle_inst_id"]
    p.feed_event({"type": "SC_SELF_SCENE_INFO_SKILLS", "session_id": "s1", "owner_inst_id": owner,
                  "skills": [{"skill_inst_id": 77, "template_int_id": 2115, "level": 12}]})
    cast = {"type": "BattleOpSkillStartCast", "session_id": "s1", "owner_id": owner,
            "skill_inst_id": 77, "timestamp_ms": clock.wall, "seq_id": 2, "client_tick_tms": 42}
    p.feed_event(cast)
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 19000
    for delay in [475, 4000, 20000]:
        clock.advance(delay)
        p.feed_event(trigger(2115, timestamp_ms=clock.wall, seq_id=delay))
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 0
    p.feed_event(cast)
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 0
    p.feed_event({**cast, "timestamp_ms": clock.wall, "seq_id": 3})
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 19000
    p.feed_event({"type": "BattleOpSkillDetach", "session_id": "s1", "skill_inst_id": 77})
    clock.advance(1000)
    p.feed_event({**cast, "timestamp_ms": clock.wall, "seq_id": 4})
    assert p.current_message()["snapshot"]["slots"][0]["remaining_ms"] == 18000

def test_cast_attach_owner_validation_and_mifu_potential_adjustment():
    p, clock = publisher()
    roster = scene()
    roster["char_list"][0]["potential_level"] = 1
    owner = roster["char_list"][0]["battle_inst_id"]
    p.feed_event(roster)
    p.feed_event({"type": "BattleOpSkillAttach", "session_id": "s1", "owner_id": owner,
                  "skill_inst_id": 77, "template_int_id": 2115, "skill_lv": 12})
    cast = {"type": "BattleOpSkillStartCast", "session_id": "s1", "owner_id": 42,
            "skill_inst_id": 77, "timestamp_ms": clock.wall, "seq_id": 1}
    p.feed_event(cast)
    assert p.current_message()["snapshot"]["slots"][0]["status"] == "unknown"
    clock.advance(450)
    p.feed_event({**cast, "owner_id": owner})
    row = p.current_message()["snapshot"]["slots"][0]
    assert row["total_ms"] == 17000 and row["remaining_ms"] == 16600
    assert row["evidence"]["capture_to_observer_ms"] == 450
