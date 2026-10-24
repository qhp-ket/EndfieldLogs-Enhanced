from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import logging
from datetime import datetime
from google.protobuf.json_format import MessageToDict
from endfield_pcap.capture.registry import DecodedMessage


LOGGER = logging.getLogger(__name__)


class DebugOutput:
    def _open_debug_session_dir(self, session_id: str) -> None:
        self.debug_session_dir = None
        self.debug_counters.clear()
        if not self.config.debug_enabled:
            return
        timestamp = datetime.now().strftime("%Y%m%d")
        session_dir = self.config.debug_dir / timestamp / f"session_{session_id}"
        (session_dir / "proto" / "CS_BATTLE_OP").mkdir(parents=True, exist_ok=True)
        (session_dir / "proto" / "SC_SELF_SCENE_INFO").mkdir(parents=True, exist_ok=True)
        (session_dir / "proto" / "SC_SYNC_CHAR_BAG_INFO").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "frame_error").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "decompression_error").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "protobuf_error").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "session_head").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "undecoded_frame").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "tcp_gap").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "multipack_pending").mkdir(parents=True, exist_ok=True)
        (session_dir / "issues" / "multipack_incomplete").mkdir(parents=True, exist_ok=True)
        self.debug_session_dir = session_dir
        LOGGER.info("debug output -> %s", session_dir)

    def _handle_debug_message(self, decoded: DecodedMessage, timestamp_ms: int) -> None:
        if self.debug_session_dir is None or self.active_session is None:
            return
        schema_files = {}
        pending_descriptors = [decoded.message.DESCRIPTOR.file]
        while pending_descriptors:
            descriptor = pending_descriptors.pop()
            if descriptor.name in schema_files:
                continue
            schema_files[descriptor.name] = hashlib.sha256(descriptor.serialized_pb).hexdigest()
            pending_descriptors.extend(descriptor.dependencies)
        payload = {
            "type": "debug_proto",
            "session_id": self.active_session.session_id,
            "timestamp_ms": timestamp_ms,
            "direction": decoded.direction,
            "class_name": decoded.class_name,
            "msg_id": decoded.msg_id,
            "head": decoded.head,
            # MessageToDict omits fields unknown to this schema. Preserve the
            # exact decoded body as well, so a newer schema can replay it.
            "raw_body_format": "protobuf_body_after_decompression_and_reassembly",
            "raw_body_size": len(decoded.raw_body),
            "raw_body_sha256": hashlib.sha256(decoded.raw_body).hexdigest(),
            "raw_body_base64": base64.b64encode(decoded.raw_body).decode('ascii'),
            "protobuf_schema_files_sha256": dict(sorted(schema_files.items())),
            "message": MessageToDict(
                decoded.message,
                preserving_proto_field_name=True,
                use_integers_for_enums=False,
                always_print_fields_with_no_presence=True,
            ),
            "message_enum_ints": MessageToDict(
                decoded.message,
                preserving_proto_field_name=True,
                use_integers_for_enums=True,
                always_print_fields_with_no_presence=True,
            ),
        }
        self._write_debug_json("proto", decoded.class_name, payload, timestamp_ms, decoded.direction)

    def _handle_debug_record(self, payload: dict[str, object]) -> None:
        if self.debug_session_dir is None:
            return
        record_type = str(payload.get("type", "record"))
        if record_type == "debug_frame_error":
            category = "frame_error"
        elif record_type == "debug_decompression_error":
            category = "decompression_error"
        elif record_type == "debug_protobuf_error":
            category = "protobuf_error"
        elif record_type == "debug_session_head":
            category = "session_head"
        elif record_type == "debug_tcp_gap":
            category = "tcp_gap"
        elif record_type == "debug_multipack_pending":
            category = "multipack_pending"
        elif record_type == "debug_multipack_incomplete":
            category = "multipack_incomplete"
        else:
            category = "undecoded_frame"
        direction = str(payload.get("direction", "na"))
        timestamp_ms = int(payload.get("timestamp_ms", 0))
        self._write_debug_json("issues", category, payload, timestamp_ms, direction)

    def _write_debug_json(
        self,
        top_level: str,
        bucket: str,
        payload: dict[str, object],
        timestamp_ms: int,
        direction: str,
    ) -> None:
        if self.debug_session_dir is None:
            return
        key = (top_level, bucket)
        self.debug_counters[key] += 1
        index = self.debug_counters[key]
        target_dir = self.debug_session_dir / top_level / bucket
        target_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"{index:06d}_{timestamp_ms}_{direction}.json"
        path = target_dir / file_name
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _batch_flush_loop(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            await self._flush_batch()
