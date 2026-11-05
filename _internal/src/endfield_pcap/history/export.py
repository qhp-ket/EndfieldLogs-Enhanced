"""Export a stable copy of a canonical trace for the official uploader."""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path
from uploader_core.log_integrity import (
    RAW_LOG_PROOF_BEGIN_PREFIX,
    RAW_LOG_PROOF_END,
    build_raw_log_proof,
    load_raw_log_integrity,
)


def export_trace_log(source: Path, destination: Path) -> dict:
    """Preserve raw trace text; append the distribution's local export proof.

    This is a snapshot export, not an attestation of server authenticity. Never
    add a proof to the growing capture file or re-seal a failed existing proof.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("请另存导出文件，不能覆盖正在写入的原始 trace")
    meta = {"exporter": "endfield-pcap-gui", "source_file_name": source.name,
            "scope": "full_trace_snapshot"}
    session_chain = None
    if source.suffix.lower() == '.ndjson':
        from endfield_pcap.history.session_volumes import resolve_sessions, read_lines, associated_trace
        session_chain = resolve_sessions(source)
        # Verify complete business-line boundaries and volume offsets before export.
        for _ in read_lines(session_chain):
            pass
        chain = associated_trace(session_chain)
        if chain is None:
            raise ValueError('旧 session_*.ndjson 没有关联 trace，请先导入原始 trace 日志')
        if any(volume.path == destination.resolve() for volume in session_chain.volumes):
            raise ValueError('请另存导出文件，不能覆盖原始 session 分卷')
        meta.update(source_session_recording_id=session_chain.volumes[0].header['recording_id'],
                    source_session_volumes=[volume.path.name for volume in session_chain.volumes])
    if source.suffix.lower() == '.jsonl' or session_chain is not None:
        from parser_core.trace_volumes import resolve_volumes
        from endfield_pcap.trace.legacy import legacy_text
        if session_chain is None:
            chain = resolve_volumes(source)
        if any(volume.path == destination.resolve() for volume in chain.volumes):
            raise ValueError("请另存导出文件，不能覆盖原始 trace 分卷")
        text = legacy_text(chain)
        meta.update(source_recording_id=chain.volumes[0].header.recording_id,
                    source_volumes=[volume.path.name for volume in chain.volumes])
    else:
        integrity = load_raw_log_integrity(str(source))
        if integrity["issues"] and integrity["issues"] != ["missing integrity proof"]:
            raise ValueError("原日志完整性校验失败：" + "；".join(integrity["issues"]))
        text = integrity["raw_content"]
    if not re.search(r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] HP_V2\s+#\d+\b", text, re.MULTILINE):
        raise ValueError("请选择含伤害记录的 trace_*.log；session_*.ndjson 不是 uploader 日志")
    return _write_export(source, destination, text, meta)


def export_battle_log(record, destination: Path) -> dict:
    """Export precisely one indexed battle, including its retained context."""
    from endfield_pcap.history.importer import TraceCombatRecord
    source, destination = record.file_path, Path(destination).resolve()
    if destination == source.resolve():
        raise ValueError('请另存导出文件，不能覆盖原始日志')
    if record.source_start_line < 0 or record.source_end_line <= record.source_start_line:
        raise ValueError('所选战斗没有有效的来源范围，请刷新记录')
    if isinstance(record, TraceCombatRecord) and not record.source_volumes:
        stat = source.stat()
        if (stat.st_mtime_ns, stat.st_size) != tuple(record.source_signature):
            raise ValueError('原始 trace 日志已变化，请刷新记录后重新导出')
        integrity = load_raw_log_integrity(str(source))
        if integrity['issues'] and integrity['issues'] != ['missing integrity proof']:
            raise ValueError('原日志完整性校验失败：' + '；'.join(integrity['issues']))
        text = ''.join(integrity['raw_content'].splitlines(keepends=True)[record.source_start_line:record.source_end_line])
        if (source.stat().st_mtime_ns, source.stat().st_size) != tuple(record.source_signature):
            raise ValueError('原始 trace 日志已变化，请刷新记录后重新导出')
    else:
        from endfield_pcap.trace.legacy import legacy_lines
        if isinstance(record, TraceCombatRecord):
            from parser_core.trace_volumes import read_events, resolve_volumes
            from parser_core.realtime.live_events import LiveEventOverlayBattleParser
            from endfield_pcap.history.structured import chain_signature
            chain = resolve_volumes(source)
            if not chain.complete or chain_signature(chain) != record.source_volumes:
                raise ValueError('原始 trace 分卷已变化或不完整，请刷新记录后重新导出')
            if any(volume.path == destination for volume in chain.volumes):
                raise ValueError('不能覆盖原始 trace 分卷')
            offset = chain.volumes[0].header.timezone_offset_minutes
            prefix = LiveEventOverlayBattleParser(timezone_offset_minutes=offset)
            selected = []
            index = -1
            for index, event in enumerate(read_events(chain)):
                if index < record.source_start_line:
                    prefix.feed_event(event)
                elif index == record.source_start_line:
                    selected.extend(prefix.history_event_context())
                if record.source_start_line <= index < record.source_end_line:
                    selected.append(event)
            if index + 1 < record.source_end_line:
                raise ValueError('所选战斗事件范围不完整，请刷新记录')
        else:
            from endfield_pcap.history.analysis import session_record_events
            from endfield_pcap.history.session_volumes import resolve_sessions, retains_sources
            from endfield_pcap.history.records import _parse_log_file
            chain = resolve_sessions(source)
            if record.session_volumes and not retains_sources(chain, record.session_volumes):
                raise ValueError('原始 session 分卷已变化或不完整，请刷新记录后重新导出')
            if any(volume.path == destination for volume in chain.volumes):
                raise ValueError('不能覆盖原始 session 分卷')
            # Re-index before checking the old prefix: include any newly written
            # evidence of this battle, while stopping at the next battle boundary.
            fresh = next((row for row in _parse_log_file(source)
                          if (row.record_index, row.started_at_ms) == (record.record_index, record.started_at_ms)), None)
            if fresh is None:
                raise ValueError('所选战斗的来源范围已变化，请刷新记录')
            selected, offset = session_record_events(record)
            if fresh.source_prefix_sha256 != record.source_prefix_sha256:
                selected, offset = session_record_events(fresh)
            record = fresh
        text = ''.join(line for event in selected for line in legacy_lines(event, timezone_offset_minutes=offset))
    if not re.search(r'^\[\d{2}:\d{2}:\d{2}\.\d{3}\] HP_V2\s+#\d+\b', text, re.MULTILINE):
        raise ValueError('所选战斗没有可导出的伤害证据')
    return _write_export(source, destination, text, dict(exporter='endfield-pcap-gui',
        source_file_name=source.name, scope='selected_battle', battle_index=record.record_index,
        source_start_line=record.source_start_line, source_end_line=record.source_end_line),
        source_mtime=record.started_at_ms / 1000)


def _write_export(source, destination, text, meta, *, source_mtime=None):
    proof = build_raw_log_proof(text.encode("utf-8"), file_name=destination.name,
        meta=meta)
    separator = bool(text) and not text.endswith("\n")
    content = text + ("\n" if separator else "") + (
        f"{RAW_LOG_PROOF_BEGIN_PREFIX}{int(separator)}\n"
        f"{json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2)}\n"
        f"{RAW_LOG_PROOF_END}\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                         prefix=destination.name + ".", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        # Uploader uses mtime as the reference date for time-only trace lines.
        # Retain the capture file's date when exporting a past day's logs.
        source_mtime = source.stat().st_mtime if source_mtime is None else source_mtime
        os.utime(temp_path, (source_mtime, source_mtime))
        temp_path.replace(destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return proof
