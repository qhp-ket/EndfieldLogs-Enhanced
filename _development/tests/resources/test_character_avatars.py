"""Offline portrait identity, bounded access, hashes and decoded-image caching."""
import hashlib
import shutil
import pytest
from app_test_support.runtime.tools import tool
from PySide6.QtCore import QUrl
from PySide6.QtGui import QImage
from endfield_pcap.data import avatars
from endfield_pcap.gui.shared import avatars as qt_avatars


def test_portrait_manifest_hashes_dimensions_and_transparency():
    data = avatars.manifest()
    assert len(data['portraits']) >= 35
    for key, row in data['portraits'].items():
        path = avatars.avatar_path(key)
        assert path.parent == avatars.ROOT and path.name == row['path']
        assert path.stat().st_size == row['bytes']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256']
        assert len(row['original_sha256']) == 64 and len(row['original_md5']) == 32
        image = QImage(str(path))
        assert image.width() == image.height() == 128
        assert image.hasAlphaChannel() and image.pixelColor(0, 0).alpha() == 0
    assert avatars.avatar_path('chr_0002_endminm') != avatars.avatar_path('chr_0003_endminf')
    assert not data['aliases'] or all(value in data['portraits'] for value in data['aliases'].values())


def test_unknown_entities_missing_once_and_explicit_aliases(monkeypatch, caplog):
    with caplog.at_level('INFO', logger=avatars.__name__):
        for _ in range(3):
            assert avatars.avatar_path('chr_9999_avatar_test') == avatars.ROOT/'placeholder.png'
        assert caplog.text.count('chr_9999_avatar_test') == 1
    for key in ('enemy_0002', 'public', '', None):
        assert avatars.avatar_path(key) is None
    data = dict(avatars.manifest(), aliases={'chr_9999_form': 'chr_0002_endminm'})
    monkeypatch.setattr(avatars, 'manifest', lambda: data)
    assert avatars.avatar_path('chr_9999_form') == avatars.avatar_path('chr_0002_endminm')
    data['portraits']['chr_bad_path'] = {'path': '../private.png'}
    assert avatars.avatar_path('chr_bad_path') == avatars.ROOT/'placeholder.png'
    del data['portraits']['chr_bad_path']


def test_qt_cache_reuses_decode_and_scales_for_size_and_dpi(app):
    qt_avatars._scaled.cache_clear()
    qt_avatars._source.cache_clear()
    pixmap = qt_avatars.avatar_pixmap('chr_0002_endminm', 24, 1.)
    for _ in range(20):
        assert qt_avatars.avatar_pixmap('chr_0002_endminm', 24, 1.).cacheKey() == pixmap.cacheKey()
    assert qt_avatars._source.cache_info().misses == 1
    scaled = qt_avatars.avatar_pixmap('chr_0002_endminm', 48, 2.)
    assert scaled.width() == 96 and scaled.devicePixelRatio() == 2.
    assert qt_avatars._source.cache_info().misses == 1
    assert qt_avatars.avatar_pixmap('public', 24).isNull()




def test_ui_manifest_is_audited_separately_and_rejects_corruption(tmp_path, monkeypatch):
    audit = tool('audit_runtime_data')
    folder = tmp_path/'_internal/data/ui/characters'
    shutil.copytree(avatars.ROOT, folder)
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    assert list(audit.resources()) == []
    audit.verify_portraits()
    (folder/'placeholder.png').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='changed portrait'):
        audit.verify_portraits()
