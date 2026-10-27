"""Offline portrait identities shared by all presentation hosts."""
from functools import lru_cache
import json
import logging
from endfield_pcap.runtime.paths import bundle_root

LOGGER = logging.getLogger(__name__)
ROOT = (bundle_root()/'data/ui/characters').resolve()
_missing = set()


@lru_cache(maxsize=1)
def manifest():
    try:
        return json.loads((ROOT/'manifest.json').read_text(encoding='utf8'))
    except (OSError, ValueError):
        return dict(version='missing', portraits={}, aliases={})


def avatar_path(character_key):
    key = str(character_key or '')
    if not key.startswith('chr_'):
        return None  # Public states/enemies do not borrow character identities.
    data = manifest()
    key = data.get('aliases', {}).get(key, key)
    row = data.get('portraits', {}).get(key, {})
    relative = row.get('path', '')
    candidate = (ROOT/relative).resolve()
    if relative and candidate.parent == ROOT and candidate.suffix == '.png' and candidate.is_file():
        return candidate
    if key not in _missing:
        _missing.add(key)
        LOGGER.info('Character portrait unavailable: %s', key)
    return ROOT/'placeholder.png'
