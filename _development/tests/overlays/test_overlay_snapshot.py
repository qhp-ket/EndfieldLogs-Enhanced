"""Execute the actual fallback renderer against a real canonical report."""
from app_test_support.paths import ROOT
import json
import subprocess
from parser_core.unified import parse_overlay_battle_snapshot_text


def test_web_and_qt_renderer_replace_canonical_state():
    root = ROOT
    fixture = root / "_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log"
    snapshot = parse_overlay_battle_snapshot_text(fixture.read_text(encoding="utf-8"))
    message = {"type": "analysis_snapshot", "schema_version": 1,
               "stream_id": "renderer-test", "sequence": 42, "snapshot": snapshot}
    result = subprocess.run(
        ["node", str(root / "_development/tests/overlays/overlay_snapshot.test.cjs")],
        input=json.dumps(message, ensure_ascii=True), text=True,
        capture_output=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
