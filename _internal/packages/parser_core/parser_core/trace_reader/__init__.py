from pathlib import Path


def read_trace_name(path: str) -> str:
    return Path(path).name

