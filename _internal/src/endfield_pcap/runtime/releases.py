"""Read official application releases; never download or execute updates."""
from __future__ import annotations

from datetime import datetime
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPOSITORY = 'qhp-ket/EndfieldLogs-Enhanced'
API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
VERSION = re.compile(r'^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$')


def release_update(payload, current_version, ignored_version=''):
    if not isinstance(payload, dict) or payload.get('draft') or payload.get('prerelease'):
        return None
    tag = str(payload.get('tag_name') or '')
    match = VERSION.fullmatch(tag)
    current = re.match(r'^v?(\d+)\.(\d+)\.(\d+)(.*)$', current_version)
    if not match or not current or not payload.get('published_at'):
        return None
    published = datetime.fromisoformat(str(payload['published_at']).replace('Z', '+00:00'))
    if published.tzinfo is None:
        return None
    candidate, installed = tuple(map(int, match.groups())), tuple(map(int, current.groups()[:3]))
    if candidate < installed or (candidate == installed and not current[4].startswith('-')):
        return None
    if tag.lstrip('v') == ignored_version.lstrip('v'):
        return None
    return dict(version=tag.lstrip('v'), published_at=published.isoformat(),
                url=f'https://github.com/{REPOSITORY}/releases/tag/{quote(tag, safe="")}')


def check_update(current_version, ignored_version=''):
    request = Request(API, headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Endfield-Logs-Enhanced'})
    try:
        with urlopen(request, timeout=8) as response:
            data = response.read(1024*1024+1)
    except HTTPError as exc:
        if exc.code == 404:  # No published official release (or a private repo).
            return None
        raise
    if len(data) > 1024*1024:
        raise ValueError('更新信息过大')
    return release_update(json.loads(data), current_version, ignored_version)
