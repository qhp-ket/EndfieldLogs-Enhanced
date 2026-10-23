from parser_core import (
    INTEGRITY_VERSION,
    build_canonical_sha256,
    build_integrity_record,
    verify_server_seal,
)


def test_canonical_sha256_changes_after_payload_mutation() -> None:
    left = {"battle": {"bossName": "罗丹", "durationMs": 12345}, "participants": [{"name": "安塔尔", "dps": 1}]}
    right = {"battle": {"bossName": "罗丹", "durationMs": 12345}, "participants": [{"name": "安塔尔", "dps": 2}]}
    assert build_canonical_sha256(left) != build_canonical_sha256(right)


def test_server_seal_verification_detects_tampering() -> None:
    payload = {"battle": {"bossName": "罗丹", "durationMs": 12345}, "participants": [{"name": "安塔尔", "dps": 1}]}
    proof = build_integrity_record(payload, secret="secret-key")
    assert proof["version"] == INTEGRITY_VERSION
    assert proof["seal_algorithm"] == "hmac-sha256"
    assert proof["server_seal"] is not None
    assert verify_server_seal(payload, "secret-key", proof["server_seal"] or "") is True

    tampered = {"battle": {"bossName": "罗丹", "durationMs": 99999}, "participants": [{"name": "安塔尔", "dps": 1}]}
    assert verify_server_seal(tampered, "secret-key", proof["server_seal"] or "") is False
