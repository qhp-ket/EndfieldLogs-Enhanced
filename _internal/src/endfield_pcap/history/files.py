"""Rename log files with their proofs, without modifying any signed bytes."""
from __future__ import annotations
import json
import os
import re
from pathlib import Path


def custom_name(path: Path) -> str:
    return path.stem.partition(' -- ')[2]


def renamed_path(path: Path, label: str) -> Path:
    label = label.strip()
    if not label or re.search(r'[<>:"/\\|?*\x00-\x1f]', label) or label.endswith(('.', ' ')):
        raise ValueError('名称不能为空，不能包含 Windows 文件名禁用字符或以点结尾')
    prefix = path.stem.partition(' -- ')[0]
    destination = path.with_name(f'{prefix} -- {label}{path.suffix}')
    if len(destination.name) > 240:
        raise ValueError('名称过长，请缩短后重试')
    return destination


def rename_log(path: Path, label: str) -> Path:
    """Preflight every companion and roll back partial failures. Never overwrite."""
    destination = renamed_path(path, label)
    if destination == path:
        return path
    pairs = [(path, destination)]
    for old, new in ((Path(str(path)+'.integrity.json'), Path(str(destination)+'.integrity.json')),
                     (path.with_suffix('.integrity.json'), destination.with_suffix('.integrity.json')),
                     (Path(str(path)+'.status.json'), Path(str(destination)+'.status.json'))):
        # Even an orphan destination proof must not become attached to this
        # log. Otherwise a valid rename could make uploader verification fail.
        if new.exists():
            raise ValueError(f'文件已存在：{new.name}')
        if old.exists():
            pairs.append((old, new))
    for old, new in pairs:
        if not old.is_file():
            raise ValueError(f'源文件不存在：{old.name}')
        if new.exists():
            raise ValueError(f'文件已存在：{new.name}')
    completed = []
    try:
        for old, new in pairs:
            # Windows Path.rename refuses an existing destination, unlike replace.
            old.rename(new)
            completed.append((old, new))
    except OSError as exc:
        rollback_errors = []
        for old, new in reversed(completed):
            try:
                new.rename(old)
            except OSError as rollback:
                rollback_errors.append(str(rollback))
        if rollback_errors:
            raise OSError(f'重命名失败：{exc}；部分文件恢复失败：{"；".join(rollback_errors)}') from exc
        raise
    return destination


def relocate_key(key: str | None, old: Path, new: Path):
    if key is None:
        return None
    try:
        values = json.loads(key)
        if os.path.normcase(values[0]) == os.path.normcase(str(old)):
            values[0] = os.path.normcase(str(new))
            return json.dumps(values, ensure_ascii=False)
    except (ValueError, TypeError, IndexError):
        pass
    return key


def relocate_record(record, old, new):
    if record.file_path != old:
        return
    record.file_path = new
    record.label = record.label.replace(old.name, new.name)
    # Only source metadata changes. Numerical canonical data stays intact.
    snapshot = getattr(record, 'snapshot', None)
    if snapshot:
        for key in ('source_file_name', 'file_name'):
            if snapshot.get('battle', {}).get(key) == old.name:
                snapshot['battle'][key] = new.name


def record_label(record):
    name = custom_name(record.file_path)
    return f'{record.label} · {name}' if name and record.file_path.name not in record.label else record.label
