"""Disposable per-file history indexes. No raw logs or analysis snapshots are copied."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .record_parser import CombatRecord, CombatPlayerSummary, _parse_log_file
from .trace_import import TraceCombatRecord, load_trace_records
from .runtime_paths import app_root, bundle_root


def record_key(record: CombatRecord) -> str:
    # Keep a removed battle hidden after an append or a reindex of its source.
    # Index paths are already absolute: avoid filesystem lookups per UI row.
    return json.dumps([os.path.normcase(str(record.file_path)), record.record_index, record.started_at_ms], ensure_ascii=False)


class HistoryIndex:
    VERSION = 1

    def __init__(self, directory: Path):
        self.directory = directory

    def relocate(self, old: Path, new: Path):
        """Move disposable metadata without reparsing or changing log contents."""
        for kind in ('trace', 'ndjson'):
            def cache_for(path):
                return self.directory / (hashlib.sha256((kind+str(path)).encode('utf8')).hexdigest()+'.json')
            source, destination = cache_for(old), cache_for(new)
            temporary = None
            try:
                payload = json.loads(source.read_text(encoding='utf8'))
                stat = new.stat()
                if (not isinstance(payload, dict) or payload.get('version') != self.VERSION
                        or payload.get('source') != str(old) or payload.get('kind') != kind
                        or payload.get('signature') != [stat.st_mtime_ns, stat.st_size]):
                    continue
                payload['source'] = str(new)
                for row in payload['records']:
                    row['file_path'] = str(new)
                    row['label'] = row['label'].replace(old.name, new.name)
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=self.directory, delete=False) as stream:
                    temporary = Path(stream.name)
                    json.dump(payload, stream, ensure_ascii=False)
                os.replace(temporary, destination)
                source.unlink(missing_ok=True)
            except (OSError, ValueError, KeyError, TypeError, AttributeError):
                pass  # A missing cache is rebuilt lazily after restart.
            finally:
                if temporary:
                    try:
                        temporary.unlink(missing_ok=True)
                    except OSError:
                        pass

    def records(self, path: Path, *, trace: bool = False) -> list[CombatRecord]:
        path = path.resolve()
        stat = path.stat()
        signature = [stat.st_mtime_ns, stat.st_size]
        kind = 'trace' if trace else 'ndjson'
        digest = hashlib.sha256((kind + str(path)).encode('utf-8')).hexdigest()
        cache = self.directory / (digest + '.json')
        try:
            payload = json.loads(cache.read_text(encoding='utf-8'))
            if (payload['version'] == self.VERSION and payload['source'] == str(path)
                    and payload['signature'] == signature and payload['kind'] == kind):
                records = []
                for row in payload['records']:
                    row['file_path'] = path
                    row['players'] = [CombatPlayerSummary(**player) for player in row['players']]
                    if trace:
                        row['source_signature'] = tuple(row['source_signature'])
                    records.append((TraceCombatRecord if trace else CombatRecord)(**row))
                return records
        except (OSError, ValueError, KeyError, TypeError):
            pass  # Missing, outdated or damaged indexes can always be rebuilt.
        records = load_trace_records(path) if trace else _parse_log_file(path)
        after = path.stat()
        if [after.st_mtime_ns, after.st_size] != signature:
            raise ValueError('日志正在变化，请稍后刷新记录')
        rows = []
        for record in records:
            row = asdict(record)
            row['file_path'] = str(path)
            row.pop('snapshot', None)
            rows.append(row)
        payload = dict(version=self.VERSION, source=str(path), signature=signature, kind=kind, records=rows)
        temporary = None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False)
            os.replace(temporary, cache)
        except OSError:
            pass  # Read-only profiles still support history without a cache.
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return records



def _has_combat_logs(path: Path) -> bool:
    try:
        if not path.exists():
            return False
        for child in path.rglob("session_*.ndjson"):
            try:
                if child.is_file() and child.stat().st_size > 0:
                    return True
            except OSError:
                continue
    except OSError:
        return False
    return False


def _resolve_log_dir(preferred: Path) -> Path:
    candidates: list[Path] = []
    seen: set[str] = set()
    for candidate in (
        preferred,
        app_root() / "logs",
        bundle_root() / "logs",
        Path.cwd() / "logs",
    ):
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(candidate)
    for candidate in candidates:
        if _has_combat_logs(candidate):
            return candidate.resolve()
    return preferred.resolve()


