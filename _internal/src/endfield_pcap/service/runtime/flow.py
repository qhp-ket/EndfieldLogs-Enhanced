from __future__ import annotations
import asyncio
import uuid
import psutil
import logging
from endfield_pcap.models import CapturedPacket, Endpoint, FlowKey, ServiceState
from endfield_pcap.service.session.pipeline import SessionPipeline


LOGGER = logging.getLogger(__name__)


class FlowCapture:
    def _game_running(self) -> bool:
        target = self.config.game_exe.lower()
        for process in psutil.process_iter(["name"]):
            if (process.info.get("name") or "").lower() == target:
                return True
        return False

    def _find_game_pids(self) -> set[int]:
        target = self.config.game_exe.lower()
        pids: set[int] = set()
        for process in psutil.process_iter(["name"]):
            if (process.info.get("name") or "").lower() == target:
                pids.add(int(process.pid))
        return pids

    def _find_active_flow(self, game_pids: set[int]) -> FlowKey | None:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.pid not in game_pids:
                continue
            if not conn.laddr or not conn.raddr:
                continue
            if int(conn.raddr.port) != 30000:
                continue
            return FlowKey(
                client=Endpoint(str(conn.laddr.ip), int(conn.laddr.port)),
                server=Endpoint(str(conn.raddr.ip), int(conn.raddr.port)),
            )
        return None

    async def _process_monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            game_pids = self._find_game_pids()
            if self.state == ServiceState.WAITING_RESTART:
                if not game_pids:
                    self._set_state(ServiceState.WAITING_GAME)
                continue
            if not game_pids:
                if self.active_flow is not None:
                    LOGGER.info("game process exited; clearing session")
                self._reset_session()
                self._set_state(ServiceState.WAITING_GAME)
                continue
            flow = self._find_active_flow(game_pids)
            if flow is None:
                if self.active_flow is not None:
                    LOGGER.info("game connection closed; returning to discovery capture")
                    self._reset_session()
                self._set_state(ServiceState.WAITING_CONNECTION)
                continue
            if self.active_flow != flow:
                self._activate_flow(flow, activation_reason=self._flow_activation_reason(flow))
            if self.active_session and self.active_session.is_live:
                self._lock_active_flow_capture_if_ready()
                self._set_state(ServiceState.LIVE)
            else:
                self._set_state(ServiceState.WAITING_HANDSHAKE)

    async def _packet_loop(self) -> None:
        while True:
            packet = await self.packet_queue.get()
            if self.state == ServiceState.WAITING_RESTART:
                continue
            flow = self._normalize_flow(packet)
            if flow is None:
                continue
            self.pending_packets[flow].append(packet)
            if self.active_flow == flow and self.active_session is not None:
                self.active_session.process_packet(packet)
                if self.active_session.is_live:
                    self._lock_active_flow_capture_if_ready()
                    self._set_state(ServiceState.LIVE)

            # Queue.get() does not yield when a backlog is already available.
            # Give status/monitor tasks a turn between complete TCP packets.
            await asyncio.sleep(0)

    @staticmethod
    def _normalize_flow(packet: CapturedPacket) -> FlowKey | None:
        if packet.src.port == 30000:
            return FlowKey(client=packet.dst, server=packet.src)
        if packet.dst.port == 30000:
            return FlowKey(client=packet.src, server=packet.dst)
        return None

    @staticmethod
    def _pending_sort_key(flow: FlowKey, packet: CapturedPacket) -> tuple[int, int, int]:
        direction_rank = 0 if packet.src == flow.client else 1
        return (direction_rank, int(packet.seq), int(packet.timestamp_ms))

    def _sorted_pending_packets(self, flow: FlowKey) -> list[CapturedPacket]:
        return sorted(
            list(self.pending_packets.get(flow, ())),
            key=lambda packet: self._pending_sort_key(flow, packet),
        )

    def _ready_to_activate_flow(self, flow: FlowKey) -> bool:
        pending = self._sorted_pending_packets(flow)
        if not pending:
            return False
        has_client_payload = any(packet.src == flow.client for packet in pending)
        has_server_payload = any(packet.src == flow.server for packet in pending)
        return has_client_payload and has_server_payload

    def _flow_activation_reason(self, flow: FlowKey) -> str:
        if self._ready_to_activate_flow(flow):
            return "buffered_bidirectional_payload"
        return "process_connection_fallback"

    def _lock_active_flow_capture_if_ready(self) -> None:
        if self.active_flow is None or self.active_session is None or not self.active_session.is_live:
            return
        if self._active_flow_capture_locked:
            return
        # Keep the original Npcap handles alive for the lifetime of the TCP
        # session. Reopening them after the encrypted handshake can lose one
        # server segment; TCP reassembly must then stop rather than fabricate
        # the missing bytes, which also hides the authoritative settlement.
        # The discovery filter is already narrow ("tcp port 30000").
        self._active_flow_capture_locked = True

    def _activate_flow(self, flow: FlowKey, *, activation_reason: str = "unknown") -> None:
        LOGGER.info(
            "activating flow %s:%d -> %s:%d reason=%s",
            flow.client.ip,
            flow.client.port,
            flow.server.ip,
            flow.server.port,
            activation_reason,
        )
        pending = self._sorted_pending_packets(flow)
        if self.active_flow is not None or self.active_session is not None:
            self._reset_session()
        self.active_flow = flow
        self._active_flow_capture_locked = False
        self.active_session = SessionPipeline(
            flow=flow,
            session_id=str(uuid.uuid4()),
            registry=self.registry,
            private_key=self.private_key,
            srsa_bridge=self.srsa_bridge,
            name_index=self.name_index,
            multi_phase_dungeon_map=self.multi_phase_dungeon_map,
            merge_multi_phase_enemy_battles=self.config.merge_multi_phase_enemy_battles,
            on_event=self._handle_outbound_event,
            on_debug_message=self._handle_debug_message if self.config.debug_enabled else None,
            on_debug_record=self._handle_debug_record if self.config.debug_enabled else None,
            metrics=self.metrics,
        )
        self._open_log_file(self.active_session.session_id)
        self._open_debug_session_dir(self.active_session.session_id)
        if self.trace_bridge is not None:
            capture_start_ts_ms = min(
                (packet.timestamp_ms for packet in pending),
                default=None,
            )
            self.trace_bridge.begin_capture_session(timestamp_ms=capture_start_ts_ms)
        self._write_status()
        LOGGER.info("replaying %d buffered packets for active flow", len(pending))
        for packet in pending:
            self.active_session.process_packet(packet)
        self._lock_active_flow_capture_if_ready()
