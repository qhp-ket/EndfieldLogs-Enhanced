from __future__ import annotations
import copy
from dataclasses import replace
from typing import Callable
from uuid import uuid4
from endfield_pcap.models import OverlayEntry, OverlayGeometry
from endfield_pcap.overlays.templates import template_for
from endfield_pcap.overlays.config import OverlayWindowConfig, _window_defaults
from endfield_pcap.overlays.window import OverlayWindow


class OverlayManager:
    def __init__(
        self, ws_port: int, on_entry_changed: Callable[[OverlayEntry], None] | None = None,
        *, use_in_process_snapshots: bool = False, on_full_requirement=None,
        on_analysis_requirement=None, visible=True, ws_browser_token='',
    ) -> None:
        self.ws_port = ws_port
        self.ws_browser_token = ws_browser_token
        self.on_full_requirement = on_full_requirement
        self.on_analysis_requirement = on_analysis_requirement
        self.visible = bool(visible)
        self.on_entry_changed = on_entry_changed
        self._entries: dict[str, OverlayEntry] = {}
        self._windows: dict[str, OverlayWindow] = {}
        self._use_in_process_snapshots = use_in_process_snapshots
        self._analysis_snapshot: dict[str, object] | None = None
        self._combo_snapshot: dict[str, object] | None = None
        self._buff_snapshot: dict[str, object] | None = None
        self._live_snapshot: dict[str, object] | None = None
        self._history_mode = False
        self._presentation_stream = str(uuid4())
        self._presentation_sequence = 0
        self._retired_live_streams: set[str] = set()
        self._live_summary = None
        self._summary_presentation = None
        self._retired_summary_streams = set()

    def apply_analysis_summary(self, message, *, take_ownership=False):
        if not isinstance(message, dict) or message.get('type') != 'analysis_summary':
            return
        stream = message.get('stream_id')
        previous = self._live_summary
        if stream in self._retired_summary_streams:
            return
        if previous and stream == previous.get('stream_id') and message.get('sequence', -1) <= previous.get('sequence', -1):
            return
        if previous and stream != previous.get('stream_id'):
            self._retired_summary_streams.add(previous['stream_id'])
        self._live_summary = message if take_ownership else copy.deepcopy(message)
        if not self._history_mode:
            self._present_summary()

    def _present_summary(self):
        if self._live_summary is None:
            return
        self._presentation_sequence += 1
        self._summary_presentation = {**self._live_summary,
            'stream_id': self._presentation_stream, 'sequence': self._presentation_sequence,
            'source': {'mode': 'live'}}
        for window in self._windows.values():
            window.apply_analysis_summary(self._summary_presentation)

    def apply_analysis_snapshot(self, message: object, *, take_ownership: bool = False) -> None:
        """Accept canonical state on Qt's thread.

        The service has already isolated its observer payload. Its single-use
        queue can transfer that copy; public callers still receive isolation.
        """
        if not isinstance(message, dict) or message.get("type") != "analysis_snapshot":
            return
        previous = self._live_snapshot
        stream = message.get("stream_id")
        if stream in self._retired_live_streams:
            return
        if previous and stream == previous.get("stream_id") and message.get("sequence", -1) <= previous.get("sequence", -1):
            return
        if previous and stream != previous.get("stream_id"):
            self._retired_live_streams.add(previous["stream_id"])
        self._live_snapshot = message if take_ownership else copy.deepcopy(message)
        if not self._history_mode:
            self._present(self._live_snapshot.get("snapshot"), {"mode": "live"}, error=self._live_snapshot.get("error"), origin=self._live_snapshot)

    def _present(self, snapshot, source: dict, *, error=None, origin=None) -> None:
        self._presentation_sequence += 1
        self._analysis_snapshot = {"type": "analysis_snapshot", "schema_version": 1,
            "stream_id": self._presentation_stream, "sequence": self._presentation_sequence,
            "snapshot": snapshot, "source": source}
        if origin:
            self._analysis_snapshot.update({key: origin[key] for key in ('source_generation', 'source_revision') if key in origin})
        if error:
            self._analysis_snapshot["error"] = copy.deepcopy(error)
        for window in self._windows.values():
            if not self._history_mode and self._live_summary is not None and 'analysis_summary' in template_for(window.entry).subscriptions:
                continue
            window.apply_analysis_snapshot(self._analysis_snapshot)

    def show_history(self, snapshot: dict, label: str) -> None:
        self._history_mode = True
        self._present(copy.deepcopy(snapshot), {"mode": "history", "label": label})

    def return_live(self) -> None:
        self._history_mode = False
        message = self._live_snapshot or {}
        self._present(message.get("snapshot"), {"mode": "live"}, error=message.get("error"), origin=message)
        self._present_summary()

    def sync_entries(self, entries: list[OverlayEntry]) -> None:
        current_ids = {entry.id for entry in entries}
        for entry in entries:
            self.apply_entry(entry)
        for entry_id in list(self._entries):
            if entry_id not in current_ids:
                self.remove_entry(entry_id)

    def apply_combo_snapshot(self, message: object) -> None:
        if not isinstance(message, dict) or message.get("type") != "combo_snapshot":
            return
        self._combo_snapshot = copy.deepcopy(message)
        for window in self._windows.values():
            window.apply_combo_snapshot(self._combo_snapshot)

    def apply_buff_snapshot(self, message: object) -> None:
        if not isinstance(message, dict) or message.get("type") != "buff_snapshot":
            return
        self._buff_snapshot = copy.deepcopy(message)
        for window in self._windows.values():
            window.apply_buff_snapshot(self._buff_snapshot)

    def apply_entry(self, entry: OverlayEntry) -> None:
        if entry.source_value == 'combo_skill' or 'combo_snapshot' in template_for(entry).subscriptions:
            self.remove_entry(entry.id)
            return
        self._entries[entry.id] = replace(entry)
        self._notify_full_requirement()
        if entry.enabled:
            window = self._windows.get(entry.id)
            if window is None:
                window = OverlayWindow(
                    OverlayWindowConfig(
                        entry=replace(entry),
                        ws_port=self.ws_port,
                        ws_browser_token=self.ws_browser_token,
                        **_window_defaults(entry),
                        on_geometry_changed=self._handle_geometry_changed,
                        on_closed=self._handle_window_closed,
                        use_in_process_snapshots=self._use_in_process_snapshots,
                        desktop_visible=self.visible and not entry.hidden,
                        hide_on_close=True,
                    )
                )
                self._windows[entry.id] = window
                if self._analysis_snapshot is not None:
                    window.apply_analysis_snapshot(self._analysis_snapshot)
                if not self._history_mode and self._summary_presentation is not None:
                    window.apply_analysis_summary(self._summary_presentation)
                if self._combo_snapshot is not None:
                    window.apply_combo_snapshot(self._combo_snapshot)
                if self._buff_snapshot is not None:
                    window.apply_buff_snapshot(self._buff_snapshot)
                window.show()
            else:
                window.apply_entry(replace(entry))
                window.set_desktop_visible(self.visible and not entry.hidden)
                window.show()

        else:
            self._close_window(entry.id)

    def remove_entry(self, entry_id: str) -> None:
        self._entries.pop(entry_id, None)
        self._notify_full_requirement()
        self._close_window(entry_id)

    def _notify_full_requirement(self):
        subscriptions = {key for row in self._entries.values() if row.enabled
                         for key in template_for(row).subscriptions}
        if self.on_analysis_requirement is not None:
            self.on_analysis_requirement(frozenset(subscriptions))
        if self.on_full_requirement is not None:
            self.on_full_requirement('analysis_snapshot' in subscriptions)

    def set_visible(self, visible):
        self.visible = bool(visible)
        for entry in self._entries.values():
            window = self._windows.get(entry.id)
            if window is not None:
                window.set_desktop_visible(self.visible and not entry.hidden)

    def close_all(self) -> None:
        for entry_id in list(self._windows):
            self._close_window(entry_id)

    def opened_window_count(self) -> int:
        return len(self._windows)

    def visible_window_count(self) -> int:
        return sum(window.desktop_visible for window in self._windows.values())

    def _close_window(self, entry_id: str) -> None:
        window = self._windows.pop(entry_id, None)
        if window is None:
            return
        window.config.on_closed = None
        window.close()

    def _handle_geometry_changed(self, entry_id: str, geometry: OverlayGeometry) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        updated = replace(entry, geometry=geometry)
        self._entries[entry_id] = updated
        if self.on_entry_changed is not None:
            self.on_entry_changed(replace(updated))

    def _handle_window_closed(self, entry_id: str) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        updated = replace(entry, hidden=True)
        self.apply_entry(updated)
        if self.on_entry_changed is not None:
            self.on_entry_changed(replace(updated))
