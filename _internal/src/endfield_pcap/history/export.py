"""Export a stable copy of a canonical trace for the official uploader."""
from __future__ import annotations
import json
import os
import re
import tempfile
from pathlib import Path
from uploader_core.log_integrity import (
    RAW_LOG_PROOF_BEGIN_PREFIX,
    RAW_LOG_PROOF_END,
    build_raw_log_proof,
    load_raw_log_integrity,
)


def export_trace_log(source: Path, destination: Path) -> dict:
    """Preserve raw trace text; append the distribution's local export proof.

    This is a snapshot export, not an attestation of server authenticity. Never
    add a proof to the growing capture file or re-seal a failed existing proof.
    """
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("请另存导出文件，不能覆盖正在写入的原始 trace")
    integrity = load_raw_log_integrity(str(source))
    if integrity["issues"] and integrity["issues"] != ["missing integrity proof"]:
        raise ValueError("原日志完整性校验失败：" + "；".join(integrity["issues"]))
    text = integrity["raw_content"]
    if not re.search(r"^\[\d{2}:\d{2}:\d{2}\.\d{3}\] HP_V2\s+#\d+\b", text, re.MULTILINE):
        raise ValueError("请选择含伤害记录的 trace_*.log；session_*.ndjson 不是 uploader 日志")
    proof = build_raw_log_proof(text.encode("utf-8"), file_name=destination.name,
        meta={"exporter": "endfield-pcap-gui", "source_file_name": source.name,
              "scope": "full_trace_snapshot"})
    separator = bool(text) and not text.endswith("\n")
    content = text + ("\n" if separator else "") + (
        f"{RAW_LOG_PROOF_BEGIN_PREFIX}{int(separator)}\n"
        f"{json.dumps(proof, ensure_ascii=False, sort_keys=True, indent=2)}\n"
        f"{RAW_LOG_PROOF_END}\n"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent,
                                         prefix=destination.name + ".", suffix=".tmp", delete=False) as stream:
            temp_path = Path(stream.name)
            stream.write(content.encode("utf-8"))
        # Uploader uses mtime as the reference date for time-only trace lines.
        # Retain the capture file's date when exporting a past day's logs.
        source_mtime = source.stat().st_mtime
        os.utime(temp_path, (source_mtime, source_mtime))
        temp_path.replace(destination)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return proof
