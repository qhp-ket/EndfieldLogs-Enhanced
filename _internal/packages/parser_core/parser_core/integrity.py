from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any


INTEGRITY_VERSION = "battle-struct-v1"


def _normalize(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return _normalize(value.model_dump(mode="json"))
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def build_canonical_json(payload: Any) -> str:
    normalized = _normalize(payload)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_canonical_sha256(payload: Any) -> str:
    canonical_json = build_canonical_json(payload)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def build_server_seal(payload: Any, secret: str) -> str:
    canonical_json = build_canonical_json(payload)
    return hmac.new(secret.encode("utf-8"), canonical_json.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_server_seal(payload: Any, secret: str, seal: str) -> bool:
    expected = build_server_seal(payload, secret)
    return hmac.compare_digest(expected, seal)


def build_integrity_record(payload: Any, secret: str | None = None) -> dict[str, str | None]:
    record: dict[str, str | None] = {
        "version": INTEGRITY_VERSION,
        "canonical_sha256": build_canonical_sha256(payload),
        "seal_algorithm": None,
        "server_seal": None,
    }
    if secret:
        record["seal_algorithm"] = "hmac-sha256"
        record["server_seal"] = build_server_seal(payload, secret)
    return record
