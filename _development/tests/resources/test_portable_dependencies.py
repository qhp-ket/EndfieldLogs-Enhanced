"""Runtime pruning must preserve native imports, JSON values and proof bytes."""
from app_test_support.paths import ROOT
import ast
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(ROOT / '_development/tools'))
from portable_dependencies import QT_BINDINGS, dependency_file_allowed, pe_imports, qt_runtime_files
from portable_uploader import extract_uploader, PREFIX


def test_qt_closure_keeps_runtime_dependencies_and_excludes_development_assets():
    root = ROOT / '_internal/python_deps/gui/PySide6'
    if not root.is_dir():
        pytest.skip('Qt wheel is required for the Windows packaging integration check')
    selected = qt_runtime_files(root)
    for required in ('Qt6WebEngineCore.dll', 'Qt6Quick.dll', 'Qt6Core.dll',
                     'plugins/platforms/qwindows.dll', 'opengl32sw.dll',
                     'translations/qtwebengine_locales/zh-CN.pak'):
        assert required in selected
    assert not any('.debug.' in name or name.startswith(('qml/', 'include/', 'metatypes/')) for name in selected)
    assert 'QtDesigner.pyd' not in selected
    assert 'QtTest.pyd' not in selected
    assert 'qtwebengine_devtools_resources.pak' not in selected
    native = {p.name.lower() for p in root.rglob('*.dll')}
    retained = {Path(n).name.lower() for n in selected}
    for name in selected:
        if Path(name).suffix.lower() in {'.dll', '.exe', '.pyd'}:
            assert pe_imports(root / name) & native <= retained


def test_all_application_qt_imports_are_packaged():
    modules = set()
    for path in (ROOT / '_internal/src').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith('PySide6.'):
                    modules.add(node.module.split('.')[1])
                elif node.module == 'PySide6':
                    modules.update(n.name for n in node.names)
    assert modules <= QT_BINDINGS


@pytest.mark.parametrize('relative, keep', [
    ('PyWin32.chm', False), ('pythonwin/Pythonwin.exe', False),
    ('win32/win32gui.pyd', True), ('win32/win32api.pyd', True),
    ('win32/win32print.pyd', True), ('win32/lib/pywintypes.py', True),
    ('win32/win32service.pyd', False), ('numpy/_core/include/array.h', False),
    ('numpy.libs/blas.dll', True), ('certifi/cacert.pem', True),
])
def test_dependency_surface(relative, keep):
    assert dependency_file_allowed(relative, set()) is keep


def test_uploader_extracts_all_original_bytes_and_ignores_unrelated_members(tmp_path):
    import zipfile
    files = {'EndfieldLogsUploader/tool.exe': b'MZ official',
             'EndfieldLogsUploader/data/plain.json': b'{ "a": [ 1, 2 ] }',
             'EndfieldLogsUploader/data/proof.json': b'{ "proof": true }'}
    archive, target = tmp_path / 'official.zip', tmp_path / 'package'
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name, content in files.items():
            bundle.writestr(PREFIX + name, content)
        bundle.writestr('unrelated/private.txt', b'excluded')
    result = extract_uploader(archive, target)
    assert result['packaged_bytes'] == result['original_bytes'] == sum(map(len, files.values()))
    assert {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob('*') if p.is_file()} == files


@pytest.mark.parametrize('member', ['../escape', 'C:/escape', 'tool/../../escape'])
def test_uploader_rejects_unsafe_archive_paths(tmp_path, member):
    import zipfile
    archive = tmp_path / 'official.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr(PREFIX + member, b'unsafe')
    with pytest.raises(ValueError, match='Unsafe'):
        extract_uploader(archive, tmp_path / 'package')
