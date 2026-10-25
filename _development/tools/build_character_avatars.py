"""Build small offline UI portraits from AKEData's indexed charroundicon assets."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT = Path(__file__).resolve().parents[2]
if sys.prefix == sys.base_prefix:
    sys.path[:0] = [str(ROOT/'_internal/python_deps/gui'), str(ROOT/'_internal/python_deps/common')]
import httpx
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

BASE = 'https://data.akedata.wiki'
CACHE = ROOT / '_development/cache/character-avatars'
OUTPUT = ROOT / '_internal/data/ui/characters'


def circle(source):
    image = QImage(str(source))
    if image.isNull():
        raise ValueError('Invalid portrait: '+source.name)
    image = image.scaled(128, 128, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    result = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    mask = QPainterPath()
    mask.addEllipse(QRectF(0, 0, 128, 128))
    painter.setClipPath(mask)
    painter.drawImage((128-image.width())//2, (128-image.height())//2, image)
    painter.end()
    return result


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    placeholder = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
    placeholder.fill(Qt.GlobalColor.transparent)
    painter = QPainter(placeholder)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor('#64748b'))
    painter.drawEllipse(QRectF(0, 0, 128, 128))
    painter.setBrush(QColor('#e2e8f0'))
    painter.drawEllipse(QRectF(44, 25, 40, 40))
    painter.drawEllipse(QRectF(28, 70, 72, 48))
    painter.end()
    placeholder.save(str(OUTPUT/'placeholder.png'))
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(BASE+'/asset-sync-index.json')
        response.raise_for_status()
        index = response.json()
        (CACHE/'asset-sync-index.json').write_bytes(response.content)
        files = index['datasets']['images']['files']
        candidates = {}
        for path, record in files.items():
            match = re.fullmatch(r'.*/charroundicon/icon_round_(chr_\d+_[a-z0-9]+)\.png', path)
            if match:
                candidates[match[1]] = (path, record)
        if not candidates:
            raise ValueError('No indexed charroundicon images')
        def build(item):
            key, (path, record) = item
            # Index paths are relative to the image dataset's public root.
            url = BASE+'/public/images/'+path.removeprefix('public/images/')
            raw = CACHE/(key+'.png')
            if not raw.exists() or hashlib.md5(raw.read_bytes()).hexdigest() != record['md5']:
                resource = client.get(url)
                resource.raise_for_status()
                if hashlib.md5(resource.content).hexdigest() != record['md5']:
                    raise ValueError('Image index checksum mismatch: '+key)
                raw.write_bytes(resource.content)
            target = OUTPUT/(key+'.png')
            if not circle(raw).save(str(target)):
                raise ValueError('Cannot save '+key)
            return key, dict(path=target.name, source=url, original_md5=record['md5'],
                             original_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),
                             sha256=hashlib.sha256(target.read_bytes()).hexdigest(), bytes=target.stat().st_size)
        with ThreadPoolExecutor(max_workers=6) as pool:
            portraits = dict(pool.map(build, sorted(candidates.items())))
    neutral = OUTPUT/'placeholder.png'
    manifest = dict(schema_version=1, version=index['revision'],
                    source_index=BASE+'/asset-sync-index.json', portraits=portraits, aliases={},
                    placeholder=dict(path=neutral.name, sha256=hashlib.sha256(neutral.read_bytes()).hexdigest(),
                                     bytes=neutral.stat().st_size))
    (OUTPUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(portraits=len(portraits), bytes=sum(p.stat().st_size for p in OUTPUT.iterdir() if p.is_file())),indent=2))


if __name__ == '__main__':
    main()
