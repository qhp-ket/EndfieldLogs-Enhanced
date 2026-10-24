from __future__ import annotations
import logging
import os
import sys
from pathlib import Path


def runtime_log_directory(fallback: Path) -> Path:
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.FileHandler):
            path = Path(handler.baseFilename)
            if path.name in {'launcher.log', 'client.log'}:
                return path.parent
    return Path(fallback)


def configure_logging(level: str) -> None:
    handlers: list[logging.Handler] = []
    if getattr(sys, "stderr", None) is not None:
        handlers.append(logging.StreamHandler())
    if not any(isinstance(handler, logging.FileHandler) for handler in logging.getLogger().handlers):
        appdata_root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".endfield-pcap")
        log_path = appdata_root / "EndfieldPCAP" / "logs" / "client.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))

    root = logging.getLogger()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    for handler in handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            if any(isinstance(existing, logging.StreamHandler) and not isinstance(existing, logging.FileHandler)
                   for existing in root.handlers):
                continue
        handler.setFormatter(formatter)
        root.addHandler(handler)
