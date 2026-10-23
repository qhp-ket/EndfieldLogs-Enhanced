"""Index trace battles without computing snapshots; analyze a selection on demand."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import sys

from .record_parser import CombatRecord, CombatPlayerSummary
from .runtime_paths import bundle_root
from .snapshot_publisher import _transport_copy


@dataclass(slots=True)
class TraceCombatRecord(CombatRecord):
    snapshot: dict = field(default_factory=dict, repr=False)
    source_signature: tuple[int, int] = (0, 0)
    source_byte_start: int = 0
    source_byte_end: int = 0
    last_hit_hint: str = ''
    reference_date: str = ''


def load_trace_records(path: Path) -> list[TraceCombatRecord]:
    path = path.resolve()
    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig')
    # Importing the splitter must not initialize or run canonical analysis.
    parser_package = bundle_root() / 'packages/parser_core'
    if str(parser_package) not in sys.path:
        sys.path.insert(0, str(parser_package))
    package = bundle_root() / 'packages/uploader_core'
    if str(package) not in sys.path:
        sys.path.insert(0, str(package))
    from uploader_core.battle_payload_builder import _split_trace_into_battles

    match = re.search(r'(20\d{6})', path.name)
    try:
        reference = datetime.strptime(match[1], '%Y%m%d').date() if match else datetime.fromtimestamp(path.stat().st_mtime).date()
    except ValueError:
        reference = datetime.fromtimestamp(path.stat().st_mtime).date()
    offsets = [3 if raw.startswith(b'\xef\xbb\xbf') else 0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line.encode('utf-8')))
    records = []
    for segment in _split_trace_into_battles(text):
        stamp = datetime.combine(reference, datetime.strptime(segment['first_hit_hint'], '%H-%M-%S-%f').time())
        start = int(segment['start_line_index'])
        end = start + len(segment['content'].splitlines())
        records.append(TraceCombatRecord(file_path=path, record_index=int(segment['battle_index']),
            started_at_ms=int(stamp.timestamp()*1000),
            label=f"trace · {stamp:%Y-%m-%d %H:%M:%S} · {path.name} #{segment['battle_index']}",
            source_start_line=start, source_end_line=end, analysis_loaded=False,
            source_signature=signature, source_byte_start=offsets[start], source_byte_end=offsets[end],
            last_hit_hint=segment['last_hit_hint'], reference_date=reference.isoformat()))
    if (path.stat().st_mtime_ns, path.stat().st_size) != signature:
        raise ValueError('日志在建立索引时发生变化，请刷新记录后重试')
    if not records:
        raise ValueError('未在 trace 日志中识别到可用战斗')
    return records


def trace_record_snapshot(record: TraceCombatRecord) -> dict:
    stat = record.file_path.stat()
    if (stat.st_mtime_ns, stat.st_size) != tuple(record.source_signature):
        raise ValueError('原始 trace 日志已变化，请刷新记录后重新加载')
    if not record.snapshot:
        from .snapshot_publisher import _new_live_parser
        _new_live_parser()
        from parser_core.unified import parse_overlay_battle_snapshot_text
        with record.file_path.open('rb') as stream:
            stream.seek(record.source_byte_start)
            content = stream.read(record.source_byte_end - record.source_byte_start).decode('utf-8').strip()
        stat = record.file_path.stat()
        if (stat.st_mtime_ns, stat.st_size) != tuple(record.source_signature):
            raise ValueError('原始 trace 日志已变化，请刷新记录后重新加载')
        snapshot = _transport_copy(parse_overlay_battle_snapshot_text(content, file_name=record.file_path.name,
            last_hit_hint=record.last_hit_hint, reference_date=datetime.fromisoformat(record.reference_date).date()))
        if not snapshot or not snapshot.get('battle', {}).get('total_damage'):
            raise ValueError('所选记录没有可供 canonical parser 分析的伤害行')
        record.snapshot = snapshot
    return deepcopy(record.snapshot)


def apply_snapshot_summary(record: CombatRecord, snapshot: dict) -> None:
    """Update the selected row only, after its analysis has completed."""
    battle = snapshot.get('battle') or {}
    record.total_damage = float(battle.get('total_damage') or 0)
    record.duration_ms = int(battle.get('duration_ms') or 0)
    record.players = [CombatPlayerSummary(battle_inst_id=index,
        display_name=str(row.get('character_name') or row['character_key']),
        templateid=row['character_key'], squad_index=index, total_damage=float(row.get('total_damage') or 0),
        max_damage=float(row.get('max_hit') or 0), crit_count=int(row.get('crit_hits') or 0),
        hit_count=int(row.get('hit_count') or 0)) for index, row in enumerate(snapshot.get('participants') or [])]
    record.analysis_loaded = True
