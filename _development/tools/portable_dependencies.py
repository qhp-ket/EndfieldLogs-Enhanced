"""Explicit Windows runtime surface, with native import closure (including delay imports).

No installed package is modified. Keep software GPU fallbacks, image codecs and
TLS plugins; remove Qt development tools, unused bindings, QML and debug assets.
"""
from pathlib import Path, PurePosixPath
import struct

QT_BINDINGS = frozenset({'QtCore', 'QtGui', 'QtWidgets', 'QtNetwork', 'QtPrintSupport',
                         'QtSvg', 'QtSvgWidgets', 'QtXml', 'QtWebChannel', 'QtMultimedia',
                         'QtWebEngineCore', 'QtWebEngineWidgets'})
QT_PLUGIN_GROUPS = frozenset({'platforms', 'styles', 'imageformats', 'iconengines',
                             'networkinformation', 'tls', 'platforminputcontexts', 'multimedia'})
QT_RESOURCES = frozenset({'icudtl.dat', 'qtwebengine_resources.pak',
                         'qtwebengine_resources_100p.pak', 'qtwebengine_resources_200p.pak',
                         'v8_context_snapshot.bin'})
LOCALES = frozenset({'en-US', 'zh-CN', 'zh-TW'})


def pe_imports(path):
    """Read ordinary and delayed PE import names without a build-only dependency."""
    data = Path(path).read_bytes()
    if data[:2] != b'MZ':
        raise ValueError(f'Not a PE image: {path}')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe+4] != b'PE\0\0':
        raise ValueError(f'Invalid PE image: {path}')
    sections_count, = struct.unpack_from('<H', data, pe+6)
    optional_size, = struct.unpack_from('<H', data, pe+20)
    optional = pe+24
    magic, = struct.unpack_from('<H', data, optional)
    if magic not in {0x10b, 0x20b}:
        raise ValueError(f'Unsupported PE image: {path}')
    directories = optional+(112 if magic == 0x20b else 96)
    image_base, = struct.unpack_from('<Q' if magic == 0x20b else '<I', data,
                                    optional+(24 if magic == 0x20b else 28))
    sections = []
    for index in range(sections_count):
        offset = optional+optional_size+index*40
        virtual_size, rva, raw_size, raw = struct.unpack_from('<IIII', data, offset+8)
        sections.append((rva, max(virtual_size, raw_size), raw))

    def offset(rva):
        for start, size, raw in sections:
            if start <= rva < start+size:
                return raw+rva-start
        raise ValueError(f'Unmapped PE RVA in {path}')

    def name(rva):
        start = offset(rva)
        return data[start:data.index(b'\0', start)].decode('ascii').lower()

    result = set()
    for directory, width in ((1, 20), (13, 32)):
        rva, size = struct.unpack_from('<II', data, directories+directory*8)
        if not rva:
            continue
        start = offset(rva)
        for pos in range(start, start+size, width):
            row = struct.unpack_from('<'+'I'*(width//4), data, pos)
            if not any(row):
                break
            if directory == 1:
                result.add(name(row[3]))
            else:
                result.add(name(row[1] if row[0] & 1 else row[1]-image_base))
    return result


def qt_runtime_files(root):
    """Return package-relative runtime files and all wheel-local native dependencies."""
    root = Path(root)
    files = {p.relative_to(root).as_posix(): p for p in root.rglob('*') if p.is_file()}
    selected = set()
    for relative in files:
        p = PurePosixPath(relative)
        if len(p.parts) == 1:
            if p.name in {'__init__.py', '_config.py', 'py.typed', 'QtWebEngineProcess.exe',
                          'opengl32sw.dll', 'd3dcompiler_47.dll', 'libEGL.dll', 'libGLESv2.dll',
                          'vk_swiftshader.dll', 'vk_swiftshader_icd.json', 'vulkan-1.dll'}:
                selected.add(relative)
            elif p.suffix == '.pyd' and p.stem in QT_BINDINGS:
                selected.add(relative)
            elif p.name.startswith('pyside6') and p.suffix == '.dll':
                selected.add(relative)
        elif p.parts[0] == 'plugins' and p.parts[1] in QT_PLUGIN_GROUPS and p.suffix == '.dll':
            if p.parts[1] == 'multimedia' and p.name != 'ffmpegmediaplugin.dll':
                continue
            if p.parts[1] != 'platforms' or p.name in {'qwindows.dll', 'qoffscreen.dll'}:
                selected.add(relative)
        elif p.parts[0] == 'resources' and len(p.parts) == 2 and p.name in QT_RESOURCES:
            selected.add(relative)
        elif p.parts[:2] == ('translations', 'qtwebengine_locales') and p.stem in LOCALES and p.suffix == '.pak':
            selected.add(relative)
        elif (p.parts[0] == 'translations' and len(p.parts) == 2 and
              p.name.startswith(('qtbase_', 'qtwebengine_')) and
              p.name.endswith(('_en.qm', '_zh_CN.qm', '_zh_TW.qm'))):
            selected.add(relative)
    required = {name+'.pyd' for name in QT_BINDINGS} | {'QtWebEngineProcess.exe'}
    required |= {'resources/'+name for name in QT_RESOURCES}
    if missing := required-selected:
        raise ValueError('Missing Qt runtime inputs: '+', '.join(sorted(missing)))
    native = {PurePosixPath(n).name.lower(): n for n in files if PurePosixPath(n).suffix.lower() == '.dll'}
    pending = list(selected)
    while pending:
        relative = pending.pop()
        if PurePosixPath(relative).suffix.lower() not in {'.pyd', '.dll', '.exe'}:
            continue
        for dependency in pe_imports(files[relative]):
            candidate = native.get(dependency)
            if candidate and candidate not in selected:
                selected.add(candidate)
                pending.append(candidate)
    return selected


def dependency_file_allowed(relative, qt_files):
    path = PurePosixPath(str(relative).replace('\\', '/'))
    if path.parts[0] == 'PySide6':
        return PurePosixPath(*path.parts[1:]).as_posix() in qt_files
    # Build interfaces, stubs and help files are not runtime inputs.
    if path.suffix.lower() in {'.h', '.hpp', '.lib', '.pyi', '.chm', '.pdb'}:
        return False
    if path.parts[0] in {'pythonwin', 'isapi', 'adodbapi', 'win32comext'}:
        return False
    if path.parts[0] == 'win32' and len(path.parts) > 1:
        if path.parts[1] == 'lib':
            return path.name in {'win32con.py', 'win32error.py', 'pywintypes.py'}
        return path.name in {'win32api.pyd', 'win32gui.pyd', 'win32print.pyd'}
    return True
