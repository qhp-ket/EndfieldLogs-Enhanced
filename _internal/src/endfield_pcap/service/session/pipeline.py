from __future__ import annotations
from collections import Counter, deque
from typing import Any, Callable
from endfield_pcap.crypto.srsa_bridge import SRSABridge
from endfield_pcap.crypto.xxe1 import XXE1
from endfield_pcap.capture.flow import TcpStreamReassembler
from endfield_pcap.capture.registry import DecodedMessage, MessageRegistry
from endfield_pcap.models import (
    CapturedPacket,
    EntityInfo,
    FlowKey,
    OutboundEvent,
    RuntimeMetrics,
    SquadMember,
)
from endfield_pcap.service.session.framing import FramingEvents
from endfield_pcap.service.session.dispatch import MessageDispatch
from endfield_pcap.service.session.state.scene import SceneEvents
from endfield_pcap.service.session.state.inventory import InventoryEvents
from endfield_pcap.service.session.state.loadout import LoadoutEvents
from endfield_pcap.service.session.state.identity import IdentityEvents
from endfield_pcap.service.session.state.skills import SkillStateEvents
from endfield_pcap.service.session.battle import BattleEvents
from endfield_pcap.service.session.actions import ActionEvents


class SessionPipeline(
    FramingEvents,
    MessageDispatch,
    SceneEvents,
    InventoryEvents,
    LoadoutEvents,
    IdentityEvents,
    SkillStateEvents,
    BattleEvents,
    ActionEvents,
):
    ENDMIN_VARIANTS = ("chr_0002_endminm", "chr_0003_endminf")

    def __init__(
        self,
        flow: FlowKey,
        session_id: str,
        registry: MessageRegistry,
        private_key: Any,
        srsa_bridge: SRSABridge,
        name_index: dict[str, str],
        multi_phase_dungeon_map: dict[str, str],
        merge_multi_phase_enemy_battles: bool,
        on_event: Callable[[OutboundEvent], None],
        on_debug_message: Callable[[DecodedMessage, int], None] | None,
        on_debug_record: Callable[[dict[str, object]], None] | None,
        metrics: RuntimeMetrics,
        rotation_clock_trace: bool = True,
    ) -> None:
        self.flow = flow
        self.session_id = session_id
        self.registry = registry
        self.private_key = private_key
        self.srsa_bridge = srsa_bridge
        self.name_index = name_index
        self.multi_phase_dungeon_map = multi_phase_dungeon_map
        self.merge_multi_phase_enemy_battles = merge_multi_phase_enemy_battles
        self.on_event = on_event
        self.on_debug_message = on_debug_message
        self.on_debug_record = on_debug_record
        self.metrics = metrics
        self.rotation_clock_trace = bool(rotation_clock_trace)

        self.client_reassembler = TcpStreamReassembler()
        self.server_reassembler = TcpStreamReassembler()
        self.client_buffer = bytearray()
        self.server_buffer = bytearray()
        self.pending_client_session_frames: deque[tuple[int, bytes, bytes, int]] = deque()
        self._last_gap_report: dict[str, tuple[int, int, int]] = {}
        self.pending_multi_frames: dict[tuple[str, int, int], dict[str, object]] = {}
        self.first_packet_ts_ms: int | None = None
        self.startup_tcp_gap_count = 0
        self.startup_tcp_gap_max_missing_bytes = 0
        self.reliability_flags: set[str] = set()
        self._startup_gap_warning_emitted = False

        self.client_login_done = False
        self.server_login_done = False
        self.client_cipher: XXE1 | None = None
        self.server_cipher: XXE1 | None = None

        self.entity_index: dict[int, EntityInfo] = {}
        self.obj_to_battle: dict[int, int] = {}
        self.squad_index: dict[int, SquadMember] = {}
        self.char_potential_levels: dict[str, int] = {}
        self.skill_levels_by_battle_inst: dict[int, dict[str, int]] = {}
        self.global_skill_levels: dict[str, int] = {}
        self.decoded_class_counts: Counter[str] = Counter()
        self.char_bag_by_objid: dict[int, dict[str, object]] = {}
        self.current_team_char_ids: list[int] = []
        self.scene_team_char_ids: list[int] = []
        # None means CS_ENTER_DUNGEON did not carry an explicit party override.
        # The packet commonly omits char_team for War Echo even though the
        # current bag team is the actual battle roster.
        self.dungeon_team_char_ids: list[int] | None = None
        self.equip_by_inst_id: dict[int, dict[str, object]] = {}
        self.weapon_by_inst_id: dict[int, dict[str, object]] = {}
        self.gem_by_inst_id: dict[int, dict[str, object]] = {}
        self.gem_by_weapon_id: dict[int, dict[str, object]] = {}
        self.server_skill_state_by_owner_inst: dict[int, dict[int, dict[str, object | None]]] = {}
        self.server_skill_owner_by_skill_inst: dict[int, int] = {}
        self._last_loadout_signature: str | None = None
        self.tracked_dungeon_id: str | None = None
        self.tracked_enemy_templateid: str | None = None
        self.tracked_enemy_inst_ids: set[int] = set()
        self.merged_battle_active = False

    @property
    def is_live(self) -> bool:
        return (
            self.client_login_done
            and self.server_login_done
            and self.client_cipher is not None
            and self.server_cipher is not None
        )

    def status_snapshot(self) -> dict[str, object]:
        return {
            "client_login_done": self.client_login_done,
            "server_login_done": self.server_login_done,
            "client_cipher_ready": self.client_cipher is not None,
            "server_cipher_ready": self.server_cipher is not None,
            "client_buffer_len": len(self.client_buffer),
            "server_buffer_len": len(self.server_buffer),
            "pending_client_session_frames": len(self.pending_client_session_frames),
            "decoded_class_counts": dict(self.decoded_class_counts.most_common(30)),
            "reliability_flags": sorted(self.reliability_flags),
            "startup_tcp_gap_count": self.startup_tcp_gap_count,
            "startup_tcp_gap_max_missing_bytes": self.startup_tcp_gap_max_missing_bytes,
            "tcp_gap": {
                direction: {
                    "missing_from_seq": gap[0],
                    "next_seen_seq": gap[1],
                    "missing_bytes": gap[2],
                }
                for direction, gap in self._last_gap_report.items()
            },
        }

    def process_packet(self, packet: CapturedPacket) -> None:
        if self.first_packet_ts_ms is None:
            self.first_packet_ts_ms = packet.timestamp_ms
        direction = "cs" if packet.src == self.flow.client else "sc"
        reassembler = self.client_reassembler if direction == "cs" else self.server_reassembler
        buffer = self.client_buffer if direction == "cs" else self.server_buffer
        flushed_chunks = reassembler.accept(packet.seq, packet.payload)
        if flushed_chunks:
            self._last_gap_report.pop(direction, None)
        else:
            gap = reassembler.gap_state()
            if gap is not None and self._last_gap_report.get(direction) != gap:
                self._last_gap_report[direction] = gap
                missing_from_seq, next_seen_seq, missing_bytes = gap
                self._note_tcp_gap(packet.timestamp_ms, direction, missing_bytes)
                if self.on_debug_record is not None:
                    self.on_debug_record(
                        {
                            "type": "debug_tcp_gap",
                            "session_id": self.session_id,
                            "timestamp_ms": packet.timestamp_ms,
                            "direction": direction,
                            "missing_from_seq": missing_from_seq,
                            "next_seen_seq": next_seen_seq,
                            "missing_bytes": missing_bytes,
                            "packet_seq": packet.seq,
                            "packet_len": len(packet.payload),
                        }
                    )
        for chunk in flushed_chunks:
            buffer.extend(chunk)
            self._drain_direction(direction, packet.timestamp_ms)

    def flush_debug_state(self) -> None:
        if self.on_debug_record is None:
            self.pending_multi_frames.clear()
            return
        for (direction, msg_id, base_seqid), state in list(self.pending_multi_frames.items()):
            parts = state.get("parts", {})
            if not isinstance(parts, dict):
                continue
            self.on_debug_record(
                {
                    "type": "debug_multipack_incomplete",
                    "session_id": self.session_id,
                    "timestamp_ms": int(state.get("last_timestamp_ms", state.get("first_timestamp_ms", 0)) or 0),
                    "direction": direction,
                    "msg_id": msg_id,
                    "base_seqid": base_seqid,
                    "total_pack_count": int(state.get("total_pack_count", 0) or 0),
                    "received_indexes": sorted(int(index) for index in parts.keys()),
                    "first_timestamp_ms": int(state.get("first_timestamp_ms", 0) or 0),
                    "last_timestamp_ms": int(state.get("last_timestamp_ms", 0) or 0),
                    "head": state.get("head", {}),
                }
            )
        self.pending_multi_frames.clear()

    def _emit_event(self, event: OutboundEvent) -> None:
        self.metrics.outbound_events_emitted += 1
        self.on_event(event)
