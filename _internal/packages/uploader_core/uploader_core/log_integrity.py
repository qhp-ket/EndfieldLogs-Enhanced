from __future__ import annotations

import hashlib
import hmac
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


RAW_LOG_PROOF_VERSION = "raw-log-proof-v1"
RAW_LOG_PROOF_SOURCE = "endfield-dps-overlay"
RAW_LOG_SEAL_ALGORITHM = "hmac-sha256(local)"
RAW_LOG_LOADOUT_BEGIN_PREFIX = "## ENDFIELD_LOADOUT_SUMMARY_BEGIN sep="
RAW_LOG_LOADOUT_END = "## ENDFIELD_LOADOUT_SUMMARY_END"
RAW_LOG_PROOF_BEGIN_PREFIX = "## ENDFIELD_RAW_LOG_INTEGRITY_BEGIN sep="
RAW_LOG_PROOF_END = "## ENDFIELD_RAW_LOG_INTEGRITY_END"
_CHAIN_SEED = b"endfield-raw-log-chain-v1"
# Keep the original seal seed stable for backward compatibility with
# already-exported sidecar proofs. Embedded proofs reuse the same seal scheme.
_LOCAL_SEAL_KEY = hashlib.sha256(
    b"endfield|meter|raw-log-proof|2026-04|sidecar"
).digest()
_BEGIN_RE = re.compile(r"^## ENDFIELD_RAW_LOG_INTEGRITY_BEGIN sep=(?P<sep>[01])$")
_LOADOUT_BEGIN_RE = re.compile(r"^## ENDFIELD_LOADOUT_SUMMARY_BEGIN sep=(?P<sep>[01])$")


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    return value


def _canonical_json(payload: dict[str, Any]) -> str:
    normalized = _normalize(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_raw_log_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_raw_log_chain_sha256(data: bytes) -> str:
    acc = _CHAIN_SEED
    for idx, line in enumerate(data.splitlines(keepends=True)):
        hasher = hashlib.sha256()
        hasher.update(acc)
        hasher.update(idx.to_bytes(4, "big", signed=False))
        hasher.update(line)
        acc = hasher.digest()
    return hashlib.sha256(acc).hexdigest()


def build_raw_log_proof(
    data: bytes,
    *,
    file_name: str | None = None,
    exported_at: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "version": RAW_LOG_PROOF_VERSION,
        "source": RAW_LOG_PROOF_SOURCE,
        "file_name": file_name,
        "exported_at": exported_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "byte_size": len(data),
        "line_count": len(data.splitlines(keepends=True)),
        "sha256": build_raw_log_sha256(data),
        "chain_sha256": build_raw_log_chain_sha256(data),
        "meta": meta or {},
    }
    local_seal = hmac.new(
        _LOCAL_SEAL_KEY,
        _canonical_json(payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    payload["seal_algorithm"] = RAW_LOG_SEAL_ALGORITHM
    payload["local_seal"] = local_seal
    return payload


def verify_raw_log_proof(data: bytes, proof: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    computed = {
        "byte_size": len(data),
        "line_count": len(data.splitlines(keepends=True)),
        "sha256": build_raw_log_sha256(data),
        "chain_sha256": build_raw_log_chain_sha256(data),
    }
    if proof.get("version") != RAW_LOG_PROOF_VERSION:
        issues.append("proof.version mismatch")
    if proof.get("source") != RAW_LOG_PROOF_SOURCE:
        issues.append("proof.source mismatch")
    if proof.get("byte_size") != computed["byte_size"]:
        issues.append("proof.byte_size mismatch")
    if proof.get("line_count") != computed["line_count"]:
        issues.append("proof.line_count mismatch")
    if proof.get("sha256") != computed["sha256"]:
        issues.append("proof.sha256 mismatch")
    if proof.get("chain_sha256") != computed["chain_sha256"]:
        issues.append("proof.chain_sha256 mismatch")
    expected_payload = {
        "version": proof.get("version"),
        "source": proof.get("source"),
        "file_name": proof.get("file_name"),
        "exported_at": proof.get("exported_at"),
        "byte_size": proof.get("byte_size"),
        "line_count": proof.get("line_count"),
        "sha256": proof.get("sha256"),
        "chain_sha256": proof.get("chain_sha256"),
        "meta": proof.get("meta") or {},
    }
    expected_seal = hmac.new(
        _LOCAL_SEAL_KEY,
        _canonical_json(expected_payload).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if proof.get("seal_algorithm") != RAW_LOG_SEAL_ALGORITHM:
        issues.append("proof.seal_algorithm mismatch")
    if not hmac.compare_digest(str(proof.get("local_seal") or ""), expected_seal):
        issues.append("proof.local_seal mismatch")
    return {
        "verified": not issues,
        "issues": issues,
        "computed": computed,
    }


def _split_embedded_raw_log(text: str) -> tuple[str, dict[str, Any] | None, str | None]:
    begin_idx = text.rfind(RAW_LOG_PROOF_BEGIN_PREFIX)
    if begin_idx < 0:
        return text, None, None

    begin_line_end = text.find("\n", begin_idx)
    if begin_line_end < 0:
        return text, None, "embedded proof begin marker incomplete"

    begin_line = text[begin_idx:begin_line_end]
    match = _BEGIN_RE.match(begin_line)
    if not match:
        return text, None, "embedded proof begin marker malformed"

    end_marker = "\n" + RAW_LOG_PROOF_END
    end_idx = text.find(end_marker, begin_line_end + 1)
    if end_idx < 0:
        return text, None, "embedded proof end marker missing"

    proof_text = text[begin_line_end + 1:end_idx]
    try:
        proof = json.loads(proof_text)
    except json.JSONDecodeError:
        return text, None, "embedded proof json malformed"

    raw_text = text[:begin_idx]
    if match.group("sep") == "1" and raw_text.endswith("\n"):
        raw_text = raw_text[:-1]
    return raw_text, proof, None


def _strip_embedded_loadout_summary(text: str) -> tuple[str, str | None]:
    begin_idx = text.rfind(RAW_LOG_LOADOUT_BEGIN_PREFIX)
    if begin_idx < 0:
        return text, None

    begin_line_end = text.find("\n", begin_idx)
    if begin_line_end < 0:
        return text, "embedded loadout begin marker incomplete"

    begin_line = text[begin_idx:begin_line_end]
    match = _LOADOUT_BEGIN_RE.match(begin_line)
    if not match:
        return text, "embedded loadout begin marker malformed"

    end_marker = "\n" + RAW_LOG_LOADOUT_END
    end_idx = text.find(end_marker, begin_line_end + 1)
    if end_idx < 0:
        return text, "embedded loadout end marker missing"

    raw_text = text[:begin_idx]
    if match.group("sep") == "1" and raw_text.endswith("\n"):
        raw_text = raw_text[:-1]
    return raw_text, None


def find_raw_log_proof_path(log_path: str) -> Path | None:
    path = Path(log_path)
    candidates = [
        Path(str(path) + ".integrity.json"),
        path.with_suffix(".integrity.json"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def load_raw_log_integrity(log_path: str) -> dict[str, Any]:
    full_bytes = Path(log_path).read_bytes()
    full_text = full_bytes.decode("utf-8")
    proof_stripped_text, embedded_proof, embedded_issue = _split_embedded_raw_log(full_text)
    raw_text, embedded_loadout_issue = _strip_embedded_loadout_summary(proof_stripped_text)
    data = raw_text.encode("utf-8")
    if embedded_issue is not None or embedded_loadout_issue is not None:
        issues = []
        if embedded_issue is not None:
            issues.append(embedded_issue)
        if embedded_loadout_issue is not None:
            issues.append(embedded_loadout_issue)
        return {
            "verified": False,
            "issues": issues,
            "proof_path": "<embedded>",
            "proof_source": "embedded",
            "proof": None,
            "raw_content": raw_text,
            "computed": {
                "byte_size": len(data),
                "line_count": len(data.splitlines(keepends=True)),
                "sha256": build_raw_log_sha256(data),
                "chain_sha256": build_raw_log_chain_sha256(data),
            },
        }
    if embedded_proof is not None:
        result = verify_raw_log_proof(data, embedded_proof)
        result["proof_path"] = "<embedded>"
        result["proof_source"] = "embedded"
        result["proof"] = embedded_proof
        result["raw_content"] = raw_text
        return result

    proof_path = find_raw_log_proof_path(log_path)
    if proof_path is None:
        return {
            "verified": False,
            "issues": ["missing integrity proof"],
            "proof_path": None,
            "proof_source": None,
            "proof": None,
            "raw_content": raw_text,
            "computed": {
                "byte_size": len(data),
                "line_count": len(data.splitlines(keepends=True)),
                "sha256": build_raw_log_sha256(data),
                "chain_sha256": build_raw_log_chain_sha256(data),
            },
        }
    proof = json.loads(proof_path.read_text(encoding="utf-8"))
    result = verify_raw_log_proof(data, proof)
    result["proof_path"] = str(proof_path)
    result["proof_source"] = "sidecar"
    result["proof"] = proof
    result["raw_content"] = raw_text
    return result
