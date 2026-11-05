"""Shared structured trace disk boundary; live analysis consumes event objects."""
from __future__ import annotations

from dataclasses import dataclass
import json
from math import isfinite
from typing import Any, BinaryIO


@dataclass(frozen=True, slots=True)
class TraceHeader:
    recording_id: str
    volume: int
    previous_volume: dict[str, Any] | None
    language: str
    generator_version: str
    timezone_id: str
    timezone_offset_minutes: int
    resources: dict[str, str]


@dataclass(frozen=True, slots=True)
class TraceEvent:
    sequence: int
    captured_at_ms: int
    type: str
    data: dict[str, Any]
    source: dict[str, Any]
    client_tick_ms: int | None = None


def to_object(record: TraceHeader | TraceEvent) -> dict[str, Any]:
    if isinstance(record, TraceHeader):
        return {"format": "endfield.trace", "version": 1, "recording_id": record.recording_id,
                "volume": record.volume, "previous_volume": record.previous_volume,
                "generator": {"language": record.language, "version": record.generator_version},
                "timezone": {"id": record.timezone_id, "offset_minutes": record.timezone_offset_minutes},
                "resources": record.resources}
    value = {"seq": record.sequence, "captured_at_ms": record.captured_at_ms, "type": record.type,
             "source": record.source, "data": record.data}
    if record.client_tick_ms is not None:
        value["client_tick_ms"] = record.client_tick_ms
    return value


def _object(value):
    if not isinstance(value, dict):
        raise ValueError("Expected trace object")
    return value


def _text(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Expected nonempty trace text")
    return value


def _integer(value, *, bits=64):
    if type(value) is not int or not -(2**(bits-1)) <= value < 2**(bits-1):
        raise ValueError("Expected trace integer")
    return value


def _finite(value):
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("Non-finite trace number requires explicit evidence status")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError("Trace object keys must be strings")
            _finite(child)
    elif isinstance(value, list):
        for child in value:
            _finite(child)


def from_object(value: dict[str, Any], *, header: bool) -> TraceHeader | TraceEvent:
    _object(value)
    _finite(value)
    if header:
        if value.get("format") != "endfield.trace" or _integer(value.get("version")) != 1:
            raise ValueError("Unsupported trace format or version")
        volume = _integer(value.get("volume"), bits=32)
        if volume < 1:
            raise ValueError("Trace volume must be positive")
        previous = value.get("previous_volume")
        if previous is not None:
            _object(previous)
            _integer(previous.get("volume"), bits=32)
            _text(previous.get("file"))
        if (volume == 1 and previous is not None) or (volume > 1 and (previous is None or previous["volume"] != volume - 1)):
            raise ValueError("Trace previous-volume reference is inconsistent")
        generator = _object(value.get("generator"))
        timezone = _object(value.get("timezone"))
        resources = _object(value.get("resources"))
        for resource in resources.values():
            _text(resource)
        return TraceHeader(_text(value.get("recording_id")), volume, previous,
                           _text(generator.get("language")), _text(generator.get("version")),
                           _text(timezone.get("id")), _integer(timezone.get("offset_minutes"), bits=32), resources)
    sequence = _integer(value.get("seq"))
    if sequence < 1:
        raise ValueError("Trace sequence must be positive")
    source = _object(value.get("source"))
    owner = source.get("owner_id")
    if owner is not None and (not isinstance(owner, str) or not owner or any(c < "0" or c > "9" for c in owner)):
        raise ValueError("Trace instance IDs must be decimal strings")
    tick = value.get("client_tick_ms")
    return TraceEvent(sequence, _integer(value.get("captured_at_ms")), _text(value.get("type")),
                      _object(value.get("data")), source, None if tick is None else _integer(tick))


def serialize(record: TraceHeader | TraceEvent) -> bytes:
    value = to_object(record)
    from_object(value, header=isinstance(record, TraceHeader))
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _reject_constant(value):
    raise ValueError("Non-finite trace number requires explicit evidence status")


def parse(line: bytes, *, header: bool) -> TraceHeader | TraceEvent:
    return from_object(json.loads(line.decode("utf-8"), parse_constant=_reject_constant), header=header)


class TraceJsonlReader:
    """Consume bounded file chunks, retaining an incomplete final line for later."""
    def __init__(self):
        self.header: TraceHeader | None = None
        self._pending = bytearray()
        self._last_sequence: int | None = None

    @property
    def pending_bytes(self) -> int:
        return len(self._pending)

    def feed(self, chunk: bytes) -> list[TraceHeader | TraceEvent]:
        records = []
        start = 0
        while start < len(chunk):
            newline = chunk.find(b"\n", start)
            if newline < 0:
                self._pending.extend(chunk[start:])
                break
            self._pending.extend(chunk[start:newline])
            record = parse(bytes(self._pending), header=self.header is None)
            if isinstance(record, TraceHeader):
                self.header = record
                self._last_sequence = 0 if record.volume == 1 else None
            else:
                if self._last_sequence is not None and record.sequence != self._last_sequence + 1:
                    raise ValueError("Trace sequence is not continuous")
                self._last_sequence = record.sequence
            records.append(record)
            self._pending.clear()
            start = newline + 1
        return records


class TraceJsonlWriter:
    """The recording owner holds and closes the persistent binary stream."""
    def __init__(self, destination: BinaryIO, header: TraceHeader):
        self._destination = destination
        self._last_sequence = 0 if header.volume == 1 else None
        destination.write(serialize(header))

    def write(self, event: TraceEvent) -> None:
        if self._last_sequence is not None and event.sequence != self._last_sequence + 1:
            raise ValueError("Trace sequence is not continuous")
        self._destination.write(serialize(event))
        self._last_sequence = event.sequence

    def flush(self) -> None:
        self._destination.flush()
