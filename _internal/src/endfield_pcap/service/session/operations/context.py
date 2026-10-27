"""Identity and emitter owned by one ordered battle operation."""
from dataclasses import dataclass
from typing import Any
from endfield_pcap.models import BattleLogEvent


@dataclass(frozen=True, slots=True)
class BattleOperation:
    session: Any
    operation: Any
    type_name: str
    timestamp_ms: int
    sequence_id: int | None
    client_tick_ms: int | None

    def emit(self, payload, *, event_type: str | None = None):
        self.session._emit_event(BattleLogEvent(
            session_id=self.session.session_id, timestamp_ms=self.timestamp_ms,
            event_type=self.type_name if event_type is None else event_type, payload=payload,
        ))
