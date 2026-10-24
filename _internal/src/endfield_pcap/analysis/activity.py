"""Pause display analysis without losing ordered inputs or receipt clocks.

Only the service loop owns these queues. Catch-up yields between bounded chunks;
the original publisher remains the sole implementation of display semantics.
"""
from collections import deque
from copy import deepcopy


class DeferredDisplayInputs:
    def __init__(self, publisher, *, combo=False):
        self._publisher = publisher
        self.combo = combo
        self.pending = deque()

    @property
    def publisher(self):
        return self._publisher() if callable(self._publisher) else self._publisher

    def clear(self):
        self.pending.clear()

    def feed(self, value, *, active, reset=False):
        if active and not self.pending:
            self._apply(value, reset)
            return
        publisher = self.publisher
        clocks = ((publisher._wall_ms(), publisher._monotonic_ms()) if self.combo
                  else (publisher.clock(),))
        self.pending.append((deepcopy(value) if self.combo else value, reset, clocks))

    def _apply(self, value, reset):
        if self.combo:
            if reset:
                self.publisher.clear_cooldowns()
            else:
                self.publisher.feed_event(value)
        else:
            self.publisher.feed_line(value)

    def drain(self, limit=256):
        publisher = self.publisher
        original = ((publisher._wall_ms, publisher._monotonic_ms) if self.combo
                    else (publisher.clock,))
        try:
            for _ in range(min(limit, len(self.pending))):
                value, reset, clocks = self.pending.popleft()
                if self.combo:
                    publisher._wall_ms = lambda: clocks[0]
                    publisher._monotonic_ms = lambda: clocks[1]
                else:
                    publisher.clock = lambda: clocks[0]
                self._apply(value, reset)
        finally:
            if self.combo:
                publisher._wall_ms, publisher._monotonic_ms = original
            else:
                publisher.clock = original[0]
        return not self.pending
