"""Opt-in official distribution resource checks; no capture or upload."""
import importlib.util
from pathlib import Path
import shutil
import pytest
from Crypto.PublicKey import RSA

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('capture_key_builder', ROOT / '_development/tools/build_portable.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
pytestmark = pytest.mark.requires_capture_key


def test_official_capture_key_matches_distribution_allowlist(tmp_path, official_capture_key):
    # A real PEM is required only here, never in the ordinary packaging suite.
    assert builder.digest(official_capture_key) == builder.CAPTURE_KEY_SHA256, (
        'Capture key does not match the verified official distribution; '
        'see _development/docs/runtime-resources.md'
    )
    key = RSA.import_key(official_capture_key.read_bytes())
    assert key.has_private(), 'The configured capture key must contain an RSA private key'
    target = tmp_path / '_internal/secrets/client_privkey.pem'
    target.parent.mkdir(parents=True)
    shutil.copy2(official_capture_key, target)
    assert builder.validate_tree(tmp_path) == [target]
