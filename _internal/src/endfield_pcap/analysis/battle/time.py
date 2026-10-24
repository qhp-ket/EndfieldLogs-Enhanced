"""Display units only; keep canonical timestamps and durations in milliseconds."""
import math


FRAMES_PER_SECOND = 30


def time_value(milliseconds, unit='seconds'):
    return milliseconds * (FRAMES_PER_SECOND / 1000 if unit == 'frames' else .001)


def format_time(milliseconds, unit='seconds', *, suffix=True):
    if unit == 'frames':
        text = f'{time_value(milliseconds, unit):.2f}'.rstrip('0').rstrip('.')
        return text + ('F' if suffix else '')
    return f'{milliseconds/1000:.3f}' + ('s' if suffix else '')


def ruler_ticks(start_ms, end_ms, width, scale=1., unit='seconds'):
    start, end = time_value(start_ms, unit), time_value(end_ms, unit)
    step = max(1. if unit == 'frames' else .001,
               (end-start)/max(2, width/(90*scale)))
    magnitude = 10**math.floor(math.log10(step))
    tick = next(n*magnitude for n in (1, 2, 5, 10) if n*magnitude >= step)
    value = math.ceil(start/tick)*tick
    divisor = FRAMES_PER_SECOND/1000 if unit == 'frames' else .001
    while value <= end+tick*1e-9:
        yield value/divisor, f'{value:g}' + ('F' if unit == 'frames' else 's')
        value += tick
