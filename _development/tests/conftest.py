"""One Qt application per test session; isolated from the user's GUI profile."""
import os
from pathlib import Path
import pytest
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWebEngineCore import QWebEngineProfile
from PySide6.QtWidgets import QApplication

EVIDENCE = Path(os.environ.get("ENDFIELD_UI_EVIDENCE_DIR", str(Path(__file__).resolve().parents[2] / "_development/implementations/implementation-ui-20261021")))


def pytest_addoption(parser):
    group = parser.getgroup("capture-key", "Optional official capture-key checks")
    group.addoption("--with-capture-key", action="store_true", default=False,
                    help="Run tests requiring the externally supplied official capture key")
    group.addoption("--capture-key-path", type=Path,
                    default=Path(__file__).resolve().parents[2] / "_internal/secrets/client_privkey.pem",
                    help="Official capture key used only by explicitly enabled integration tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "requires_capture_key: opt-in check of the external official capture key")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("with_capture_key"):
        skip = pytest.mark.skip(reason="requires official capture key; run _development/run_tests.py capture-key")
        for item in items:
            if item.get_closest_marker("requires_capture_key"):
                item.add_marker(skip)


@pytest.fixture
def official_capture_key(request):
    if not request.config.getoption("with_capture_key"):
        pytest.skip("official capture-key checks require --with-capture-key")
    path = request.config.getoption("capture_key_path").resolve()
    if not path.is_file():
        pytest.fail("Official capture key is missing. Prepare _internal/secrets/client_privkey.pem "
                    "from a trusted official distribution or pass --capture-key-path. "
                    "See _development/docs/runtime-resources.md.", pytrace=False)
    return path


@pytest.fixture(scope="session")
def app():
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    # Offscreen has no Windows fallback-font integration; register the installed
    # CJK face explicitly so screenshots use the same readable text as the GUI.
    cjk_font = Path("C:/Windows/Fonts/msyh.ttc")
    if application.platformName() == "offscreen" and cjk_font.is_file():
        QFontDatabase.addApplicationFont(str(cjk_font))
    application.setStyle("Fusion")
    application.setFont(QFont("Microsoft YaHei UI", 10))
    profile = QWebEngineProfile.defaultProfile()
    root = EVIDENCE
    profile.setCachePath(str(root / "qt-cache"))
    profile.setPersistentStoragePath(str(root / "qt-storage"))
    return application
