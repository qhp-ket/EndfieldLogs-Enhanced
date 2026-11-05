"""Event-fed live battles share the existing boundary and publication state machine."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import logging
import time

from parser_core.realtime.events import EventBattleParser, LiveEventBatch
from parser_core.realtime.live import LiveOverlayBattleParser, _LIVE_CLOCK_MAX_DRIFT_MS
from parser_core.realtime.live_frozen import FrozenMutation


LOGGER = logging.getLogger(__name__)
_CONTEXT = frozenset(('dungeon', 'battle_result', 'squad', 'entity_stats', 'loadout_group',
    'loadout_slot', 'loadout_stats', 'buff_start', 'buff_blackboard',
    'legacy_attribute_modifier', 'legacy_damage_modifier'))


def _boundary(event):
    phase = event.data.get('phase')
    return (event.type == 'battle_timer' and phase in ('start', 'end', 'reset')
            or event.type == 'official_timer' and phase == 'end')


def preserved_event_context(events):
    boundary = next((index for index in range(len(events) - 1, -1, -1) if _boundary(events[index])), -1)
    return [event for event in events[boundary + 1:] if event.type in _CONTEXT]


class LiveEventOverlayBattleParser(LiveOverlayBattleParser):
    def __init__(self, *, timezone_offset_minutes=0, reference_date=None, **options):
        self.timezone_offset_minutes = timezone_offset_minutes
        self.reference_date = reference_date
        self._events = []
        self._consumed_events = 0
        self._event_recoveries = 0
        self._last_event_recovery_reason = ''
        super().__init__(**options)
        self._engine_generation = -1

    def feed_line(self, line):
        raise TypeError('Structured live input requires feed_events')

    def feed_event(self, event):
        return self.feed_events((event,))

    def feed_events(self, events):
        # Detach only the new batch. Feed and snapshot cannot split a business group.
        batch = deepcopy(tuple(events))
        with self._lock:
            for event in batch:
                self._feed_event(event)
            return self._snapshot

    def _feed_event(self, event):
        phase = event.data.get('phase')
        if event.type == 'battle_timer' and phase == 'reset':
            self.reset()
            return
        return self._feed_observation(event, clock_ms=event.captured_at_ms, absolute_clock=True,
            is_hit=event.type == 'damage', is_context=event.type in _CONTEXT,
            is_party_action=event.type == 'skill_cast' and phase == 'start',
            is_official_timer_start=event.type == 'official_timer' and phase == 'start',
            is_official_timer_end=event.type == 'official_timer' and phase == 'end',
            packet_timer_start=event.type == 'battle_timer' and phase == 'start',
            is_timer_end=event.type in ('battle_timer', 'official_timer') and phase == 'end',
            game_id=str(event.data.get('game_id') or ''), is_heartbeat=event.type == 'clock_tick',
            is_clock_tick=event.type == 'clock_tick' and event.data.get('source') in ('GAME_CLOCK_TICK', 'CS_BATTLE_OP'))

    def reset(self):
        with self._lock:
            super().reset()
            self._events.clear()

    def _append_input(self, item):
        self._events.append(item)

    def _retain_context(self):
        self._events = preserved_event_context(self._events)

    def history_event_context(self):
        with self._lock:
            source = self._events if self._official_timer_active else preserved_event_context(self._events)
            return deepcopy(tuple(event for event in source if event.type != 'damage'))

    def _live_timer_snapshot_line(self, now_ms=None):
        # This hook returns a numeric observation, never a synthetic legacy row.
        if (not self._official_timer_active or self._official_timer_start_abs_ms is None
                or self._hit_count <= 0 or self._closed_by_timer_end):
            return None
        if now_ms is None:
            now_ms = (self._last_clock_ms if self._align_to_data_watermark or not self._live_clock_enabled
                      else time.time_ns() // 1_000_000)
            if now_ms is not None and self._last_clock_ms is not None and abs(now_ms - self._last_clock_ms) > _LIVE_CLOCK_MAX_DRIFT_MS:
                now_ms = self._last_clock_ms
        if now_ms is None:
            return None
        now_ms = max(now_ms, self._last_hit_abs_ms if self._last_hit_abs_ms is not None else now_ms)
        return now_ms, max(now_ms - self._official_timer_start_abs_ms, 1)

    def _capture_input(self):
        after = self._consumed_events if self._engine_generation == self._generation else 0
        return LiveEventBatch(self._generation, self._revision, after, tuple(self._events[after:]))

    def _new_event_engine(self, first=None):
        reference = self.reference_date
        if reference is None and first is not None:
            zone = timezone(timedelta(minutes=self.timezone_offset_minutes))
            reference = datetime.fromtimestamp(first.captured_at_ms / 1000, zone).date()
        return EventBattleParser(reference_date=reference, timezone_offset_minutes=self.timezone_offset_minutes,
                                allow_empty=True)

    def _calculate_snapshot(self, batch, observer, generation, clock_previous):
        if self._engine_generation != generation:
            self._engine = self._new_event_engine(batch.events[0] if batch.events else None)
            self._engine_generation = generation
            self._consumed_events = 0
        try:
            result = self._engine.snapshot_events(batch, observer=observer, summary=self._summary)
        except Exception as error:
            self._event_recoveries += 1
            self._last_event_recovery_reason = type(error).__name__ + ': ' + str(error)
            LOGGER.exception('incremental event analysis failed; replaying the requested battle prefix')
            self._engine_generation = -1
            self._consumed_events = 0
            with self._lock:
                if generation != self._generation:
                    raise
                # Later arrivals belong to the next request, never this recovery result.
                prefix = tuple(self._events[:batch.after_evidence_index + len(batch.events)])
            fallback = self._new_event_engine(prefix[0] if prefix else None)
            if isinstance(error, FrozenMutation):
                fallback.freeze_disabled = True
            result = fallback.snapshot_events(replace(batch, after_evidence_index=0, events=prefix),
                                              observer=observer, summary=self._summary)
            self._engine = fallback
            self._engine_generation = generation
        self._consumed_events = batch.after_evidence_index + len(batch.events)
        return result

    @property
    def incremental_diagnostics(self):
        return {**super().incremental_diagnostics, 'event_recoveries': self._event_recoveries,
                'last_event_recovery_reason': self._last_event_recovery_reason}
