"""Ordered operation dispatch and synthetic multi-phase battle boundaries."""
from types import SimpleNamespace

import pytest

from endfield_pcap.service.session.battle import BattleEvents


class Session(BattleEvents):
    def __init__(self):
        self.session_id = "session"
        self.rotation_clock_trace = True
        self.merge_multi_phase_enemy_battles = True
        self.merged_battle_active = True
        self.tracked_enemy_inst_ids = {42}
        self.events = []

    def _field_enum_name(self, operation, field):
        return getattr(operation, field, None)

    def _emit_event(self, event):
        self.events.append(event)


@pytest.mark.parametrize("enemy_id,merged,expected_end", [
    (42, True, True), (99, True, False), (42, False, False),
])
def test_enemy_death_closes_only_tracked_merged_battle(enemy_id, merged, expected_end):
    session = Session()
    session.merge_multi_phase_enemy_battles = merged
    operation = SimpleNamespace(
        op_type="BattleOpEntityDie", seq_id=7, client_tick_tms=12345,
        entity_die_op_data=SimpleNamespace(entity_inst_id=enemy_id),
    )
    message = SimpleNamespace(client_data=SimpleNamespace(op_list=[operation]))
    session._emit_battle_events(message, 1700000000123)
    assert [event.event_type for event in session.events] == [
        "GAME_CLOCK_TICK", "BattleOpEntityDie",
        *(["BattleOpModifyBattleState"] if expected_end else []),
    ]
    assert session.events[1].payload == {
        "seq_id": 7, "client_tick_tms": 12345, "entity_inst_id": enemy_id,
    }
    assert all(event.session_id == "session" and event.timestamp_ms == 1700000000123
               for event in session.events)
    if expected_end:
        assert session.events[-1].payload == {
            "seq_id": 7, "client_tick_tms": 12345, "is_in_battle": False,
        }
        assert session.tracked_enemy_inst_ids == set()
        assert session.merged_battle_active is False
    else:
        assert session.tracked_enemy_inst_ids == {42}
        assert session.merged_battle_active is True


def test_clock_ticks_are_deduplicated_per_message_and_reset_next_message():
    session = Session()
    session.merged_battle_active = False
    operation = SimpleNamespace(
        op_type="BattleOpEntityDie", seq_id=8, client_tick_tms=12345,
        entity_die_op_data=SimpleNamespace(entity_inst_id=99),
    )
    message = SimpleNamespace(client_data=SimpleNamespace(op_list=[operation, operation]))
    session._emit_battle_events(message, 1000)
    session._emit_battle_events(message, 2000)
    assert [event.event_type for event in session.events] == [
        "GAME_CLOCK_TICK", "BattleOpEntityDie", "BattleOpEntityDie",
        "GAME_CLOCK_TICK", "BattleOpEntityDie", "BattleOpEntityDie",
    ]
