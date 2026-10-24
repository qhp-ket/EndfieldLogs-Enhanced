from app_test_support.paths import ROOT
import json
import os
from pathlib import Path
from PySide6.QtCore import QEventLoop, QTimer
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

def wait_for_page(window, trigger):
    loop = QEventLoop()
    results = []
    def loaded(ok):
        results.append(ok)
        loop.quit()
    window.webview.loadFinished.connect(loaded)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(15_000)
    trigger()
    loop.exec()
    timer.stop()
    window.webview.loadFinished.disconnect(loaded)
    assert results == [True], "Qt WebEngine did not load the existing overlay page"

def read_dom(window):
    loop = QEventLoop()
    result = []
    def received(value):
        result.append(json.loads(value))
        loop.quit()
    window.webview.page().runJavaScript("JSON.stringify({damage: document.getElementById('totalDamage').textContent, dps: document.getElementById('totalDps').textContent, rows: document.getElementById('rows').children.length, quality: document.getElementById('footerText').textContent})", received)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5_000)
    loop.exec()
    timer.stop()
    assert result, "Qt WebEngine DOM callback timed out"
    return result[0]

def page_value(window, expression):
    loop = QEventLoop()
    results = []
    def received(value):
        results.append(json.loads(value))
        loop.quit()
    window.webview.page().runJavaScript("JSON.stringify(" + expression + ")", received)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(5000)
    loop.exec()
    timer.stop()
    assert results
    return results[0]
