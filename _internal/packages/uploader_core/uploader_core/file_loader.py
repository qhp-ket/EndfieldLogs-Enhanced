from pathlib import Path

from uploader_core.log_integrity import load_raw_log_integrity

def read_trace_preview(path: str) -> str:
    return Path(path).name


def read_trace_preview_with_integrity(path: str) -> dict:
    return {
        "file_name": Path(path).name,
        "integrity": load_raw_log_integrity(path),
    }
