"""Per-calculation phase measurements, local to the active analysis context."""
from contextvars import ContextVar
from time import perf_counter

ACTIVE_PHASES = ContextVar('live_phases', default=None)


def mark(name):
    active = ACTIVE_PHASES.get()
    if active is not None:
        now = perf_counter()
        active['phases'][name] = active['phases'].get(name, 0.0) + (now-active['last'])*1000
        active['last'] = now
