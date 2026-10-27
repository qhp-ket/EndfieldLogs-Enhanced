from __future__ import annotations
from typing import Any
from endfield_pcap.models import BattleLogEvent
from endfield_pcap.service.session.operations import BattleOperation, HANDLERS


class BattleEvents:
    def _emit_battle_events(self, message: Any, timestamp_ms: int) -> None:
        client_data = getattr(message, "client_data", None)
        if client_data is None:
            return
        emitted_clock_ticks: set[int] = set()
        for op in getattr(client_data, "op_list", []):
            op_type_name = self._field_enum_name(op, "op_type")
            if op_type_name is None:
                continue
            seq_id = int(getattr(op, "seq_id", 0)) or None
            client_tick_tms = int(getattr(op, "client_tick_tms", 0)) or None

            if (getattr(self, "rotation_clock_trace", False) and client_tick_tms is not None
                    and client_tick_tms > 0 and client_tick_tms not in emitted_clock_ticks):
                emitted_clock_ticks.add(client_tick_tms)
                self._emit_event(BattleLogEvent(
                    session_id=self.session_id, timestamp_ms=timestamp_ms,
                    event_type="GAME_CLOCK_TICK",
                    payload={"source": "CS_BATTLE_OP", "tick_ms": client_tick_tms, "seq_id": seq_id},
                ))

            handler = HANDLERS.get(op_type_name)
            if handler is not None:
                handler(BattleOperation(self, op, op_type_name, timestamp_ms, seq_id, client_tick_tms))
