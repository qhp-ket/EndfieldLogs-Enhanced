"""Direct append-only event input using the existing ingestion and allocation rules."""
from dataclasses import dataclass, replace
from datetime import date
from threading import RLock
from time import perf_counter

from parser_core.ingestion.state import IngestionState
from parser_core.ingestion.structured import consume_trace_event
from parser_core.ink_provenance import ink_trace_observation
from parser_core.realtime.incremental import IncrementalBattleParser
from parser_core.realtime.live_copy import isolated_copy
from parser_core.realtime.live_metrics import ACTIVE_PHASES, mark
from parser_core.trace_jsonl import TraceEvent


@dataclass(frozen=True, slots=True)
class LiveEventBatch:
    generation: int
    revision: int
    after_evidence_index: int
    events: tuple[TraceEvent, ...]


class EventBattleParser(IncrementalBattleParser):
    def __init__(self, *, reference_date=None, timezone_offset_minutes=0, allow_empty=False,
                 file_name='live-overlay.log', first_hit_hint=None, last_hit_hint=None):
        super().__init__(allow_empty=allow_empty)
        self.reference_date = reference_date or date.today()
        self.timezone_offset_minutes = timezone_offset_minutes
        self.file_name = file_name
        self.first_hit_hint, self.last_hit_hint = first_hit_hint, last_hit_hint
        self._gate = RLock()
        self._source_generation = None
        self._event_revision = -1
        self._consumed_events = 0
        self._ingestion = None
        self._cached_key = self._cached_snapshot = None

    def _coordinate(self, unix_ms):
        stamp = (unix_ms + self.timezone_offset_minutes * 60_000) % 86_400_000
        origin = self._ingestion.timestamp_clock_origin
        return stamp if origin is None else origin + (stamp - origin) % 86_400_000

    def snapshot(self, *args, **kwargs):
        raise TypeError('Use snapshot_events for structured input')

    def snapshot_events(self, batch, *, observer=None, summary=False):
        """Consume only the suffix after the acknowledged evidence watermark.

        observer is an optional (Unix milliseconds, elapsed milliseconds) runtime
        observation. It is never serialized as captured business evidence.
        """
        with self._gate:
            same_generation = self._source_generation == batch.generation
            if self._source_generation is not None and batch.generation < self._source_generation:
                raise ValueError('Stale live event generation')
            if batch.after_evidence_index != (self._consumed_events if same_generation else 0):
                raise ValueError('Live event batch does not begin at the consumed watermark')
            if same_generation and (batch.revision < self._event_revision or batch.events and batch.revision <= self._event_revision):
                raise ValueError('Stale live event revision')
            if not same_generation:
                if self._source_generation is not None:
                    # An explicit generation transition is not an error replay.
                    super().__init__(allow_empty=self.allow_empty)
                self._event_revision = -1
                self._consumed_events = 0
                self._cached_key = self._cached_snapshot = None
                self._source_generation = batch.generation
                from parser_core.ingestion.fields import _parse_hint_timestamp_ms
                self._ingestion = IngestionState(reference_date=self.reference_date,
                    first_hit_hint_ms=_parse_hint_timestamp_ms(self.first_hit_hint),
                    last_hit_hint_ms=_parse_hint_timestamp_ms(self.last_hit_hint), context_enemy_hint=None, trace_identity_inference_seen=False,
                    loadout_override_by_char=None, critical_attributes_override_by_actor=None)
            phases = {'phases': {}, 'last': perf_counter()}
            token = ACTIVE_PHASES.set(phases)
            try:
                for event in batch.events:
                    self._consumed_events += 1
                    event = replace(event, captured_at_ms=self._coordinate(event.captured_at_ms))
                    consume_trace_event(self._ingestion, event, self._consumed_events)
                    self._ingestion.timestamp_clock_origin = (event.captured_at_ms if self._ingestion.timestamp_clock_origin is None
                                                              else self._ingestion.timestamp_clock_origin)
                    if self._ingestion.first_context_ms is None:
                        self._ingestion.first_context_ms = event.captured_at_ms
                    self._ingestion.last_context_ms = event.captured_at_ms
                    if event.type in ('damage', 'ink_release', 'blackboard_dynamic', 'blackboard_calculation', 'actor_mapping', 'skill_cast'):
                        self.relevant_lines.append((self._consumed_events, ink_trace_observation(event)))
                    self.ingested_lines += 1
                self._event_revision = batch.revision
                key = batch.revision, observer, summary
                if self._cached_key == key:
                    return isolated_copy(self._cached_snapshot)
                self.state = self._ingestion.snapshot()
                self.state['reference_timezone_offset_minutes'] = self.timezone_offset_minutes
                self.frontier.relevant_lines = self.relevant_lines
                self.frontier.line_count = self._consumed_events
                mark('new_input_ms')
                runtime_clock = None if observer is None else (self._coordinate(observer[0]), observer[1])
                snapshot = self._project('', summary=summary, evidence_count=self._consumed_events,
                                         observer=runtime_clock, file_name=self.file_name)
                self._cached_snapshot = isolated_copy(snapshot)
                self._cached_key = key
                return snapshot
            except BaseException:
                # The caller must replay a failed batch from zero; a partial watermark is not acknowledged.
                self._restart('structured event batch failed')
                self._source_generation = None
                self._event_revision = -1
                self._consumed_events = 0
                self._cached_key = self._cached_snapshot = None
                raise
            finally:
                mark('output_projection_ms')
                self.phases = phases['phases']
                ACTIVE_PHASES.reset(token)
