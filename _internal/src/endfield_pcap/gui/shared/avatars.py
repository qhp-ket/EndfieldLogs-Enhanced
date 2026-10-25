"""Cache decoded portrait sources and scaled Qt pixmaps."""
from functools import lru_cache
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from endfield_pcap.data.avatars import avatar_path, manifest


@lru_cache(maxsize=80)
def _source(path, version):
    return QImage(path)


@lru_cache(maxsize=512)
def _scaled(key, size, ratio, version):
    path = avatar_path(key)
    if path is None:
        return QPixmap()
    image = _source(str(path), version)
    if image.isNull():
        from endfield_pcap.data.avatars import ROOT
        image = _source(str(ROOT/'placeholder.png'), version)
    pixmap = QPixmap.fromImage(image.scaled(round(size*ratio), round(size*ratio),
        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def avatar_pixmap(key, size, ratio=1.):
    return _scaled(str(key), max(1, round(size)), float(ratio), manifest().get('version', 'missing'))
