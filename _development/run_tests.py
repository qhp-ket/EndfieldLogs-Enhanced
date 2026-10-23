"""Run current application/core suites with workspace-local dependencies."""
import contextlib
import os
from pathlib import Path
import sys
import ctypes
import uuid

# Isolated native Qt crashes must return an exit code, never leave WER dialogs
# on the user's desktop. This applies only to this verification process.
if sys.platform == "win32":
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parents[1]
output = root / "_development/verification"
output.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root / '_internal/src'))
from endfield_pcap.environment_paths import configure_paths
dll_directories = configure_paths(root)
sys.path.insert(0, str(root / '_internal/packages/parser_core/tests'))
os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
os.environ["ENDFIELD_LOGS_DATA_ROOT"] = str(root / "_internal")
os.environ["ENDFIELD_UI_EVIDENCE_DIR"] = str(output)
os.environ["QT_QPA_PLATFORM"] = os.environ.get("ENDFIELD_UI_TEST_PLATFORM", "offscreen")
os.environ["LOCALAPPDATA"] = str(output / "test-profile/local")
os.environ["APPDATA"] = str(output / "test-profile/roaming")
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu --disable-dev-shm-usage"

if __name__ == "__main__":
    import pytest

    target = sys.argv[1] if len(sys.argv) > 1 else "live"
    tests = root / "_development/tests" if target in {"live", "visual", "controls"} else root / f"_internal/packages/{target}/tests"
    if target in {'official-parser_core', 'official-uploader_core', 'baseline-parser_core'}:
        package = target.removeprefix('official-').removeprefix('baseline-')
        tests = root / f'_development/official-release/EndfieldLogsClient/_internal/packages/{package}/tests'
        sys.path.insert(0, str(tests))
        if target.startswith('baseline-'):
            baseline = root / '_development/official-release/EndfieldLogsClient/_internal'
            sys.path[:0] = [str(baseline / 'packages/parser_core'), str(baseline / 'packages/uploader_core')]
            os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(baseline)
    if target == 'official-uploader-gui':
        app = root / '_development/audits/audit-20261021/upstream/endfield-suite-open/endfield-logs/apps/uploader'
        baseline = root / '_development/official-release/EndfieldLogsClient/_internal'
        tests = app / 'tests'
        sys.path[:0] = [str(app), str(baseline / 'packages/parser_core'), str(baseline / 'packages/uploader_core')]
        os.environ['ENDFIELD_LOGS_DATA_ROOT'] = str(baseline)
    if target == "controls":
        tests = tests / "test_overlay_controls.py"
    extra_args = []
    if target == "capture-key":
        tests = root / '_development/tests/integration'
        extra_args = ['--with-capture-key', '-m', 'requires_capture_key']
    log = output / f"{target}-tests.txt"
    with log.open("w", encoding="utf-8") as stream:
        with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
            print(f"Python: {sys.version}; pytest: {pytest.__version__}")
            result = pytest.main([
                str(tests), "-q", "-ra", "-p", "no:cacheprovider",
                "--basetemp", str(output / f"{target}-tmp-{uuid.uuid4().hex[:10]}"),
                "--junitxml", str(output / f"{target}-junit.xml"),
                *extra_args,
                *sys.argv[2:],
            ])
    print(f"{target}: exit={result}; log={log}")
    print("\n".join(log.read_text(encoding="utf-8").splitlines()[-10:]))
    raise SystemExit(int(result))
