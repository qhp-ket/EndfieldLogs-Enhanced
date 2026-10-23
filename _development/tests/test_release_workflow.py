"""Source clones can restore data without losing overrides or collecting secrets."""
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from test_repository_inputs import tool


def resource_fixture(root):
    content = b'upstream resource'
    override = b'development override'
    kept = root / '_internal/data/local_semantics/team_energy_rules.json'
    kept.parent.mkdir(parents=True)
    kept.write_bytes(override)
    rows = [dict(path='data/base.json', bytes=len(content), sha256=hashlib.sha256(content).hexdigest(),
                 origin='official_3_0_12_unchanged'),
            dict(path='data/local_semantics/team_energy_rules.json', bytes=len(override),
                 sha256=hashlib.sha256(override).hexdigest(), origin='development_addition')]
    archive = root / 'baseline.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.writestr('EndfieldLogsClient/_internal/data/base.json', content)
        bundle.writestr('EndfieldLogsClient/_internal/data/local_semantics/team_energy_rules.json', b'obsolete')
        bundle.writestr('EndfieldLogsClient/_internal/secrets/client_privkey.pem', b'not requested')
        bundle.writestr('EndfieldLogsClient/_internal/uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe', b'official fixture')
    manifest = dict(files=rows, source_url='https://example.invalid/baseline.zip',
                    source_archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
    (root / '_internal/data/resource-manifest.json').write_text(json.dumps(manifest), encoding='utf8')
    return archive, kept, manifest


def test_resource_restore_is_offline_repeatable_and_does_not_copy_unrequested_secrets(tmp_path):
    resources = tool('prepare_resources')
    archive, kept, _ = resource_fixture(tmp_path)
    assert resources.prepare(tmp_path, check=True) == 2
    assert resources.prepare(tmp_path, archive=archive, offline=True) == 0
    assert kept.read_bytes() == b'development override'
    assert not (tmp_path / '_internal/secrets').exists()
    assert not (tmp_path / 'Uploader').exists()
    assert resources.prepare(tmp_path, offline=True) == 0
    assert resources.prepare(tmp_path, archive=archive, uploader=True, offline=True) == 0
    assert (tmp_path / 'Uploader/EndfieldLogsUploader/EndfieldLogsUploader.exe').read_bytes() == b'official fixture'


def test_restore_refuses_corrupt_archive_and_changed_development_override(tmp_path):
    resources = tool('prepare_resources')
    archive, kept, manifest = resource_fixture(tmp_path)
    kept.write_bytes(b'local edit')
    with pytest.raises(ValueError, match='Changed resource'):
        resources.prepare(tmp_path, archive=archive)
    kept.unlink()
    with pytest.raises(ValueError, match='Missing tracked development'):
        resources.prepare(tmp_path, archive=archive)
    kept.write_bytes(b'development override')
    archive.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='SHA-256'):
        resources.prepare(tmp_path, archive=archive)
    with pytest.raises(ValueError, match='Unsafe resource'):
        resources.resource_path(tmp_path, 'data/../../outside.json')


def test_version_update_and_artifact_identity_share_one_source(tmp_path, monkeypatch):
    release = tool('release')
    source = tmp_path / '_version.py'
    source.write_text("APP_NAME = 'EndfieldLogs'\n__version__ = '0.1.0-dev.1'\n", encoding='utf8')
    monkeypatch.setattr(release, 'VERSION_FILE', source)
    release.set_version('0.1.0-dev.2')
    assert release.identity() == ('EndfieldLogs', '0.1.0-dev.2')
    for invalid in ('v1.0.0', '1.0', '../1.0.0', '01.0.0', '1.0.0-dev.01'):
        with pytest.raises(ValueError):
            release.set_version(invalid)
    assert release.identity()[1] == '0.1.0-dev.2'


def test_builder_rejects_arbitrary_names_before_creating_a_directory(tmp_path, monkeypatch):
    from test_portable_packaging import builder
    monkeypatch.setattr(builder, 'RELEASES', tmp_path)
    with pytest.raises(ValueError, match='version file'):
        builder.stage_release('arbitrary-date-build')
    assert not list(tmp_path.iterdir())
