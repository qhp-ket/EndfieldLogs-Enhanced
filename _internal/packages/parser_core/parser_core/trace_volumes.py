"""Discover continuous JSONL volumes by identity, including renamed files."""
from dataclasses import dataclass
from pathlib import Path

from parser_core.trace_jsonl import TraceHeader, TraceEvent, TraceJsonlReader, parse


@dataclass(frozen=True, slots=True)
class TraceVolume:
    path: Path
    header: TraceHeader
    signature: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class TraceVolumeChain:
    volumes: tuple[TraceVolume, ...]
    issues: tuple[str, ...]

    @property
    def complete(self):
        return not self.issues


def _signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


def _inspect(path):
    signature = _signature(path)
    with path.open('rb') as stream:
        header = parse(stream.readline(), header=True)
    previous = header.previous_volume
    if previous is not None:
        name = previous['file']
        if name in ('.', '..') or any(char in name for char in '/\\:<>"|?*\0'):
            raise ValueError('trace 前卷引用必须是同目录文件名')
    if _signature(path) != signature:
        raise ValueError('trace 在读取文件头时发生变化，请刷新记录')
    return TraceVolume(path, header, signature)


def resolve_volumes(path):
    path = Path(path).resolve()
    selected = _inspect(path)
    volumes = [selected]
    for candidate in path.parent.glob('*.jsonl'):
        if candidate == path or candidate.name.lower().endswith('.input.jsonl'):
            continue
        try:
            other = _inspect(candidate)
        except (OSError, ValueError, TypeError):
            continue
        if other.header.recording_id == selected.header.recording_id:
            volumes.append(other)
    volumes.sort(key=lambda volume: volume.header.volume)
    issues, expected = [], 1
    for volume in volumes:
        header = volume.header
        if header.volume < expected:
            raise ValueError(f'trace 录制有重复的第 {header.volume} 卷')
        if header.volume > expected:
            issues.append(f'trace 缺少第 {expected}～{header.volume - 1} 卷，记录不完整')
        expected = header.volume + 1
        if any(getattr(header, field) != getattr(selected.header, field) for field in (
                'version', 'language', 'generator_version', 'timezone_id', 'timezone_offset_minutes', 'resources')):
            raise ValueError('trace 连续分卷的生成器、时区或资源不一致')
        if header.previous_volume is not None:
            previous = header.previous_volume
            named = path.parent / previous['file']
            predecessor = next((item for item in volumes if item.header.volume == previous['volume']), None)
            if named.exists() and predecessor is not None and named != predecessor.path:
                raise ValueError('trace 前卷文件名与录制身份不一致')
    return TraceVolumeChain(tuple(volumes), tuple(issues))


def read_events(chain):
    if not chain.complete:
        raise ValueError('；'.join(chain.issues))
    sequence = 0
    for volume in chain.volumes:
        if _signature(volume.path) != volume.signature:
            raise ValueError('trace 已变化，请刷新记录')
        reader = TraceJsonlReader()
        remaining = volume.signature[0]
        with volume.path.open('rb') as stream:
            while remaining:
                chunk = stream.read(min(64 * 1024, remaining))
                if not chunk:
                    raise ValueError('trace 在读取时发生变化，请刷新记录')
                remaining -= len(chunk)
                for record in reader.feed(chunk):
                    if isinstance(record, TraceHeader):
                        if record != volume.header:
                            raise ValueError('trace 文件头已变化，请刷新记录')
                    elif isinstance(record, TraceEvent):
                        if record.sequence != sequence + 1:
                            raise ValueError('trace 跨卷事件序号不连续')
                        sequence = record.sequence
                        yield record
        if reader.header is None or reader.pending_bytes:
            raise ValueError('trace 有尚未完成的 JSONL 行，请稍后重试')
        if _signature(volume.path) != volume.signature:
            raise ValueError('trace 在读取时发生变化，请刷新记录')
