"""Replay one indexed raw-log range through TraceBridge and canonical analysis.

The history list owns the event boundaries. This adapter neither recalculates
damage nor introduces battle segmentation or synthetic timer evidence.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from endfield_pcap.history.records import CombatRecord
from endfield_pcap.analysis.live.publisher import _new_live_parser, _transport_copy
from endfield_pcap.trace.bridge import TraceBridge


def load_record_snapshot(record: CombatRecord) -> dict:
    from endfield_pcap.history.importer import TraceCombatRecord
    from endfield_pcap.history.importer import trace_record_snapshot
    if isinstance(record, TraceCombatRecord):
        return trace_record_snapshot(record)
    if record.source_end_line <= record.source_start_line:
        raise ValueError("历史记录没有有效的来源范围，请刷新记录")
    # Skill/entity mappings and official timer start can precede the list's
    # battle-state event. Let the live parser select the active prefix context;
    # analyze the bounded text with the canonical overlay batch entry point.
    parser = _new_live_parser()
    from parser_core.live import _preserved_context_lines
    from parser_core.unified import parse_overlay_battle_snapshot_text

    context: list[str] = []
    selected: list[str] = []
    bridge = TraceBridge(write_enabled=False, line_sink=parser.feed_line)
    with record.file_path.open(encoding="utf-8") as stream:
        for index, raw_line in enumerate(stream):
            if index >= record.source_end_line:
                break
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if index == record.source_start_line:
                # Do not carry prefix hits or a previous battle's elapsed
                # watermark into the selection. An active official start is
                # necessary evidence and must survive this switch.
                context = list(parser._lines) if parser._official_timer_active else _preserved_context_lines(parser._lines)
                context = [line for line in context if not re.search(r"\bHP_V2\s+#\d+\b", line)]
                bridge.line_sink = selected.append
            bridge.handle_event(event)
    bridge.end_capture_session()
    snapshot = parse_overlay_battle_snapshot_text("".join(context + selected), file_name=record.file_path.name,
        reference_date=datetime.fromtimestamp(record.started_at_ms / 1000).date())
    if not snapshot or not snapshot.get("battle", {}).get("total_damage"):
        raise ValueError("所选记录没有可供 canonical parser 分析的伤害行")
    return _transport_copy(snapshot)
