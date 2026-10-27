from app_test_support.paths import ROOT
import json
import os
from pathlib import Path
from parser_core.unified import parse_overlay_battle_snapshot_text
from app_test_support.scenarios.combo import trigger

EVIDENCE = Path(os.environ.get("ENDFIELD_UI_EVIDENCE_DIR",
    str(ROOT / "_development/implementations/implementation-ui-20261021")))

def snapshot_message(sequence=1, snapshot=None):
    if snapshot is None:
        root = ROOT
        text = (root / "_internal/packages/parser_core/tests/fixtures/rdps_snapshot_contract.log").read_text(encoding="utf-8")
        snapshot = parse_overlay_battle_snapshot_text(text)
    return {"type": "analysis_snapshot", "schema_version": 1,
            "stream_id": "qt-test", "sequence": sequence, "snapshot": snapshot}
