"""Coalesced, replace-only transport for the canonical live parser."""
from __future__ import annotations
import asyncio
import logging
import re
import sys
import time
from copy import deepcopy
from math import isfinite
from typing import Any, Callable
from uuid import uuid4
from endfield_pcap.runtime.paths import bundle_root


LOGGER = logging.getLogger(__name__)
_RESET_RE = re.compile(r"\bGAME_TIMER_RESET\b")
_JS_SAFE_INTEGER = (1 << 53) - 1


def _new_live_parser(*, summary=False):
    # Source launches use the same bundled parser as rdps_audit. Do not search
    # upstream checkouts or install a second parser copy.
    local_package = bundle_root() / "packages" / "parser_core"
    if local_package.is_dir() and str(local_package) not in sys.path:
        sys.path.insert(0, str(local_package))
    from parser_core.live import LiveOverlayBattleParser

    return LiveOverlayBattleParser(align_to_data_watermark=True, summary=summary)


def _transport_copy(value: Any) -> Any:
    # Most leaves are strings/numbers; dispatch them before container checks.
    kind = type(value)
    if value is None or kind is str or kind is bool:
        return value
    if kind is int:
        return str(value) if abs(value) > _JS_SAFE_INTEGER else value
    if kind is float:
        return value if isfinite(value) else None
    if isinstance(value, dict):
        return {key: _transport_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_transport_copy(item) for item in value]
    if isinstance(value, float) and not isfinite(value):
        return None
    return deepcopy(value)


class SnapshotPublisher:
    """Event-loop-owned inbox with one ordered parser worker at a time.

    ``feed_line`` never parses. ``publish_pending`` coalesces all queued lines
    into one worker call. A reset replaces the parser generation and publishes
    a null frame before any following battle, including when a worker is busy.
    """

    def __init__(self, *, parser_factory: Callable[[], Any] | None = None, use_process: bool = False,
                 summary: bool = False, minimum_interval: float = 0.0) -> None:
        self.summary = summary
        self.minimum_interval = minimum_interval
        self._last_started = None
        self._use_process = use_process
        self._worker = None
        self._parser_factory = parser_factory or (lambda: _new_live_parser(summary=summary))
        self._parser = None if use_process else self._parser_factory()
        self._generation = 0
        self._pending_lines: list[str] = []
        self._trace_lines: list[str] = []
        self._revision = 0
        self._publish_lock = asyncio.Lock()
        self._changed = asyncio.Event()
        self._clear_pending = True
        self._requested = False
        self.last_analysis_ms = 0.0
        self.last_worker_metrics: dict[str, float] = {}
        self._message = self._envelope(str(uuid4()), 0, None)

    def _envelope(self, stream_id: str, sequence: int, snapshot: Any) -> dict[str, Any]:
        return {"type": "analysis_summary" if self.summary else "analysis_snapshot", "schema_version": 1,
                "stream_id": stream_id, "sequence": sequence, "snapshot": snapshot,
                "source_generation": self._generation, "source_revision": self._revision}

    def current_message(self, *, copy_result=True) -> dict[str, Any]:
        return deepcopy(self._message) if copy_result else self._message

    def is_current(self, message: dict) -> bool:
        return (message.get("stream_id"), message.get("sequence")) == (self._message["stream_id"], self._message["sequence"])

    def start(self) -> None:
        if self._use_process and self._worker is None:
            from endfield_pcap.analysis.live.process import SnapshotProcess
            self._worker = SnapshotProcess(summary=True) if self.summary else SnapshotProcess()

    async def close(self) -> None:
        worker, self._worker = self._worker, None
        if worker is not None:
            await asyncio.to_thread(worker.close)

    def reset(self, *, new_stream: bool = False) -> None:
        self._generation += 1
        self._pending_lines.clear()
        self._trace_lines.clear()
        self._revision = 0
        self._parser = None if self._use_process else self._parser_factory()
        stream_id = str(uuid4()) if new_stream else self._message["stream_id"]
        sequence = 0 if new_stream else self._message["sequence"] + 1
        self._message = self._envelope(stream_id, sequence, None)
        self._clear_pending = True
        self._changed.set()

    def feed_line(self, line: str) -> None:
        if _RESET_RE.search(line):
            self.reset()
            return
        self._pending_lines.append(line)
        self._trace_lines.append(line)
        self._revision += 1
        self._changed.set()
        if self._worker is not None:
            self._worker.feed_line(self._generation, line)

    def request_current(self):
        self._requested = True
        self._changed.set()

    async def wait_for_pending(self) -> None:
        """Sleep while clean; feed/reset wakes the sole service scheduler."""
        while not self._clear_pending and not self._pending_lines and not self._requested:
            self._changed.clear()
            await self._changed.wait()

    @staticmethod
    def _calculate(parser: Any, lines: list[str]) -> Any:
        parser.feed_lines(lines)
        return _transport_copy(parser.snapshot())

    async def publish_pending(self, *, copy_result: bool = True) -> dict[str, Any] | None:
        async with self._publish_lock:
            if self._clear_pending:
                self._clear_pending = False
                return self.current_message()
            if self._use_process and self._worker is None:
                self.start()
                for line in self._trace_lines:
                    self._worker.feed_line(self._generation, line)
            if not self._pending_lines and not self._requested:
                return None
            if self._last_started is not None:
                remaining = self.minimum_interval-(time.perf_counter()-self._last_started)
                if remaining > 0:
                    await asyncio.sleep(remaining)
            # Reset can arrive while throttling. Its clear frame must precede
            # every result from the new generation, even if new input is ready.
            if self._clear_pending:
                self._clear_pending = False
                return self.current_message()
            self._requested = False
            lines, self._pending_lines = self._pending_lines, []
            generation, parser = self._generation, self._parser
            revision = self._revision
            try:
                started = time.perf_counter()
                self._last_started = started
                snapshot = await asyncio.to_thread(self._worker.calculate, generation) if self._use_process else await asyncio.to_thread(self._calculate, parser, lines)
                self.last_analysis_ms = (time.perf_counter() - started) * 1000
                if self._use_process:
                    self.last_worker_metrics = dict(self._worker.last_metrics)
                    revision = self.last_worker_metrics.get('source_revision', revision)
                else:
                    revision = getattr(parser, 'source_revision', revision)
                    self.last_worker_metrics = getattr(parser, 'incremental_diagnostics', {})
            except Exception as exc:
                LOGGER.exception("live snapshot analysis failed; clearing current snapshot")
                if generation != self._generation:
                    return None
                if self._use_process:
                    await self.close()
                    # A worker crash is not a battle reset. Restore the entire
                    # retained canonical input in a fresh private process.
                    self._pending_lines = list(self._trace_lines)
                    self._message = self._envelope(self._message['stream_id'], self._message['sequence']+1, None)
                else:
                    self.reset()
                self._clear_pending = False
                self._message["error"] = {"type": type(exc).__name__, "message": str(exc)}
                return self.current_message()
            if generation != self._generation:
                return None
            # A completed semantic revision can confirm the same numbers with
            # newer evidence. Publish its source watermark as well. Cached
            # reads (including ended heartbeats) retain the prior watermark
            # and remain silent; empty startup does not emit repeated clears.
            if (snapshot == self._message["snapshot"] and "error" not in self._message
                    and (snapshot is None or revision == self._message.get('source_revision'))):
                return None
            self._message = self._envelope(self._message["stream_id"],
                                           self._message["sequence"] + 1, snapshot)
            self._message['source_revision'] = revision
            # The service borrows this immutable result, then isolates observer
            # delivery itself. Public callers retain the default owned copy.
            return self.current_message() if copy_result else self._message
