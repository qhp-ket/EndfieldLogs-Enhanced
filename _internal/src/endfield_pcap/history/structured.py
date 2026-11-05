"""JSONL history indexes event ranges; selected analysis consumes the same events."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from parser_core.battle_splitter.events import split_event_battles
from parser_core.realtime.events import EventBattleParser, LiveEventBatch
from parser_core.trace_volumes import read_events, resolve_volumes

from endfield_pcap.analysis.live.publisher import _transport_copy
from endfield_pcap.history.importer import TraceCombatRecord


def chain_signature(chain):
    return [dict(path=str(volume.path), signature=list(volume.signature)) for volume in chain.volumes]


def trace_source_signature(path):
    """Include appended/renamed/missing sibling volumes in cache invalidation."""
    if path.suffix.lower() != '.jsonl':
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size
    chain = resolve_volumes(path)
    return [chain_signature(chain), list(chain.issues)]


def load_structured_records(path):
    chain = resolve_volumes(path)
    # One logical recording has the same row identity whichever volume was selected.
    path = chain.volumes[0].path
    header = chain.volumes[0].header
    bounds = split_event_battles(read_events(chain), timezone_offset_minutes=header.timezone_offset_minutes)
    zone = timezone(timedelta(minutes=header.timezone_offset_minutes))
    signature = (path.stat().st_mtime_ns, path.stat().st_size)
    sources = chain_signature(chain)
    records = []
    for segment in bounds:
        stamp = datetime.fromtimestamp(segment['first_hit_captured_at_ms'] / 1000, zone)
        records.append(TraceCombatRecord(file_path=path, record_index=segment['battle_index'],
            started_at_ms=segment['first_hit_captured_at_ms'],
            label=f"trace · {stamp:%Y-%m-%d %H:%M:%S} · {path.name} #{segment['battle_index']}",
            source_start_line=segment['start_line_index'], source_end_line=segment['end_line_index'],
            analysis_loaded=False, source_signature=signature, source_volumes=deepcopy(sources),
            last_hit_hint=segment['last_hit_hint'], reference_date=stamp.date().isoformat()))
    return records


def structured_record_snapshot(record):
    chain = resolve_volumes(record.file_path)
    if chain_signature(chain) != record.source_volumes or not chain.complete:
        raise ValueError('原始 trace 分卷已变化或不完整，请刷新记录后重新加载')
    if not record.snapshot:
        header = chain.volumes[0].header
        # The reader validates the complete chain, but only the selected range enters analysis.
        selected = tuple(event for index, event in enumerate(read_events(chain))
                         if record.source_start_line <= index < record.source_end_line)
        if not selected:
            raise ValueError('所选记录没有可供分析的事件')
        zone = timezone(timedelta(minutes=header.timezone_offset_minutes))
        reference = datetime.fromtimestamp(selected[0].captured_at_ms / 1000, zone).date()
        parser = EventBattleParser(reference_date=reference,
            timezone_offset_minutes=header.timezone_offset_minutes, file_name=record.file_path.name,
            last_hit_hint=record.last_hit_hint)
        snapshot = _transport_copy(parser.snapshot_events(LiveEventBatch(0, 1, 0, selected)))
        if not snapshot or not snapshot.get('battle', {}).get('total_damage'):
            raise ValueError('所选记录没有可供分析的伤害事件')
        record.snapshot = snapshot
    return deepcopy(record.snapshot)
