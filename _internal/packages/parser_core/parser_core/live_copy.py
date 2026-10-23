"""Isolated copies for the JSON-shaped live state, preserving shared identities."""
from collections import Counter, defaultdict
from copy import deepcopy
import io
import pickle
import threading

_COPY_CONTEXT = threading.local()


def _restore_defaults(factory_id):
    return defaultdict(_COPY_CONTEXT.factories[factory_id])


def _reduce_defaults(value):
    factory = value.default_factory
    _COPY_CONTEXT.factories[id(factory)] = factory
    return _restore_defaults, (id(factory),), None, None, iter(value.items())


def copy_ingestion_state(value):
    """Native detached graph copy, including aliases and local default factories.

    Only serializes objects already created by canonical ingestion in this
    process. No file, wire payload, or caller-supplied pickle is deserialized.
    """
    prior = getattr(_COPY_CONTEXT, 'factories', None)
    _COPY_CONTEXT.factories = {}
    try:
        buffer = io.BytesIO()
        pickler = pickle.Pickler(buffer, protocol=pickle.HIGHEST_PROTOCOL)
        pickler.dispatch_table = {defaultdict: _reduce_defaults}
        pickler.dump(value)
        return pickle.loads(buffer.getvalue())
    finally:
        _COPY_CONTEXT.factories = prior


def isolated_copy(value, memo=None):
    kind = type(value)
    if value is None or kind in (str, int, float, bool, bytes):
        return value
    if memo is None:
        memo = {}
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if kind in (dict, defaultdict, Counter):
        result = defaultdict(value.default_factory) if kind is defaultdict else Counter() if kind is Counter else {}
        memo[identity] = result
        for key, item in value.items():
            result[key] = isolated_copy(item, memo)
        return result
    if kind is list:
        result = []
        memo[identity] = result
        result.extend(isolated_copy(item, memo) for item in value)
        return result
    if kind is set:
        result = {isolated_copy(item, memo) for item in value}
        memo[identity] = result
        return result
    return deepcopy(value, memo)


def changed_records(previous, rows):
    """Reuse only detached, unchanged dependencies; ingestion is never shared."""
    return [old if index < len(previous) and (old := previous[index]) == row else isolated_copy(row)
            for index, row in enumerate(rows)]

