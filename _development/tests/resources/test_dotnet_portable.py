"""Private-runtime layout, candidate inventory and ZIP integrity; no Qt required."""
from pathlib import Path
import importlib.util
import json
import tempfile
import sys
import unittest
from unittest.mock import patch
import zipfile

TOOL = Path(__file__).resolve().parents[2] / 'tools/build_dotnet_portable.py'
sys.path.insert(0, str(TOOL.parent))
SPEC = importlib.util.spec_from_file_location('build_dotnet_portable', TOOL)
portable = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portable)


class DotnetPortableTests(unittest.TestCase):
    def test_source_archive_keeps_wpf_style_dictionary(self):
        portable.copy_source(self.stage)
        resource = '_internal/dotnet/Desktop/Presentation/CompactControls.xaml'
        with zipfile.ZipFile(self.stage / portable.SOURCE) as bundle:
            self.assertEqual(bundle.read(resource), (portable.ROOT / resource).read_bytes())
            self.assertFalse(any('/obj/' in name or '/bin/' in name for name in bundle.namelist()))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.stage = self.root / 'candidate-0.2.1-csharp.1-windows-x64'
        self.stage.mkdir()
        (self.stage / 'file.txt').write_text('synthetic payload', encoding='utf8')
        (self.stage / portable.MANIFEST).write_text(json.dumps(dict(files=portable.inventory(self.stage))), encoding='utf8')

    def test_inventory_zip_extract_and_versioned_filename(self):
        archive = portable.package_zip(self.stage)
        self.assertEqual(archive.name, self.stage.name + '.zip')
        destination = self.root / 'fresh'
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(destination)
        self.assertEqual(portable.verify_zip(archive), portable.verify_tree(destination))
        self.assertTrue(Path(str(archive) + '.sha256').read_text().startswith(portable.digest(archive)))
        with self.assertRaises(FileExistsError):
            portable.package_zip(self.stage)

    def test_changed_and_extra_files_rejected(self):
        (self.stage / 'file.txt').write_text('changed', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'differs'):
            portable.verify_tree(self.stage)
        (self.stage / 'file.txt').write_text('synthetic payload', encoding='utf8')
        (self.stage / 'settings.json').write_text('{}', encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'differs'):
            portable.verify_tree(self.stage)

    def test_app_local_vc_runtime_requires_reviewed_size_and_hash(self):
        source = self.root / 'vcruntime140.dll'; source.write_bytes(b'synthetic signed runtime fixture')
        manifest = self.root / '_development/portable/dotnet-native.json'; manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(dict(files={'vcruntime140.dll': dict(bytes=source.stat().st_size, sha256=portable.digest(source))})), encoding='utf8')
        with patch.object(portable, 'ROOT', self.root):
            portable.copy_vc_runtime(self.stage, source)
            self.assertEqual((self.stage / portable.WEBP / 'vcruntime140.dll').read_bytes(), source.read_bytes())
            self.assertEqual((self.stage / 'licenses/Microsoft-VC-Runtime-manifest.json').read_bytes(), manifest.read_bytes())
            source.write_bytes(b'changed runtime')
            with self.assertRaisesRegex(ValueError, 'reviewed Microsoft VC runtime'):
                portable.copy_vc_runtime(self.stage, source)

    def test_comparison_reads_verified_legacy_qt_inventory(self):
        legacy = self.root / 'qt.zip'
        payload = self.stage / 'file.txt'
        row = dict(size=payload.stat().st_size, sha256=portable.digest(payload))
        with zipfile.ZipFile(legacy, 'w') as bundle:
            bundle.write(payload, 'qt/file.txt')
            bundle.writestr('qt/' + portable.MANIFEST, json.dumps(dict(files={'file.txt': row})))
        native = portable.package_zip(self.stage)
        comparison = portable.compare_packages(legacy, native)
        self.assertEqual(comparison['unchanged'], ['file.txt'])
        self.assertEqual([row['path'] for row in comparison['changed']], [portable.MANIFEST])
        self.assertEqual(comparison['summary']['previous_files'], 2)
        payload.write_text('modified after archive', encoding='utf8')
        self.assertEqual(portable.compare_packages(legacy, native), comparison)

    def test_zip_traversal_noncanonical_and_windows_device_paths(self):
        for name in ('../outside', '/root', 'C:/outside', 'data\\file', 'a/./b', 'a//b', 'con.txt', 'a/COM1', 'a/trailing. ', 'a\0b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                portable.member_path(name)

    def test_zip_payload_hash_checked_beyond_crc(self):
        archive = self.root / 'changed.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.write(self.stage / portable.MANIFEST, portable.MANIFEST)
            bundle.writestr('file.txt', 'synthetic payloae')  # Same length, valid CRC, different SHA-256.
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            portable.verify_zip(archive)

    def test_case_collisions_and_unlisted_zip_members_rejected(self):
        for collision in (False, True):
            with self.subTest(collision=collision):
                archive = self.root / ('collision.zip' if collision else 'extra.zip')
                with zipfile.ZipFile(archive, 'w') as bundle:
                    bundle.write(self.stage / portable.MANIFEST, portable.MANIFEST)
                    bundle.write(self.stage / 'file.txt', 'file.txt')
                    bundle.writestr('FILE.TXT' if collision else 'extra.txt', 'unexpected')
                with self.assertRaises(ValueError):
                    portable.verify_zip(archive)

    def test_unpinned_framework_and_wrong_version_inputs_rejected(self):
        publish = self.root / 'publish'; publish.mkdir()
        (publish / (portable.APP + '.runtimeconfig.json')).write_text(json.dumps(dict(runtimeOptions=dict(framework=dict(name='Microsoft.NETCore.App')))), encoding='utf8')
        version = portable.ET.parse(portable.ROOT / '_internal/dotnet/Directory.Build.props').findtext('.//Version')
        deps = dict(libraries={portable.APP + '/' + version: {}}, runtimeTarget=dict(name='net10.0/win-x64'))
        (publish / (portable.APP + '.deps.json')).write_text(json.dumps(deps), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'exact private framework'):
            portable.stage_package(publish, self.root / 'invalid', self.root / 'packages')
        deps['libraries'] = {}
        (publish / (portable.APP + '.deps.json')).write_text(json.dumps(deps), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'version or architecture'):
            portable.stage_package(publish, self.root / 'invalid', self.root / 'packages')
        self.assertFalse((self.root / 'invalid').exists())

    def publish_fixture(self):
        publish = self.root / 'publish'; publish.mkdir()
        version = portable.ET.parse(portable.ROOT / '_internal/dotnet/Directory.Build.props').findtext('.//Version')
        frameworks = [dict(name=name, version='10.0.14') for name in ('Microsoft.NETCore.App', 'Microsoft.WindowsDesktop.App')]
        (publish / (portable.APP + '.runtimeconfig.json')).write_text(json.dumps(dict(runtimeOptions=dict(frameworks=frameworks, rollForward='Disable'))), encoding='utf8')
        (publish / (portable.APP + '.deps.json')).write_text(json.dumps(dict(libraries={portable.APP + '/' + version: {}}, runtimeTarget=dict(name='net10.0/win-x64'))), encoding='utf8')
        for name in (portable.APP + '.dll', 'Google.Protobuf.dll', 'libwebpdemux.dll', 'libwebp.dll', 'libsharpyuv.dll'):
            path = publish / name; path.parent.mkdir(exist_ok=True); path.write_bytes(b'synthetic runtime')
        packages = self.root / 'packages'
        for framework in frameworks:
            name = framework['name']
            package = packages / (name.lower() + '.runtime.win-x64') / framework['version']
            (package / 'data').mkdir(parents=True)
            files = ['native/hostfxr.dll', 'native/coreclr.dll'] if name == 'Microsoft.NETCore.App' else [
                'lib/net10.0/PresentationFramework.dll', 'native/wpfgfx_cor3.dll', 'lib/net10.0/fr/PresentationFramework.resources.dll']
            (package / 'data/RuntimeList.xml').write_text('<FileList FrameworkName="' + name + '">' + ''.join(
                '<File Path="runtimes/win-x64/' + relative + '" Profile="WPF" />' for relative in files) +
                '<File Path="runtimes/win-x64/lib/net10.0/Forms.dll" Profile="WindowsForms" /></FileList>')
            files += ['lib/net10.0/' + name + suffix for suffix in ('.deps.json', '.runtimeconfig.json')]
            for relative in files:
                path = package / 'runtimes/win-x64' / relative
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'synthetic runtime')
            (package / 'runtimes/win-x64/lib/net10.0/Forms.dll').write_bytes(b'WinForms must be excluded')
            metadata = dict(targets={'framework': {'runtime-library': dict(runtime={'PresentationFramework.dll': {}, 'Forms.dll': {}},
                native={'wpfgfx_cor3.dll': {}}, resources={'fr/PresentationFramework.resources.dll': {}, 'fr/Forms.resources.dll': {}})}})
            (package / ('runtimes/win-x64/lib/net10.0/' + name + '.deps.json')).write_text(json.dumps(metadata))
        return publish, packages

    def test_publish_entrypoint_and_component_layout(self):
        publish, packages = self.publish_fixture()
        entry = publish / (portable.APP + '.exe'); entry.write_bytes(b'unrelocated apphost')
        target = self.root / 'nested'
        with self.assertRaisesRegex(ValueError, 'PortableAppHost=true'):
            portable.stage_package(publish, target, packages)
        self.assertFalse(target.exists())
        entry.write_bytes(b'fixture apphost\0' + str(portable.APPLICATION / (portable.APP + '.dll')).encode('utf8') + b'\0\x02\x00../dotnet\0')
        with patch.object(portable, 'copy_resources'), patch.object(portable, 'copy_source'), patch.object(portable, 'copy_vc_runtime'), patch.object(portable, 'copy_licenses'):
            portable.stage_package(publish, target, packages)
        self.assertEqual({path.name for path in target.iterdir() if path.is_file()}, {portable.APP + '.exe', portable.MANIFEST, 'README.zh-CN.md'})
        self.assertEqual((target / portable.DOTNET / 'shared/Microsoft.WindowsDesktop.App/10.0.14/fr/PresentationFramework.resources.dll').read_bytes(), b'synthetic runtime')
        self.assertTrue((target / portable.DOTNET / 'host/fxr/10.0.14/hostfxr.dll').is_file())
        self.assertFalse((target / portable.DOTNET / 'shared/Microsoft.NETCore.App/10.0.14/hostfxr.dll').exists())
        self.assertTrue((target / portable.APPLICATION / 'Google.Protobuf.dll').is_file())
        self.assertTrue((target / portable.WEBP / 'libwebpdemux.dll').is_file())
        self.assertTrue((target / portable.WEBP / 'libsharpyuv.dll').is_file())
        self.assertFalse((target / portable.APPLICATION / 'coreclr.dll').exists())
        framework = target / portable.DOTNET / 'shared/Microsoft.WindowsDesktop.App/10.0.14'
        self.assertFalse((framework / 'Forms.dll').exists())
        metadata = json.loads((framework / 'Microsoft.WindowsDesktop.App.deps.json').read_text())['targets']['framework']['runtime-library']
        self.assertEqual(set(metadata['runtime']), {'PresentationFramework.dll'})
        self.assertEqual(set(metadata['resources']), {'fr/PresentationFramework.resources.dll'})
        self.assertEqual((target / (portable.APP + '.exe')).read_bytes(), entry.read_bytes())
        self.assertFalse((target / portable.APPLICATION / (portable.APP + '.exe')).exists())
        archive = portable.package_zip(target)
        self.assertEqual(portable.verify_zip(archive), portable.verify_tree(target))

    def test_self_contained_output_and_framework_leaks_rejected(self):
        publish, packages = self.publish_fixture()
        entry = publish / (portable.APP + '.exe')
        entry.write_bytes(str(portable.APPLICATION / (portable.APP + '.dll')).encode('utf8') + b'\0\x02\x00../dotnet\0')
        (publish / 'coreclr.dll').write_bytes(b'framework outside its directory')
        with self.assertRaisesRegex(ValueError, 'Framework file leaked'):
            portable.stage_package(publish, self.root / 'leaked', packages)
        config = publish / (portable.APP + '.runtimeconfig.json')
        config.write_text(json.dumps(dict(runtimeOptions=dict(includedFrameworks=[dict(name='Microsoft.NETCore.App', version='10.0.14')]))))
        with self.assertRaisesRegex(ValueError, 'exact private framework'):
            portable.stage_package(publish, self.root / 'self-contained', packages)


if __name__ == '__main__':
    unittest.main()
