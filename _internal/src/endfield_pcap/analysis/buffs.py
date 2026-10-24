"""Observed BUFF lifetimes for display only; never used for damage allocation."""
from __future__ import annotations
import json
import math
import re
import time
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from endfield_pcap.runtime.paths import bundle_root


_STAMP = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\.(\d{3})\] (.*)$")
_PAIR = re.compile(r'(\w+)=(?:"([^"]*)"|(\S+))')


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


class BuffDisplayPublisher:
    """Ordered canonical trace observations, with explicitly estimated clocks.

    Repeated START rows update the same instance; they do not restart its clock.
    No fixed slot limit and no guessed durations from arbitrary blackboard keys.
    """

    def __init__(self, *, clock=time.monotonic, data_root: Path | None = None):
        self.clock = clock
        self.data_root = data_root or bundle_root() / "data/akedata/buff/items"
        self.stream_id = str(uuid4())
        self.sequence = -1
        self._last_snapshot = None
        self.reset(new_stream=True)

    @lru_cache(maxsize=4096)
    def _root(self, buff_id):
        if not re.fullmatch(r"[a-zA-Z0-9_]+", buff_id):
            return {}
        try:
            value = json.loads((self.data_root / f"{buff_id}.json").read_text(encoding="utf-8-sig"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def reset(self, *, new_stream=False):
        if new_stream:
            self.stream_id = str(uuid4())
            self.sequence = -1
        self.buffs = {}
        self._watermark = None
        self._anchor = self.clock()
        self._last_snapshot = None

    def feed_line(self, line):
        match = _STAMP.match(line.strip())
        if not match:
            return
        h, m, s, ms = map(int, match.groups()[:4])
        stamp = ((h * 60 + m) * 60 + s) * 1000 + ms
        if self._watermark is not None:
            # Trace time is time-of-day; preserve order through midnight.
            stamp += (self._watermark // 86400000) * 86400000
            if stamp < self._watermark - 43200000:
                stamp += 86400000
        self._watermark = max(stamp, self._watermark if self._watermark is not None else stamp)
        self._anchor = self.clock()
        body = match[5]
        if re.search(r"\bGAME_TIMER_RESET\b", body):
            self.reset()
            return
        pairs = {key: quoted or plain for key, quoted, plain in _PAIR.findall(body)}
        uid = pairs.get("uid")
        if body.startswith("BUFF_START ") and uid:
            row = self.buffs.get(uid)
            if row is None:
                row = dict(uid=uid, start_ms=stamp, bb={}, enabled=None)
                self.buffs[uid] = row
            row.update(buff_id=pairs.get("id", "unknown_buff"), owner=pairs.get("owner", "?"), source=pairs.get("src", "?"))
            duration = _number(pairs.get("dur"))
            passed = _number(pairs.get("passed"))
            if duration is not None and duration >= 0:
                row["duration_ms"] = round(duration * 1000)
                row["duration_source"] = "trace_duration"
                if passed is not None and passed >= 0:
                    row["start_ms"] = stamp - round(passed * 1000)
        elif body.startswith("BUFF_END ") and uid:
            self.buffs.pop(uid, None)
        elif body.startswith("BUFF_ENABLE "):
            try:
                observation = json.loads(body.partition(" ")[2])
                row = self.buffs.get(str(observation.get("buffUid")))
                if row is not None and type(observation.get("enabled")) is bool:
                    row["enabled"] = observation["enabled"]
            except (ValueError, AttributeError):
                pass
        else:
            bb = re.match(r"BB\[(\d+)\]: (.*)", body)
            if bb and bb[1] in self.buffs:
                self.buffs[bb[1]]["bb"].update({key: _number(quoted or plain) for key, quoted, plain in _PAIR.findall(bb[2])})

    def current_message(self):
        now = self._watermark or 0
        if self._watermark is not None:
            now += max(0, self.clock() - self._anchor) * 1000
        rows = []
        for row in self.buffs.values():
            root = self._root(row["buff_id"])
            duration = row.get("duration_ms")
            source = row.get("duration_source", "unknown")
            mode = root.get("lifeType")
            if duration is None and mode == "Limited":
                config = root.get("duration") or {}
                if not isinstance(config, dict):
                    config = {}
                seconds = _number(row["bb"].get(config.get("blackboardKey"))) if config.get("useBlackboardKey") is True else _number(config.get("value")) if config.get("useBlackboardKey") is False else None
                if seconds is not None and seconds >= 0:
                    duration = round(seconds * 1000)
                    source = "official_duration_blackboard" if config["useBlackboardKey"] else "official_duration_constant"
            remaining = max(0, round(duration - (now - row["start_ms"]), -1)) if duration is not None else None
            rows.append({key: row[key] for key in ("uid", "buff_id", "owner", "source", "enabled")} | dict(
                duration_ms=duration, remaining_ms=remaining, duration_source=source,
                status="disabled" if row["enabled"] is False else "expired_estimate" if remaining == 0 else "timed" if duration is not None else "indefinite" if mode == "Infinity" else "unknown"))
        snapshot = dict(buffs=rows, timing="observed_trace_plus_wall_clock_estimate")
        if snapshot != self._last_snapshot:
            self.sequence += 1
            self._last_snapshot = deepcopy(snapshot)
        return dict(type="buff_snapshot", schema_version=1, stream_id=self.stream_id,
                    sequence=self.sequence, snapshot=deepcopy(snapshot))
