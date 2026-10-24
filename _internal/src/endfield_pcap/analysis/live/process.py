"""An isolated canonical parser; capture and Qt never compete for its GIL."""
from __future__ import annotations
import multiprocessing
import gc
import queue
import threading
import time


def _worker(connection, summary=False):
    # This module deliberately imports neither Qt nor the capture service.
    from endfield_pcap.analysis.live.publisher import _new_live_parser
    from endfield_pcap.analysis.live.publisher import _transport_copy
    initial_parser = _new_live_parser(summary=summary)
    from parser_core import battle_log_parser

    # Load the existing official metadata caches before the first battle.
    # Their content and all calculation functions remain unchanged.
    for name in (
        '_load_current_buff_roots', '_load_skill_profiles', '_load_rdps_semantics_registry',
        '_load_classifier_hints', '_load_nonstacking_weapon_ids', '_load_weapon_id_stack_limits',
        '_load_weapon_buff_stack_limits', '_load_packet_numeric_buff_map',
        '_load_packet_canonical_buff_map', '_load_mechanism_registry_by_buff_id',
        '_load_weapon_catalog', '_load_character_base_stat_catalog', '_load_suit_catalog',
        '_load_weapon_refine_catalog', '_load_equip_item_catalog', '_load_packet_numeric_skill_map',
        '_load_num_id_str_skill_map', '_load_num_id_str_buff_map', '_load_canonical_skill_display_names',
        '_load_local_skill_semantic_entries', '_load_damage_zone_config', '_load_local_buff_semantic_entries',
        '_load_equip_suit_allowed_buffs', '_load_character_names', '_load_enemy_names',
        '_load_dungeon_by_id', '_load_skill_name_prefixes', '_load_skill_exact_names',
        '_load_character_profiles', '_load_official_skill_damage_catalog',
        '_load_official_skill_damage_prefixes', '_load_buff_manifest_names',
        '_load_contract_tag_texts', '_load_contract_tag_catalog',
    ):
        getattr(battle_log_parser, name)()
    # Metadata contains a large, process-lifetime graph of dictionaries/lists.
    # It is read-only during analysis. Keep cyclic GC from repeatedly walking
    # that graph while transient projection records are created and released.
    gc.collect()
    gc.freeze()
    state_lock = threading.Lock()
    ready = threading.Event()
    state = dict(parser=initial_parser, generation=-1, request=None, stopped=False)

    def read_lines():
        try:
            while True:
                command = connection.recv()
                kind = command[0]
                if kind == "stop":
                    break
                generation = command[1]
                with state_lock:
                    if generation != state["generation"]:
                        state.update(parser=_new_live_parser(summary=summary), generation=generation)
                    parser = state["parser"]
                if kind == "lines":
                    parser.feed_lines(command[2])
                elif kind == "calculate":
                    with state_lock:
                        state["request"] = (generation, parser, command[2])
                    ready.set()
        except (EOFError, OSError):
            pass
        finally:
            with state_lock:
                state["stopped"] = True
            ready.set()

    reader = threading.Thread(target=read_lines, name="canonical-trace-reader", daemon=True)
    reader.start()
    try:
        while True:
            ready.wait()
            with state_lock:
                ready.clear()
                if state["stopped"]:
                    return
                request, state["request"] = state["request"], None
            if request is None:
                continue
            generation, parser, requested = request
            try:
                started = time.perf_counter()
                before = parser.incremental_diagnostics.get('report_builds', 0)
                before_clock = parser.incremental_diagnostics.get('clock_projections', 0)
                report = parser.snapshot()
                parsed = time.perf_counter()
                diagnostics = parser.incremental_diagnostics
                performed = diagnostics.get('report_builds', 0) != before
                clock_update = diagnostics.get('clock_projections', 0) != before_clock
                if not performed:
                    diagnostics = {**diagnostics, 'phases': diagnostics.get('phases', {}) if clock_update else {},
                                   'allocated_hits': 0, 'reused_hits': 0}
                snapshot = _transport_copy(report)
                response = (generation, snapshot, None, {
                    "queue_ms": round((started - requested) * 1000, 1),
                    "core_ms": round((parsed - started) * 1000, 1),
                    "transport_ms": round((time.perf_counter() - parsed) * 1000, 1),
                    "finished_at": time.perf_counter(),
                    "source_revision": parser.source_revision,
                    "analysis_performed": performed,
                    "update_kind": 'semantic' if performed else 'clock' if clock_update else 'cached',
                    "diagnostics": diagnostics,
                })
            except Exception as exc:
                response = (generation, None, {"type": type(exc).__name__, "message": str(exc)}, {})
            connection.send(response)
    finally:
        connection.close()


class SnapshotProcess:
    """One reader and one calculator, with ordered nonblocking input delivery.

    The reader feeds new lines even while snapshot() runs, as the official
    overlay's trace reader does. The parent accepts results by generation.
    IPC can block only the sender thread, never the capture event loop.
    """

    def __init__(self, *, summary=False):
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe()
        self.process = context.Process(target=_worker, args=(child, summary), name="endfield-summary" if summary else "endfield-canonical-analysis", daemon=True)
        self.process.start()
        child.close()
        self.commands = queue.Queue()
        self.closed = False
        self.error = None
        self.last_metrics = {}
        self.sender = threading.Thread(target=self._send, name="canonical-trace-sender", daemon=True)
        self.sender.start()

    def _send(self):
        pending = None
        try:
            while True:
                command = pending if pending is not None else self.commands.get()
                pending = None
                if command[0] == "lines":
                    # Coalesce only adjacent lines of the same generation.
                    # Never reorder a reset boundary or a calculate request.
                    lines = list(command[2])
                    while len(lines) < 4096:
                        try:
                            next_command = self.commands.get_nowait()
                        except queue.Empty:
                            break
                        if next_command[:2] != command[:2]:
                            pending = next_command
                            break
                        lines.extend(next_command[2])
                    command = ("lines", command[1], lines)
                self.connection.send(command)
                if command[0] == "stop":
                    return
        except (OSError, EOFError, BrokenPipeError) as exc:
            # A failed Connection.send traceback can retain the pickler's
            # exported BytesIO buffer. Keep the diagnostic, not those frames.
            self.error = f"{type(exc).__name__}: {exc}"

    def feed_line(self, generation, line):
        self.commands.put(("lines", generation, [line]))

    def calculate(self, generation):
        if self.closed:
            raise RuntimeError("analysis worker is closed")
        if self.error:
            raise RuntimeError(f"analysis worker input failed: {self.error}")
        if not self.process.is_alive():
            raise RuntimeError(f"analysis worker exited ({self.process.exitcode})")
        self.commands.put(("calculate", generation, time.perf_counter()))
        while not self.connection.poll(0.1):
            if self.closed or not self.process.is_alive():
                raise RuntimeError(f"analysis worker exited ({self.process.exitcode})")
            if self.error:
                raise RuntimeError(f"analysis worker input failed: {self.error}")
        received_generation, snapshot, error, self.last_metrics = self.connection.recv()
        finished_at = self.last_metrics.pop("finished_at", None)
        if finished_at is not None:
            self.last_metrics["ipc_ms"] = round((time.perf_counter() - finished_at) * 1000, 1)
        if received_generation != generation:
            raise RuntimeError("analysis worker returned an unexpected generation")
        if error:
            raise RuntimeError(f"{error['type']}: {error['message']}")
        return snapshot

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.commands.put(("stop",))
        self.process.join(2)
        if self.process.is_alive():
            # Only this publisher's private worker can be terminated here.
            self.process.terminate()
            self.process.join(2)
        self.connection.close()
        self.sender.join(1)
