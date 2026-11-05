"""Replay one indexed raw-log range through TraceBridge and canonical analysis.

The history list owns the event boundaries. This adapter neither recalculates
damage nor introduces battle segmentation or synthetic timer evidence.
"""
from __future__ import annotations
import json
import hashlib
from itertools import islice
from datetime import datetime, timedelta, timezone
from endfield_pcap.history.records import CombatRecord
from endfield_pcap.analysis.live.publisher import _transport_copy
from endfield_pcap.trace.bridge import TraceBridge


def load_record_snapshot(record: CombatRecord) -> dict:
    from endfield_pcap.history.importer import TraceCombatRecord
    from endfield_pcap.history.importer import trace_record_snapshot
    if isinstance(record, TraceCombatRecord):
        return trace_record_snapshot(record)
    events, offset = session_record_events(record)
    from parser_core.realtime.events import EventBattleParser, LiveEventBatch
    if not events:
        raise ValueError('所选记录没有可供分析的事件')
    # Time-only replay unfolds midnight relative to its first event, not first hit.
    stamp = datetime.fromtimestamp(events[0].captured_at_ms / 1000, timezone(timedelta(minutes=offset)))
    analysis = EventBattleParser(reference_date=stamp.date(), timezone_offset_minutes=offset,
                                file_name=record.file_path.name)
    snapshot = analysis.snapshot_events(LiveEventBatch(0, 1, 0, events))
    if not snapshot or not snapshot.get('battle', {}).get('total_damage'):
        raise ValueError('所选记录没有可供分析的伤害事件')
    return _transport_copy(snapshot)


def session_record_events(record):
    """Select original evidence plus required prefix context, never prefix hits."""
    if record.source_end_line <= record.source_start_line:
        raise ValueError("历史记录没有有效的来源范围，请刷新记录")
    from endfield_pcap.history.session_volumes import resolve_sessions, read_lines, chain_signature, retains_sources
    try:
        chain = resolve_sessions(record.file_path)
    except FileNotFoundError as exc:
        if record.session_volumes:
            raise ValueError('原始 session 分卷已变化或不完整，请刷新记录后重新加载') from exc
        raise
    if record.session_volumes and (not chain.complete or
            (not retains_sources(chain, record.session_volumes) if record.source_prefix_sha256
             else chain_signature(chain) != record.session_volumes)):
        raise ValueError('原始 session 分卷已变化或不完整，请刷新记录后重新加载')
    # Old sessions preserve local interpretation; new volumes record their zone.
    stamp = datetime.fromtimestamp(record.started_at_ms / 1000).astimezone()
    offset = (chain.volumes[0].header['timezone_offset_minutes'] if chain.volumes[0].header
              else int(stamp.utcoffset().total_seconds() // 60))
    from parser_core.realtime.live_events import LiveEventOverlayBattleParser
    parser = LiveEventOverlayBattleParser(timezone_offset_minutes=offset, align_to_data_watermark=True)

    context, selected = (), []
    sink = parser.feed_event
    def receive(event):
        sink(event)
    bridge = TraceBridge(write_enabled=False, event_sink=receive)
    prefix_hash = hashlib.sha256()
    count = 0
    for index, raw_line in enumerate(islice(read_lines(chain, allow_append=bool(record.source_prefix_sha256)), record.source_end_line)):
        prefix_hash.update(raw_line.encode('utf8') + b'\n')
        count += 1
        if index == record.source_start_line:
            # Do not carry prefix hits or a previous battle's elapsed
            # watermark into the selection. An active official start is
            # necessary evidence and must survive this switch.
            context = parser.history_event_context()
            sink = selected.append
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        bridge.handle_event(event)
    bridge.end_capture_session()
    if count != record.source_end_line or (record.source_prefix_sha256 and prefix_hash.hexdigest() != record.source_prefix_sha256):
        raise ValueError('所选战斗的原始 session 内容已变化，请刷新记录后重新加载')
    return (*context, *selected), offset
