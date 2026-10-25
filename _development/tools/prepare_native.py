"""Acquire the small official SDL3 runtime; verify every byte against the manifest."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile


def prepare_native(root,*,check=False,offline=False,archive=None):
    root=Path(root)
    target=root/'_internal/native'
    manifest=json.loads((target/'manifest.json').read_text(encoding='utf8'))
    names={'SDL3.dll','SDL3-LICENSE.txt'}
    if set(manifest['files'])!=names:
        raise ValueError('Unexpected native runtime manifest members')
    def valid():
        return all((target/name).is_file() and (target/name).stat().st_size==row['bytes'] and
                   hashlib.sha256((target/name).read_bytes()).hexdigest()==row['sha256']
                   for name,row in manifest['files'].items())
    if valid(): return
    if check: raise ValueError('Prepare the verified SDL3 runtime with prepare_native.py')
    cache=Path(archive) if archive else root/'_development/cache'/Path(manifest['source']).name
    if not cache.is_file():
        if offline: raise FileNotFoundError('SDL3 archive missing; provide --archive for offline setup')
        cache.parent.mkdir(parents=True,exist_ok=True)
        request=urllib.request.Request(manifest['source'],headers={'User-Agent':'Endfield-Logs-Enhanced-setup'})
        with urllib.request.urlopen(request,timeout=60) as response:
            data=response.read(16*1024*1024)
        if hashlib.sha256(data).hexdigest()!=manifest['archive_sha256']:
            raise ValueError('SDL3 archive checksum mismatch')
        cache.write_bytes(data)
    data=cache.read_bytes()
    if hashlib.sha256(data).hexdigest()!=manifest['archive_sha256']:
        raise ValueError('SDL3 archive checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        dll=source.read('SDL3.dll')
        if hashlib.sha256(dll).hexdigest()!=manifest['files']['SDL3.dll']['sha256']:
            raise ValueError('SDL3 runtime checksum mismatch')
        # The source-controlled license is reviewed separately; never replace it at setup.
        (target/'SDL3.dll').write_bytes(dll)
    if not valid(): raise ValueError('SDL3 native runtime verification failed')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    prepare_native(Path(__file__).resolve().parents[2],check=args.check,offline=args.offline,archive=args.archive)
    print('SDL3 runtime verified')
