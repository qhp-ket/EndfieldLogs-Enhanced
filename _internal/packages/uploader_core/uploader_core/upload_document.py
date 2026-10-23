from __future__ import annotations

import json
from pathlib import Path

from uploader_core.log_integrity import load_raw_log_integrity


def build_raw_log_upload_document(log_path: str) -> dict:
    path = Path(log_path)
    integrity = load_raw_log_integrity(log_path)
    content = str(integrity.get("raw_content") or "")
    issues = list(integrity.get("issues") or [])
    proof = integrity.get("proof")
    return {
        "file_name": path.name,
        "content": content,
        "proof": proof,
        "integrity_gate": {
            "tamper_suspected": not bool(integrity.get("verified")),
            "integrity_proof_present": proof is not None,
            "reasons": issues,
        },
    }


def build_raw_log_upload_document_json(log_path: str) -> str:
    return json.dumps(build_raw_log_upload_document(log_path), ensure_ascii=False, sort_keys=True)
