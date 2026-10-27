from __future__ import annotations
import logging
from typing import Any
from endfield_pcap.crypto.xxe1 import XXE1
from endfield_pcap.capture.registry import MessageDecodeFailure
from endfield_pcap.models import BattleLogEvent
from endfield_pcap.capture.protocol import (
    SessionBodyDecompressionError,
    maybe_decompress_session_body,
    parse_head,
    parse_sc_login,
    pop_frame,
    rsa_decrypt_session_key,
)


LOGGER = logging.getLogger(__name__)


class FramingEvents:
    def _note_tcp_gap(self, timestamp_ms: int, direction: str, missing_bytes: int) -> None:
        if self.first_packet_ts_ms is None:
            return
        if timestamp_ms - self.first_packet_ts_ms > 5000:
            return
        self.startup_tcp_gap_count += 1
        self.startup_tcp_gap_max_missing_bytes = max(self.startup_tcp_gap_max_missing_bytes, int(missing_bytes))
        self.reliability_flags.add("startup_tcp_gap")
        if self.startup_tcp_gap_max_missing_bytes >= 4096:
            self.reliability_flags.add("startup_tcp_gap_large")
        if self._startup_gap_warning_emitted:
            return
        self._startup_gap_warning_emitted = True
        self._emit_event(
            BattleLogEvent(
                session_id=self.session_id,
                timestamp_ms=timestamp_ms,
                event_type="SESSION_WARNING",
                payload={
                    "kind": "startup_tcp_gap",
                    "direction": direction,
                    "missing_bytes": int(missing_bytes),
                    "startup_tcp_gap_count": self.startup_tcp_gap_count,
                },
            )
        )

    def _drain_direction(self, direction: str, timestamp_ms: int) -> None:
        buffer = self.client_buffer if direction == "cs" else self.server_buffer
        while True:
            frame = pop_frame(buffer)
            if frame is None:
                return
            head_len, head_bytes, payload = frame
            if direction == "cs" and not self.client_login_done:
                self.client_login_done = True
                continue
            if direction == "sc" and not self.server_login_done:
                plain = self.srsa_bridge.decrypt_login_body(payload)
                login_info = parse_sc_login(plain)
                session_key = rsa_decrypt_session_key(self.private_key, login_info["session_key_encrypted"])
                nonce = login_info["session_nonce"]
                self.client_cipher = XXE1(session_key, nonce, counter=1)
                self.server_cipher = XXE1(session_key, nonce, counter=1)
                self.server_login_done = True
                self._drain_pending_client_session_frames()
                continue
            cipher = self.client_cipher if direction == "cs" else self.server_cipher
            if cipher is None:
                if direction == "cs":
                    self.pending_client_session_frames.append((head_len, head_bytes, payload, timestamp_ms))
                continue
            self._decode_session_frame(direction, head_len, head_bytes, payload, timestamp_ms)

    def _drain_pending_client_session_frames(self) -> None:
        while self.pending_client_session_frames and self.client_cipher is not None:
            head_len, head_bytes, payload, timestamp_ms = self.pending_client_session_frames.popleft()
            self._decode_session_frame("cs", head_len, head_bytes, payload, timestamp_ms)

    def _decode_session_frame(
        self,
        direction: str,
        head_len: int,
        head_bytes: bytes,
        payload: bytes,
        timestamp_ms: int,
    ) -> None:
        cipher = self.client_cipher if direction == "cs" else self.server_cipher
        if cipher is None:
            return
        plain = cipher.process(head_bytes + payload)
        plain_head = plain[:head_len]
        plain_body = plain[head_len:]
        head = parse_head(plain_head)
        if self.on_debug_record is not None and "parse_error" in head:
            self.on_debug_record(
                {
                    "type": "debug_frame_error",
                    "session_id": self.session_id,
                    "timestamp_ms": timestamp_ms,
                    "direction": direction,
                    "error": head["parse_error"],
                    "head_len": head_len,
                    "plain_head_hex": plain_head.hex(),
                    "plain_body_prefix_hex": plain_body[:64].hex(),
                }
            )
        if "parse_error" in head:
            return
        self._record_session_head(direction, head_len, plain_head, plain_body, head, timestamp_ms)
        try:
            assembled = self._assemble_multi_pack_message(direction, head, plain_body, timestamp_ms)
        except SessionBodyDecompressionError as exc:
            self.metrics.decompression_errors += 1
            self.reliability_flags.add("session_body_decompression_failed")
            LOGGER.error("session frame decompression failed", exc_info=True)
            if self.on_debug_record is not None:
                self.on_debug_record(
                    {
                        "type": "debug_decompression_error",
                        "session_id": self.session_id,
                        "timestamp_ms": timestamp_ms,
                        "direction": direction,
                        "msg_id": int(head.get("msgid", 0) or 0),
                        "error": str(exc),
                        "head": head,
                        "body_len": len(plain_body),
                        "body_prefix_hex": plain_body[:128].hex(),
                    }
                )
            return
        if assembled is None:
            return
        head, body, is_already_decompressed = assembled
        msg_id = int(head.get("msgid", 0) or 0)
        if not self.registry.should_decode_message(direction, msg_id):
            self._record_ignored_frame(direction, head, body, is_already_decompressed, timestamp_ms)
            return
        decoded = self._decode_frame_body(direction, head, body, is_already_decompressed, timestamp_ms)
        if decoded is None:
            return
        decoded_messages, body = decoded
        self.metrics.frames_decoded += 1
        if self.on_debug_record is not None and not decoded_messages:
            self.on_debug_record(
                {
                    "type": "debug_undecoded_frame",
                    "session_id": self.session_id,
                    "timestamp_ms": timestamp_ms,
                    "direction": direction,
                    "head": head,
                    "head_len": head_len,
                    "plain_head_hex": plain_head.hex(),
                    "plain_body_prefix_hex": body[:128].hex(),
                }
            )
        for decoded in decoded_messages:
            self.metrics.messages_decoded += 1
            self._handle_message(decoded, timestamp_ms)

    def _record_session_head(self, direction, head_len, plain_head, plain_body, head, timestamp_ms):
        if self.on_debug_record is not None:
            msg_id = int(head.get("msgid", 0) or 0)
            self.on_debug_record(
                {
                    "type": "debug_session_head",
                    "session_id": self.session_id,
                    "timestamp_ms": timestamp_ms,
                    "direction": direction,
                    "msg_id": msg_id,
                    "class_name": self.registry.resolve_class_name(direction, msg_id),
                    "head": head,
                    "head_len": head_len,
                    "plain_head_hex": plain_head.hex(),
                    "plain_body_len": len(plain_body),
                    "plain_body_prefix_hex": plain_body[:64].hex(),
                    "plain_body_hex": plain_body.hex() if len(plain_body) <= 4096 else None,
                }
            )

    def _record_ignored_frame(self, direction, head, body, is_already_decompressed, timestamp_ms):
        if self.on_debug_record is not None:
            msg_id = int(head.get("msgid", 0) or 0)
            try:
                debug_body = body if is_already_decompressed else maybe_decompress_session_body(head, body)
            except SessionBodyDecompressionError as exc:
                debug_body = body
                self.metrics.decompression_errors += 1
                self.reliability_flags.add("session_body_decompression_failed")
                LOGGER.error("ignored session frame decompression failed", exc_info=True)
                self.on_debug_record(
                    {
                        "type": "debug_decompression_error",
                        "session_id": self.session_id,
                        "timestamp_ms": timestamp_ms,
                        "direction": direction,
                        "msg_id": msg_id,
                        "error": str(exc),
                        "head": head,
                        "body_len": len(body),
                        "body_prefix_hex": body[:128].hex(),
                    }
                )
            self.on_debug_record(
                {
                    "type": "debug_ignored_frame",
                    "session_id": self.session_id,
                    "timestamp_ms": timestamp_ms,
                    "direction": direction,
                    "msg_id": msg_id,
                    "class_name": self.registry.resolve_class_name(direction, msg_id),
                    "head": head,
                    "body_len": len(debug_body),
                    "body_prefix_hex": debug_body[:128].hex(),
                    "body_hex": debug_body.hex() if len(debug_body) <= 8192 else None,
                }
            )
        return

    def _decode_frame_body(self, direction, head, body, is_already_decompressed, timestamp_ms):
        msg_id = int(head.get("msgid", 0) or 0)
        if not is_already_decompressed:
            try:
                body = maybe_decompress_session_body(head, body)
            except SessionBodyDecompressionError as exc:
                self.metrics.decompression_errors += 1
                self.reliability_flags.add("session_body_decompression_failed")
                LOGGER.error("session frame decompression failed", exc_info=True)
                if self.on_debug_record is not None:
                    self.on_debug_record(
                        {
                            "type": "debug_decompression_error",
                            "session_id": self.session_id,
                            "timestamp_ms": timestamp_ms,
                            "direction": direction,
                            "msg_id": msg_id,
                            "error": str(exc),
                            "head": head,
                            "body_len": len(body),
                            "body_prefix_hex": body[:128].hex(),
                        }
                    )
                return
        try:
            decoded_messages = self.registry.decode_messages(direction, head, body)
        except MessageDecodeFailure as exc:
            self.metrics.protobuf_decode_errors += 1
            self.reliability_flags.add("protobuf_decode_failed")
            LOGGER.error("session protobuf decode failed", exc_info=True)
            if self.on_debug_record is not None:
                self.on_debug_record(
                    {
                        "type": "debug_protobuf_error",
                        "session_id": self.session_id,
                        "timestamp_ms": timestamp_ms,
                        "direction": direction,
                        "msg_id": msg_id,
                        "class_name": self.registry.resolve_class_name(direction, msg_id),
                        "error": str(exc),
                        "head": head,
                        "body_len": len(body),
                        "body_prefix_hex": body[:128].hex(),
                    }
                )
            return
        except SessionBodyDecompressionError as exc:
            self.metrics.decompression_errors += 1
            self.reliability_flags.add("session_body_decompression_failed")
            LOGGER.error("merged protobuf payload decompression failed", exc_info=True)
            if self.on_debug_record is not None:
                self.on_debug_record(
                    {
                        "type": "debug_decompression_error",
                        "session_id": self.session_id,
                        "timestamp_ms": timestamp_ms,
                        "direction": direction,
                        "msg_id": msg_id,
                        "class_name": self.registry.resolve_class_name(direction, msg_id),
                        "error": str(exc),
                        "head": head,
                        "body_len": len(body),
                        "body_prefix_hex": body[:128].hex(),
                    }
                )
            return
        return decoded_messages, body


    def _assemble_multi_pack_message(
        self,
        direction: str,
        head: dict[str, Any],
        plain_body: bytes,
        timestamp_ms: int,
    ) -> tuple[dict[str, Any], bytes, bool] | None:
        total_pack_count = int(head.get("total_pack_count", 1) or 1)
        if total_pack_count <= 1:
            return head, plain_body, False

        current_pack_index = int(head.get("current_pack_index", 0) or 0)
        seqid = int(head.get("down_seqid", head.get("up_seqid", 0)) or 0)
        if seqid <= 0:
            return None
        base_seqid = seqid - current_pack_index
        key = (direction, int(head.get("msgid", 0) or 0), base_seqid)
        state = self.pending_multi_frames.setdefault(
            key,
            {
                "total_pack_count": total_pack_count,
                "head": dict(head),
                "parts": {},
                "first_timestamp_ms": timestamp_ms,
                "last_timestamp_ms": timestamp_ms,
            },
        )
        parts = state["parts"]
        assert isinstance(parts, dict)
        parts[current_pack_index] = maybe_decompress_session_body(head, plain_body)
        state["last_timestamp_ms"] = timestamp_ms
        if len(parts) < total_pack_count:
            if self.on_debug_record is not None:
                self.on_debug_record(
                    {
                        "type": "debug_multipack_pending",
                        "session_id": self.session_id,
                        "timestamp_ms": timestamp_ms,
                        "direction": direction,
                        "msg_id": int(head.get("msgid", 0) or 0),
                        "seqid": seqid,
                        "base_seqid": base_seqid,
                        "total_pack_count": total_pack_count,
                        "current_pack_index": current_pack_index,
                        "received_indexes": sorted(int(index) for index in parts.keys()),
                    }
                )
            return None

        combined = b"".join(parts[index] for index in range(total_pack_count) if index in parts)
        if len(parts) != total_pack_count:
            return None
        full_head = dict(state["head"])
        full_head["is_compress"] = False
        self.pending_multi_frames.pop(key, None)
        return full_head, combined, True
