"""Clock observations preserve their independent capture and simulation domains."""
from parser_core.trace_model import event_data
from dataclasses import dataclass

from parser_core.ingestion.skill_wire import integer
from parser_core.ingestion.structured_damage import _object

CLOCK_TYPES = ('clock_tick', 'clock_sync', 'time_freeze_request', 'time_freeze_state')


def clock_data(event, event_type):
    if event_type == 'GAME_CLOCK_TICK':
        tick = integer(event.get('tick_ms'))
        if event.get('source') != 'CS_BATTLE_OP' or tick is None or tick <= 0:
            return None
        kind, source = 'clock_tick', 'CS_BATTLE_OP'
    else:
        kind = ('clock_sync' if event_type in ('CS_PING', 'SC_PING') else
                'time_freeze_request' if event_type in ('CS_GAME_TIME_FREEZE_START_REQ', 'CS_GAME_TIME_FREEZE_END_REQ')
                else 'time_freeze_state')
        source = event_type
    fields = {'clock_tick': (('tick_ms', 'tick_ms'), ('seq_id', 'operation_seq')),
              'clock_sync': (('msg_id', 'message_id'), ('client_ts', 'client_ts'), ('server_ts', 'server_ts'),
                             ('logical_ts', 'logical_ts'), ('raw_body_hex', 'raw_body_hex')),
              'time_freeze_request': (('msg_id', 'message_id'), ('reason', 'reason'), ('raw_body_hex', 'raw_body_hex')),
              'time_freeze_state': (('msg_id', 'message_id'), ('reason', 'reason'), ('raw_body_hex', 'raw_body_hex'),
                                    ('in_time_freeze', 'in_time_freeze'))}[kind]
    return kind, {'source': source, **{target: event[key] for key, target in fields if key in event}}


@dataclass(frozen=True)
class ClockObservation:
    kind: str
    source: str
    captured_at_ms: int | None
    tick_ms: int | None = None
    client_ts: int | None = None
    server_ts: int | None = None
    logical_ts: int | None = None
    frozen: bool | None = None


def clock_observation(event):
    if event.type not in CLOCK_TYPES:
        raise ValueError('Expected clock event')
    data = _object(event_data(event))
    source = data.get('source')
    if not isinstance(source, str) or not source:
        raise ValueError('Clock event requires its observed source')
    def nonnegative(key):
        value = integer(data.get(key))
        return value if value is not None and value >= 0 else None
    frozen = data.get('in_time_freeze')
    return ClockObservation(event.type, source, event.captured_at_ms, integer(data.get('tick_ms')),
                            nonnegative('client_ts'), nonnegative('server_ts'), nonnegative('logical_ts'),
                            frozen if type(frozen) is bool else None)


def consume_structured_clock(ingestion, event, evidence_index):
    clock = clock_observation(event)
    if clock.source == 'GAME_TIMER_TICK':
        ingestion.timer_observed_times[evidence_index] = event.captured_at_ms
    if clock.source in ('GAME_TIMER_TICK', 'HEARTBEAT'):
        ingestion.pending_buff_record = None
    # Clock-only evidence does not create damage or an authoritative elapsed time.
    if ingestion.timestamp_clock_origin is None:
        ingestion.timestamp_clock_origin = event.captured_at_ms
    if ingestion.first_context_ms is None:
        ingestion.first_context_ms = event.captured_at_ms
    ingestion.last_context_ms = event.captured_at_ms
