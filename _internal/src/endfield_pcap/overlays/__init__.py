"""Overlay renderers; configure Chromium before importing any host."""
import os


os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS",
    "--disable-gpu --disable-gpu-compositing --disable-software-rasterizer "
    "--disable-features=VizDisplayCompositor --no-sandbox",
)

os.environ.setdefault("QT_OPENGL", "software")

for _capture_flag in ('--disable-backgrounding-occluded-windows',
                      '--disable-renderer-backgrounding', '--disable-background-timer-throttling'):
    if _capture_flag not in os.environ['QTWEBENGINE_CHROMIUM_FLAGS'].split():
        os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] += ' ' + _capture_flag
