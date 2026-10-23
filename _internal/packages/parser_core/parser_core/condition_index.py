"""Per-report temporal candidates; the allocator retains every semantic check.

Inclusive bounds deliberately retain ambiguous endpoint observations. Queries
preserve input order and support backward timestamps, so indexing cannot change
the existing identity, line-order, lifetime or packet-UID rules.
"""
from collections import defaultdict
import heapq


class ConditionRecordIndex:
    def __init__(self, records, coerce_integer):
        self.groups = defaultdict(list)
        self.state = {}
        for order, record in enumerate(records or []):
            start = coerce_integer(record.get('ts_ms'))
            if start is None:
                continue  # The existing active-record predicate rejects this.
            end = coerce_integer(record.get('end_ts_ms'))
            duration = coerce_integer(record.get('raw_duration_ms'))
            if duration is not None:
                end = min(end if end is not None else float('inf'), start + duration)
            target = str(record.get('target_enemy_key') or record.get('target_character_key') or '')
            self.groups[target].append((start, order, end, record))
        for rows in self.groups.values():
            rows.sort(key=lambda row: (row[0], row[1]))

    def candidates(self, target, stamp):
        rows = self.groups.get(target, [])
        state = self.state.get(target)
        if state is None or stamp < state[0]:
            state = [stamp, 0, {}, []]
            self.state[target] = state
        _, cursor, active, expiry = state
        while cursor < len(rows) and rows[cursor][0] <= stamp:
            _, order, end, record = rows[cursor]
            if end is None or end >= stamp:
                active[order] = record
                if end is not None:
                    heapq.heappush(expiry, (end, order))
            cursor += 1
        while expiry and expiry[0][0] < stamp:
            _, order = heapq.heappop(expiry)
            active.pop(order, None)
        state[0], state[1] = stamp, cursor
        return [active[order] for order in sorted(active)]


class EffectWindowIndex:
    """Inclusive time bounds only, retaining original window indices/order."""
    def __init__(self, windows):
        self.rows = []
        self.state = None
        for order, window in enumerate(windows):
            start, end = window.get('start_ts_ms'), window.get('end_ts_ms')
            self.rows.append((start if type(start) is int else float('-inf'), order,
                              end if type(end) is int else float('inf')))
        self.rows.sort()

    def candidates(self, stamp):
        if self.state is None or stamp < self.state[0]:
            self.state = [stamp, 0, set(), []]
        _, cursor, active, expiry = self.state
        while cursor < len(self.rows) and self.rows[cursor][0] <= stamp:
            _, order, end = self.rows[cursor]
            if end >= stamp:
                active.add(order)
                heapq.heappush(expiry, (end, order))
            cursor += 1
        while expiry and expiry[0][0] < stamp:
            _, order = heapq.heappop(expiry)
            active.discard(order)
        self.state[0], self.state[1] = stamp, cursor
        return sorted(active)
