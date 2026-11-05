"""Assemble a portable C#/WPF candidate with a private, standard .NET installation.

The product never invokes Python. This development tool copies reviewed resources,
source and licenses, inventories every file, and verifies the resulting ZIP.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

from compile_resource_cache import write_cache

ROOT = Path(__file__).resolve().parents[2]
CAPTURE_KEY_SHA256 = 'b83257fadefe901f708386da11ffcde0eb0dee6450a6b56fc1b85e197cab1b56'
APP = 'EndfieldLogs-Enhanced'
MANIFEST = 'BUILD-MANIFEST.json'
APPLICATION = PurePosixPath('_internal/app')
DOTNET = PurePosixPath('_internal/dotnet')
WEBP = PurePosixPath('_internal/native/webp')
SOURCE = PurePosixPath('_internal/source/SOURCE.zip')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def member_path(value):
    path = PurePosixPath(value)
    if (not path.parts or path.is_absolute() or '..' in path.parts or '\\' in value
            or ':' in value or path.as_posix() != value or any(ord(char) < 32 for char in value)
            or any(part.endswith((' ', '.')) or part.split('.')[0].upper() in
                   {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}
                   for part in path.parts)):
        raise ValueError('Unsafe package member: ' + value)
    return path


def copy_file(source, target, expected=None):
    if source.is_symlink() or not source.is_file():
        raise ValueError('Missing or linked package input: ' + source.name)
    if expected and (source.stat().st_size != expected['bytes'] or digest(source) != expected['sha256']):
        raise ValueError('Package input hash mismatch: ' + source.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ValueError('Duplicate package member: ' + target.name)
    shutil.copyfile(source, target)


def inventory(directory):
    rows = []
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Package contains a link')
        if path.is_file() and path.relative_to(directory).as_posix() != MANIFEST:
            rows.append(dict(path=path.relative_to(directory).as_posix(), bytes=path.stat().st_size, sha256=digest(path)))
    return rows


def verify_tree(directory):
    manifest = json.loads((directory / MANIFEST).read_text(encoding='utf8'))
    rows = manifest['files']
    names = [row['path'] for row in rows]
    for name in names:
        member_path(name)
    if len(set(name.casefold() for name in names)) != len(names):
        raise ValueError('Duplicate manifest members')
    if inventory(directory) != rows:
        raise ValueError('Extracted package differs from manifest')
    return manifest


def verify_zip(archive):
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        names = [entry.filename for entry in entries]
        for name in names:
            member_path(name)
        if len(set(name.casefold() for name in names)) != len(names):
            raise ValueError('Duplicate ZIP members')
        if any(entry.is_dir() or (entry.external_attr >> 16) & 0o170000 == 0o120000 for entry in entries):
            raise ValueError('Unexpected directory/link ZIP entries')
        if bundle.testzip() is not None:
            raise ValueError('ZIP CRC mismatch')
        manifest = json.loads(bundle.read(MANIFEST))
        rows = manifest['files']
        if set(names) != {MANIFEST, *(row['path'] for row in rows)} or len(names) != len(rows) + 1:
            raise ValueError('ZIP inventory mismatch')
        for row in rows:
            member_path(row['path'])
            if bundle.getinfo(row['path']).file_size != row['bytes']:
                raise ValueError('ZIP size mismatch: ' + row['path'])
            with bundle.open(row['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256']:
                    raise ValueError('ZIP hash mismatch: ' + row['path'])
        return manifest


def copy_resources(stage):
    internal = ROOT / '_internal'
    manifest_path = internal / 'data/resource-manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    if manifest['schema_version'] != 2:
        raise ValueError('Expected reviewed runtime projection v2')
    for row in manifest['files']:
        path = member_path(row['path'])
        if path.parts[0] not in {'data', 'jsondata'}:
            raise ValueError('Unexpected runtime resource root')
        copy_file(internal / path, stage / '_internal' / path, row)
    copy_file(manifest_path, stage / '_internal/data/resource-manifest.json')
    # A derivative of the reviewed source, independently inventoried in BUILD-MANIFEST.
    # The runtime validates source/payload hashes and falls back to the original gzip.
    roots = stage / '_internal/data/local_static/buff/typed_roots.json.gz'
    write_cache(roots, Path(str(roots) + '.egr'))
    for name in ('skill_frame_rules.json', 'team_energy_rules.json'):
        if not (stage / '_internal/data/local_semantics' / name).is_file():
            raise ValueError('Required UI resource missing: ' + name)
    portraits = internal / 'data/ui/characters'
    portrait_manifest = json.loads((portraits / 'manifest.json').read_text(encoding='utf8'))
    for row in [*portrait_manifest['portraits'].values(), portrait_manifest['placeholder']]:
        path = member_path(row['path'])
        if len(path.parts) != 1 or path.suffix != '.png':
            raise ValueError('Invalid portrait resource')
        copy_file(portraits / path, stage / '_internal/data/ui/characters' / path, row)
    copy_file(portraits / 'manifest.json', stage / '_internal/data/ui/characters/manifest.json')
    native = internal / 'native'
    native_manifest = json.loads((native / 'manifest.json').read_text(encoding='utf8'))
    if set(native_manifest['files']) != {'SDL3.dll', 'SDL3-LICENSE.txt'}:
        raise ValueError('Unexpected native runtime members')
    for name, row in native_manifest['files'].items():
        copy_file(native / name, stage / '_internal/native/input' / name, row)
    copy_file(native / 'manifest.json', stage / '_internal/native/input/manifest.json')
    key = internal / 'secrets/client_privkey.pem'
    if digest(key) != CAPTURE_KEY_SHA256:
        raise ValueError('Approved shared capture resource hash mismatch')
    copy_file(key, stage / '_internal/secrets/client_privkey.pem')


def copy_source(stage):
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    names = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode('utf8').split('\0')
    projects = {'Core', 'Protocol', 'Native', 'Capture', 'Runtime', 'Desktop'}
    selected = []
    for name in sorted(set(filter(None, names))):
        path = PurePosixPath(name)
        if path.parts[:2] != ('_internal', 'dotnet') or not (ROOT / path).is_file():
            continue
        if len(path.parts) == 3 or path.parts[2] in projects:
            if path.suffix.lower() not in {'.cs', '.csproj', '.json', '.props', '.pb', '.rsp', '.config', '.manifest', '.xaml'}:
                continue
            selected.append(path)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        selected.append(PurePosixPath(name))
    # Keep corresponding source archived: IDE background builds must not add obj/bin to the installation tree.
    (stage / SOURCE).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(stage / SOURCE, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(selected):
            source = ROOT / path
            if source.is_symlink():
                raise ValueError('Linked source input')
            bundle.write(source, path.as_posix())
        bundle.writestr('README.zh-CN.md',
            '# C#／WPF 对应源码\n\n使用 .NET SDK 10.0.403，在本目录运行：\n\n'
            '```powershell\ndotnet publish _internal/dotnet/Desktop/EndfieldLogs.Desktop.csproj '
            '-c Release -r win-x64 --self-contained false -p:PublishSingleFile=false '
            '-p:PublishTrimmed=false -p:DebugType=None -p:DebugSymbols=false -p:PortableAppHost=true '
            f'-p:SourceRevisionId={revision}\n```\n\n'
            '从已构建目录重新发布时，先用相同参数执行 `dotnet build -t:Rebuild`，'
            '确保调试符号等构建选项生效。`SourceRevisionId` 固定对应源码提交的版本元数据；'
            '无 Git 目录也可按上述命令重建。\n\n'
            '发布后将 EXE 放在包根目录，应用程序集放入 `_internal/app/`，同版本 NuGet runtime pack 按标准 host/fxr、shared 框架结构放入 `_internal/dotnet/`。'
            '桌面框架依据 SDK RuntimeList.xml 选择 WPF profile，并同步生成仅包含所选文件的 deps 资产索引。'
            'SDK apphost 只搜索这份私有运行库，不依赖系统 .NET；WebP 及 VC 组件放入 `_internal/native/webp/`，SDL3 放入 `_internal/native/input/`。'
            '运行资源采用便携包中的 `_internal/data/`、`_internal/jsondata/`、`_internal/native/` 及批准的统一 RSA 资源。'
            '保留 `_internal/native/webp/vcruntime140.dll`；其来源、版本和哈希见 '
            '`licenses/Microsoft-VC-Runtime-manifest.json`。数据来源见许可与清单；真实游戏和 Npcap 为外部运行条件。\n')


def copy_licenses(stage, packages, frameworks):
    for source, target in [('LICENSE', 'EndfieldLogs-GPL-3.0.txt'), ('THIRD_PARTY_NOTICES.md', 'THIRD_PARTY_NOTICES.md'),
                           ('_development/portable/licenses/EndfieldLogs-MIT.txt', 'Upstream-MIT.txt'),
                           ('_development/portable/licenses/Upstream-THIRD_PARTY_NOTICES.md', 'Upstream-THIRD_PARTY_NOTICES.md')]:
        copy_file(ROOT / source, stage / 'licenses' / target)
    licensed = ROOT / '_development/portable/dotnet-licenses'
    manifest = json.loads((licensed / 'manifest.json').read_text(encoding='utf8'))
    for row in manifest['files']:
        path = member_path(row['path'])
        copy_file(licensed / path, stage / 'licenses' / path, row)
    copy_file(licensed / 'manifest.json', stage / 'licenses/source-manifest.json')
    for framework in frameworks:
        name = framework['name'].lower() + '.runtime.win-x64'
        package = packages / name / framework['version']
        files = ('LICENSE.TXT', 'THIRD-PARTY-NOTICES.TXT') if framework['name'] == 'Microsoft.NETCore.App' else ('LICENSE',)
        for filename in files:
            copy_file(package / filename, stage / 'licenses' / (framework['name'] + '-' + filename))


def copy_vc_runtime(stage, supplied=None):
    manifest_path = ROOT / '_development/portable/dotnet-native.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    expected = manifest['files']['vcruntime140.dll']
    if supplied is not None:
        candidates = [Path(supplied)]
    else:
        candidates = [ROOT / '_internal/native/vcruntime140.dll']
        vs = Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft Visual Studio'
        candidates.extend(sorted(vs.glob('*/BuildTools/VC/Redist/MSVC/*/x64/Microsoft.VC143.CRT/vcruntime140.dll')))
    source = next((path for path in candidates if path.is_file() and not path.is_symlink()
                   and path.stat().st_size == expected['bytes'] and digest(path) == expected['sha256']), None)
    if source is None:
        raise ValueError('Provide the reviewed Microsoft VC runtime via --vc-runtime; see dotnet-native.json')
    copy_file(source, stage / WEBP / 'vcruntime140.dll', expected)
    copy_file(manifest_path, stage / 'licenses/Microsoft-VC-Runtime-manifest.json')


def runtime_members(packages, frameworks):
    """Keep framework ownership and the SDK's WPF profile, including culture directories.

    Read the SDK's runtime packs instead of guessing ownership from DLL names.
    hostfxr belongs to the host, not a shared framework. SDKs/targeting packs are absent.
    """
    members = []
    for framework in frameworks:
        name, version = framework['name'], framework['version']
        member_path(name); member_path(version)
        if '/' in name or '/' in version:
            raise ValueError('Invalid framework identity')
        package = packages / (name.lower() + '.runtime.win-x64') / version
        root = ET.parse(package / 'data/RuntimeList.xml').getroot()
        if root.get('FrameworkName') != name:
            raise ValueError('Runtime pack identity mismatch: ' + name)
        framework_path = DOTNET / 'shared' / name / version
        for row in root:
            if name == 'Microsoft.WindowsDesktop.App' and 'WPF' not in row.get('Profile', '').split(';'):
                continue
            path = member_path(row.attrib['Path'])
            if len(path.parts) > 4 and path.parts[:4] == ('runtimes', 'win-x64', 'lib', 'net10.0'):
                relative = PurePosixPath(*path.parts[4:])
            elif path.parts[:3] == ('runtimes', 'win-x64', 'native'):
                relative = PurePosixPath(*path.parts[3:])
            else:
                raise ValueError('Unexpected runtime pack asset: ' + str(path))
            destination = framework_path / relative
            if str(relative) == 'hostfxr.dll':
                destination = DOTNET / 'host/fxr' / version / relative
            members.append((package / path, destination))
        for metadata in (name + '.deps.json', name + '.runtimeconfig.json'):
            members.append((package / 'runtimes/win-x64/lib/net10.0' / metadata, framework_path / metadata))
    return members


def copy_runtime(stage, members, frameworks):
    for source, destination in members:
        copy_file(source, stage / destination)
    # The shared-framework index originally describes WinForms as well as WPF.
    # Project its asset lists onto the SDK-selected WPF files, retaining original
    # identities and version metadata. Do not leave references to omitted assemblies.
    framework = next(row for row in frameworks if row['name'] == 'Microsoft.WindowsDesktop.App')
    directory = stage / DOTNET / 'shared' / framework['name'] / framework['version']
    path = directory / (framework['name'] + '.deps.json')
    metadata = json.loads(path.read_text(encoding='utf8'))
    for target in metadata['targets'].values():
        for library in target.values():
            for kind in ('runtime', 'native', 'resources'):
                if kind in library:
                    library[kind] = {asset: value for asset, value in library[kind].items()
                                     if (directory / member_path(asset)).is_file()}
    path.write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf8')


def stage_package(publish, target, packages, vc_runtime=None):
    if target.exists():
        raise ValueError('Use a fresh candidate directory; an existing artifact is never overwritten')
    config = json.loads((publish / (APP + '.runtimeconfig.json')).read_text(encoding='utf8'))['runtimeOptions']
    version = ET.parse(ROOT / '_internal/dotnet/Directory.Build.props').findtext('.//Version')
    dependencies = json.loads((publish / (APP + '.deps.json')).read_text(encoding='utf8'))
    if APP + '/' + version not in dependencies['libraries'] or not dependencies['runtimeTarget']['name'].endswith('/win-x64'):
        raise ValueError('Publish version or architecture differs from current source')
    frameworks = config.get('frameworks', [])
    if (config.get('includedFrameworks') or config.get('framework') or len(frameworks) != 2
            or {row['name'] for row in frameworks} != {'Microsoft.NETCore.App', 'Microsoft.WindowsDesktop.App'}
            or config.get('rollForward') != 'Disable'):
        raise ValueError('Publish with PortableAppHost=true and exact private framework versions')
    for name in (APP + '.exe', APP + '.dll'):
        if not (publish / name).is_file():
            raise ValueError('Missing application output: ' + name)
    entry = (publish / (APP + '.exe')).read_bytes()
    if ((str(APPLICATION / (APP + '.dll')).encode('utf8') + b'\0') not in entry
            or b'\x02\x00../dotnet\0' not in entry):
        raise ValueError('Publish with -p:PortableAppHost=true; the root EXE must target the private app and runtime')
    runtime = runtime_members(packages, frameworks)
    framework_names = {destination.name.casefold() for _, destination in runtime}
    target.mkdir(parents=True)
    for source in sorted(publish.rglob('*')):
        if not source.is_file():
            continue
        relative = source.relative_to(publish)
        lowered = relative.as_posix().lower()
        if (source.suffix.lower() not in {'.dll', '.exe', '.json', '.txt', '.dat'}
                or any(token in lowered for token in ('python', 'pyside', 'qt6', 'qt5', 'webengine', 'webview', 'chromium', '.dev-gui', 'settings.json'))):
            raise ValueError('Unexpected publish member: ' + relative.as_posix())
        if relative.name.casefold() in framework_names:
            raise ValueError('Framework file leaked into application publish output: ' + relative.as_posix())
        if relative.as_posix() == APP + '.exe':
            destination = target / relative
        elif relative.as_posix() in {'libwebp.dll', 'libwebpdemux.dll', 'libwebpmux.dll', 'libsharpyuv.dll'}:
            destination = target / WEBP / relative
        else:
            destination = target / APPLICATION / relative
        copy_file(source, destination)
    copy_runtime(target, runtime, frameworks)
    copy_resources(target)
    copy_vc_runtime(target, vc_runtime)
    copy_source(target)
    copy_licenses(target, packages, frameworks)
    copy_file(ROOT / '_development/portable/README.csharp.zh-CN.md', target / 'README.zh-CN.md')
    manifest = dict(schema_version=1, component='csharp-wpf-candidate', version=version, runtime='win-x64-private-dotnet', layout='private-frameworks-v1', frameworks=frameworks,
                    framework_profiles={'Microsoft.WindowsDesktop.App': 'WPF'},
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    source_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT)),
                    files=inventory(target))
    (target / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    verify_tree(target)
    return manifest


def package_zip(stage):
    verify_tree(stage)
    archive = Path(str(stage) + '.zip')
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for source in sorted(stage.rglob('*')):
            if source.is_file():
                bundle.write(source, source.relative_to(stage).as_posix())
    verify_zip(archive)
    archive.with_suffix('.zip.sha256').write_text(digest(archive) + '  ' + archive.name + '\n', encoding='ascii')
    return archive


def zip_inventory(archive):
    """Read and check both the historical Qt inventory and the native candidate inventory."""
    with zipfile.ZipFile(archive) as bundle:
        manifests = [name for name in bundle.namelist() if name.endswith(MANIFEST)]
        if len(manifests) != 1:
            raise ValueError('Expected one package manifest')
        manifest_name = manifests[0]; prefix = manifest_name[:-len(MANIFEST)]
        raw = bundle.read(manifest_name); manifest = json.loads(raw)
        rows = manifest['files']
        if isinstance(rows, dict):
            rows = [dict(path=name, bytes=row['size'], sha256=row['sha256']) for name, row in rows.items()]
        expected = {prefix + row['path'] for row in rows} | {manifest_name}
        actual = [item.filename for item in bundle.infolist() if not item.is_dir()]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError('Comparison ZIP inventory mismatch')
        result = {}
        for row in rows:
            member_path(row['path'])
            with bundle.open(prefix + row['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != row['sha256'] or bundle.getinfo(prefix + row['path']).file_size != row['bytes']:
                    raise ValueError('Comparison ZIP hash/size mismatch: ' + row['path'])
            result[row['path']] = row
        result[MANIFEST] = dict(path=MANIFEST, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        return result


def compare_packages(previous, candidate):
    before, after = zip_inventory(previous), zip_inventory(candidate)
    common = before.keys() & after.keys()
    result = dict(added=sorted(after.keys() - before.keys()), removed=sorted(before.keys() - after.keys()),
                  changed=[dict(path=name, before=before[name], after=after[name]) for name in sorted(common) if before[name] != after[name]],
                  unchanged=sorted(name for name in common if before[name] == after[name]))
    result['summary'] = dict(previous_files=len(before), candidate_files=len(after), added=len(result['added']), removed=len(result['removed']),
                             changed=len(result['changed']), unchanged=len(result['unchanged']), previous_zip_bytes=previous.stat().st_size,
                             candidate_zip_bytes=candidate.stat().st_size, previous_extracted_bytes=sum(row['bytes'] for row in before.values()),
                             candidate_extracted_bytes=sum(row['bytes'] for row in after.values()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-directory', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--packages', type=Path, default=ROOT / '.nuget/packages')
    parser.add_argument('--vc-runtime', type=Path, help='Reviewed app-local vcruntime140.dll; defaults to local resource or VS redist')
    args = parser.parse_args()
    stage = args.target.resolve()
    manifest = stage_package(args.publish_directory.resolve(), stage, args.packages.resolve(), args.vc_runtime)
    archive = package_zip(stage)
    print(json.dumps(dict(files=len(manifest['files']), extracted_bytes=sum(row['bytes'] for row in manifest['files']), zip_bytes=archive.stat().st_size,
                          zip_sha256=digest(archive), source_dirty=manifest['source_dirty']), indent=2))


if __name__ == '__main__':
    main()
