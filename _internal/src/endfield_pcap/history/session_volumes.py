"""Continuous raw business-event volumes; headers never enter TraceBridge."""
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SessionVolume:
    path: Path
    header: dict | None
    signature: tuple


@dataclass(frozen=True, slots=True)
class SessionChain:
    volumes: tuple[SessionVolume, ...]
    issues: tuple[str, ...]

    @property
    def complete(self):
        return not self.issues


def _signature(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino


def _matches(path, expected, allow_append=False):
    actual = _signature(path)
    return actual == expected or (allow_append and actual[0] > expected[0]
                                  and actual[2:] == expected[2:])


def _inspect(path):
    signature = _signature(path)
    with path.open('rb') as stream:
        raw = stream.readline()
    try:
        value = json.loads(raw)
    except ValueError:
        value = None  # Old raw files may start with malformed business data.
    header = value if isinstance(value, dict) and value.get('type') == 'session_volume' else None
    if header is not None:
        integers = ('volume', 'trace_volume', 'event_offset', 'timezone_offset_minutes')
        previous = header.get('previous_volume')
        if (header.get('schema_version') != 1
                or any(not isinstance(header.get(key), str) or not header[key]
                       for key in ('recording_id', 'session_id', 'trace_recording_id'))
                or any(type(header.get(key)) is not int for key in integers)
                or header['volume'] < 1 or header['trace_volume'] < 1 or header['event_offset'] < 0
                or not -840 <= header['timezone_offset_minutes'] <= 840
                or (header['volume'] == 1 and (previous is not None or header['event_offset'] != 0))
                or (header['volume'] > 1 and (not isinstance(previous, dict)
                    or previous.get('volume') != header['volume'] - 1))):
            raise ValueError('session 分卷文件头无效')
        if previous is not None:
            name = previous.get('file')
            if (not isinstance(name, str) or not name or name in ('.', '..')
                    or any(char in name for char in '/\\:<>"|?*\0')):
                raise ValueError('session 前卷引用必须是同目录文件名')
    if not _matches(path, signature, allow_append=True):
        raise ValueError('session 在读取文件头时发生变化，请刷新记录')
    return SessionVolume(path, header, signature)


def resolve_sessions(path):
    path = Path(path).resolve()
    selected = _inspect(path)
    if selected.header is None:
        return SessionChain((selected,), ())
    volumes = [selected]
    for candidate in path.parent.glob('session_*.ndjson'):
        if candidate == path:
            continue
        try:
            other = _inspect(candidate)
        except (OSError, ValueError):
            continue
        if other.header and other.header['recording_id'] == selected.header['recording_id']:
            volumes.append(other)
    volumes.sort(key=lambda item: item.header['volume'])
    issues, expected = [], 1
    for volume in volumes:
        header = volume.header
        if header['volume'] < expected:
            raise ValueError(f"session 有重复的第 {header['volume']} 卷")
        if header['volume'] > expected:
            issues.append(f"session 缺少第 {expected}～{header['volume'] - 1} 卷，记录不完整")
        expected = header['volume'] + 1
        if any(header[key] != selected.header[key] for key in (
                'session_id', 'trace_recording_id', 'timezone_offset_minutes')):
            raise ValueError('session 连续分卷的会话、trace 或时区不一致')
        previous = header.get('previous_volume')
        if previous:
            named = path.parent / previous['file']
            predecessor = next((item for item in volumes if item.header['volume'] == previous['volume']), None)
            if named.exists() and predecessor is not None and named != predecessor.path:
                raise ValueError('session 前卷文件名与录制身份不一致')
    return SessionChain(tuple(volumes), tuple(issues))


def chain_signature(chain):
    return [dict(path=str(item.path), signature=list(item.signature), header=item.header) for item in chain.volumes]


def retains_sources(chain, sources):
    """Allow recording append/rotation while retaining the indexed volume identity."""
    current = {str(item.path): item for item in chain.volumes}
    for source in sources:
        volume = current.get(source['path'])
        expected = source['signature']
        if (volume is None or volume.header != source['header']
                or volume.signature[0] < expected[0]
                or tuple(volume.signature[2:]) != tuple(expected[2:])):
            return False
    return True


def session_source_signature(path):
    chain = resolve_sessions(path)
    return [chain_signature(chain), list(chain.issues)]


def read_lines(chain, *, allow_append=False):
    if not chain.complete:
        raise ValueError('；'.join(chain.issues))
    count = 0
    for volume in chain.volumes:
        if not _matches(volume.path, volume.signature, allow_append):
            raise ValueError('session 已变化，请刷新记录')
        if volume.header and volume.header['event_offset'] != count:
            raise ValueError('session 跨卷事件位置不连续')
        with volume.path.open('rb') as stream:
            if volume.header:
                first = stream.readline()
                if not first.endswith(b'\n'):
                    raise ValueError('session 有尚未完成的 NDJSON 行，请稍后重试')
                if json.loads(first) != volume.header:
                    raise ValueError('session 分卷文件头已变化，请刷新记录')
            remaining = volume.signature[0] - stream.tell()
            while remaining > 0:
                raw = stream.readline(remaining)
                if not raw:
                    raise ValueError('session 已截断，请刷新记录')
                remaining -= len(raw)
                if volume.header and not raw.endswith(b'\n'):
                    raise ValueError('session 有尚未完成的 NDJSON 行，请稍后重试')
                count += 1
                yield raw.decode('utf8').rstrip('\r\n')
        if not _matches(volume.path, volume.signature, allow_append):
            raise ValueError('session 在读取时发生变化，请刷新记录')


def associated_trace(chain):
    """Find the trace by immutable recording identity, even after renaming."""
    from parser_core.trace_volumes import resolve_volumes
    from parser_core.trace_jsonl import parse
    header = chain.volumes[0].header
    if not header:
        return None
    for path in chain.volumes[0].path.parent.glob('*.jsonl'):
        if path.name.lower().endswith('.input.jsonl'):
            continue
        try:
            with path.open('rb') as stream:
                trace_header = parse(stream.readline(), header=True)
        except (OSError, ValueError, TypeError):
            continue
        if trace_header.recording_id == header['trace_recording_id']:
            trace = resolve_volumes(path)
            if any(not any(item.header.volume == volume.header['trace_volume']
                           and item.header.timezone_offset_minutes == volume.header['timezone_offset_minutes']
                           for item in trace.volumes) for volume in chain.volumes):
                raise ValueError('session 配套的 trace 分卷缺失或时区不一致')
            return trace
    raise ValueError('未找到 session 关联的 trace 分卷')
