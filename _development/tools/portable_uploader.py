"""Extract the uploader unchanged from a verified upstream release archive."""
from pathlib import PurePosixPath
import zipfile

PREFIX = 'EndfieldLogsClient/_internal/uploader/'


def extract_uploader(archive, target):
    total = count = 0
    with zipfile.ZipFile(archive) as bundle:
        seen = set()
        for info in bundle.infolist():
            if info.is_dir() or not info.filename.startswith(PREFIX):
                continue
            relative = PurePosixPath(info.filename[len(PREFIX):])
            if (not relative.parts or relative.is_absolute() or '..' in relative.parts
                    or chr(92) in str(relative) or ':' in str(relative)
                    or str(relative).casefold() in seen):
                raise ValueError('Unsafe or duplicate official uploader member')
            seen.add(str(relative).casefold())
            destination = target.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                content = bundle.read(info)
                stream.write(content)
            total += len(content)
            count += 1
    if not count:
        raise ValueError('Official uploader missing from archive')
    return dict(policy='official-archive-byte-exact-v1', files=count, original_bytes=total,
                packaged_bytes=total)
