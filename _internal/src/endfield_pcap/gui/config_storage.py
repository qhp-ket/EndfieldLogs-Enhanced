"""Atomic settings storage and application-relative portable references."""
from __future__ import annotations

import json
import logging
import math
import os
from pathlib import Path
import tempfile
import time
import uuid

LOGGER = logging.getLogger(__name__)
SERVICE_PATHS = ('log_dir', 'debug_dir', 'rsa_key_txt', 'name_index_path')


def number(value, default, *, integer=False):
    try:
        if isinstance(value, bool):
            return default
        result = int(value) if integer else float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError, OverflowError):
        return default


def path_value(value, default):
    try:
        return Path(value).resolve() if isinstance(value, str) and value.strip() and '\0' not in value else default
    except (OSError, ValueError):
        return default


def _object(text):
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError('配置根节点应为对象')
    return payload


def read_settings(target):
    for candidate in (target, target.with_suffix(target.suffix + '.bak')):
        if not candidate.exists():
            continue
        try:
            payload = _object(candidate.read_text(encoding='utf8'))
        except (ValueError, UnicodeError):
            LOGGER.warning('配置损坏：%s', candidate)
            if candidate == target:
                preserved = target.with_name(target.name + '.corrupt-' + uuid.uuid4().hex[:10])
                try:
                    target.rename(preserved)
                except OSError:
                    LOGGER.warning('无法保留损坏配置原文件：%s', target, exc_info=True)
                else:
                    LOGGER.warning('损坏配置保留于：%s', preserved)
            continue
        if candidate != target:
            LOGGER.warning('已从备份恢复配置：%s', candidate)
        return payload
    return {}


def _atomic_write(target, content):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=target.name + '.',
                                         suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                # Windows indexers/scanners can briefly hold the destination.
                time.sleep(.01 * 2**attempt)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_settings(target, payload):
    content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode('utf8')
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        previous = target.read_bytes()
        try:
            _object(previous.decode('utf8'))
        except (ValueError, UnicodeError):
            pass
        else:
            _atomic_write(target.with_suffix(target.suffix + '.bak'), previous)
    _atomic_write(target, content)


def portable_paths(payload, root, *, saving=False):
    """Relocate only application-owned references; preserve external choices."""
    payload = dict(payload)
    service = payload.get('service')
    service = dict(service) if isinstance(service, dict) else {}
    root = root.resolve()
    relative = payload.get('path_base') == 'application'
    previous_root = None
    if not saving and not relative:
        # Older launchers persisted both resource paths under the same root.
        # Require both anchors, rather than guessing from a folder name.
        anchors = []
        for key, suffix in (('rsa_key_txt', Path('_internal/secrets/client_privkey.pem')),
                            ('name_index_path', Path('_internal/jsondata/CharacterNameIndex.json'))):
            value = service.get(key)
            path = path_value(value, None)
            if path is not None and tuple(p.lower() for p in path.parts[-3:]) == tuple(p.lower() for p in suffix.parts):
                anchors.append(path.parents[2])
        if len(anchors) == 2 and anchors[0] == anchors[1]:
            previous_root = anchors[0]

    def convert(value):
        if not isinstance(value, str) or not value.strip() or '\0' in value:
            return value
        try:
            path = Path(value)
            if saving:
                if path.is_absolute() and path.is_relative_to(root):
                    return path.relative_to(root).as_posix()
            elif not path.is_absolute() and relative:
                return str((root / path).resolve())
            elif previous_root is not None and path.is_absolute() and path.is_relative_to(previous_root):
                return str(root / path.relative_to(previous_root))
        except (OSError, ValueError):
            pass
        return value

    def record_key(value):
        try:
            parts = json.loads(value)
            if isinstance(parts, list) and len(parts) == 3 and isinstance(parts[0], str):
                parts[0] = convert(parts[0])
                if not saving:
                    parts[0] = os.path.normcase(parts[0])
                return json.dumps(parts, ensure_ascii=False)
        except (ValueError, TypeError):
            pass
        return value

    for key in SERVICE_PATHS:
        if key in service:
            service[key] = convert(service[key])
    payload['service'] = service
    paths = payload.get('imported_trace_files')
    if isinstance(paths, list):
        payload['imported_trace_files'] = [convert(p) for p in paths]
    hidden = payload.get('hidden_history_records')
    if isinstance(hidden, list):
        payload['hidden_history_records'] = [record_key(p) for p in hidden if isinstance(p, str)]
    bindings = payload.get('input_log_bindings')
    if isinstance(bindings, dict):
        payload['input_log_bindings'] = {record_key(k): v for k, v in bindings.items()}
    overlays = payload.get('overlays')
    if isinstance(overlays, list):
        payload['overlays'] = [dict(item, source_value=convert(item.get('source_value')))
            if isinstance(item, dict) and item.get('source_type') == 'file' else item for item in overlays]
    if saving:
        payload['path_base'] = 'application'
    return payload
