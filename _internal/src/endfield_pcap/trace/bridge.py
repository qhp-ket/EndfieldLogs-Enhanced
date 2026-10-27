from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from endfield_pcap.capture.resolver import PacketResolver
from endfield_pcap.trace.formatting import _intish
from endfield_pcap.trace.observations import (
    CLOCK_EVENTS, write_clock_observation, write_keyword_update,
    write_buff_enable, write_entity_value,
)
from endfield_pcap.trace.context import BattleContext
from endfield_pcap.trace.actors import ActorEvents
from endfield_pcap.trace.skills import SkillEvents
from endfield_pcap.trace.damage import DamageEvents
from endfield_pcap.trace.buffs.events import BuffEvents
from endfield_pcap.trace.buffs.mapping import BuffMapping


def default_trace_file() -> Path:
    import os

    return Path(os.environ.get("TEMP", ".")) / "dxg_trace.dat"

def make_archive_trace_file(log_dir: Path, *, now: datetime | None = None) -> Path:
    timestamp = now or datetime.now()
    day_dir = Path(log_dir) / timestamp.strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    stem = f"trace_{timestamp.strftime('%Y%m%d-%H%M%S')}"
    candidate = day_dir / f"{stem}.log"
    index = 1
    while candidate.exists():
        candidate = day_dir / f"{stem}_{index:02d}.log"
        index += 1
    return candidate

class TraceBridge(BattleContext, ActorEvents, SkillEvents, DamageEvents, BuffEvents, BuffMapping):
    """Translate decoded events into the shared canonical trace format.

    Disk recording and live analysis receive the same ordered lines through
    _append_line; the feature mixins preserve their existing evidence rules.
    """

    def __init__(
        self, trace_file: Path | None = None, *,
        line_sink: Callable[[str], None] | None = None,
        write_enabled: bool = True,
    ) -> None:
        self.trace_file = (trace_file or default_trace_file()) if write_enabled else None
        self.line_sink = line_sink
        self.id_to_name: dict[int, str] = {}
        self.skill_id_by_inst: dict[int, str] = {}
        self.skill_source_by_inst: dict[int, str] = {}
        self._char_skills_emitted: set[tuple[str, tuple[str, ...]]] = set()
        self.skill_owner_by_int: dict[int, str] = {}
        self.buff_id_by_uid: dict[int, str] = {}
        self.buff_actor_ids_by_uid: dict[int, tuple[int | None, int | None]] = {}
        self.buff_values_by_uid: dict[int, dict[str, float]] = {}
        self.buff_keys_by_uid: dict[int, set[str]] = {}
        self.actor_alias_by_raw_id: dict[int, str] = {}
        self.learned_buff_mapping_by_signature: dict[tuple[int, str, tuple[str, ...]], str] = {}
        self.learned_buff_mapping_conflicts: set[tuple[int, str, tuple[str, ...]]] = set()
        self.resolver = PacketResolver()
        self.active_suits_by_char: dict[str, set[str]] = {}
        self.active_weapons_by_char: dict[str, str] = {}
        self.loadout_actor_order: list[str] = []
        self._next_loadout_actor_index = 0
        self.recent_dynamic_bb_by_inst: dict[int, list[tuple[int, float]]] = {}
        self._keyword_value_serials: dict[tuple[str, str, str], tuple[int, float | None]] = {}
        self.recent_calc_bb_by_inst: dict[int, list[tuple[int, str, float]]] = {}
        self.hit_seq = 0
        self.buff_seq = 0
        self._last_ts_ms: int | None = None
        self._pending_add_buff_ts_ms: int | None = None
        self._pending_add_buff_events: list[dict[str, Any]] = []
        self._pending_create_buff_ts_ms: int | None = None
        self._pending_create_buff_events: list[dict[str, Any]] = []
        self._pending_buff_start_ts_ms: int | None = None
        self._pending_buff_start_order: list[int] = []
        self._pending_buff_start_rows: dict[int, tuple[str, str, str, Any]] = {}
        self._battle_active = False
        self._battle_start_ts_ms: int | None = None
        self._battle_start_client_tick_ms: int | None = None
        self._official_timer_active = False
        self._official_timer_start_ts_ms: int | None = None
        self._official_timer_observed_start_ts_ms: int | None = None
        self._official_timer_game_id = ""
        self._official_timer_expected = False
        self._challenge_pass_confirmed = False
        self._current_dungeon_context: dict[str, Any] | None = None
        self._battle_dungeon_context_emitted = False
        self._current_enemy_hint = ""
        self._current_enemy_hint_source = ""
        self._has_scene_squad = False
        if self.trace_file is not None:
            self.trace_file.parent.mkdir(parents=True, exist_ok=True)
            self.trace_file.write_text("", encoding="utf-8")

    def handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        ts_ms = _intish(event.get("timestamp_ms"))
        if event_type in CLOCK_EVENTS:
            write_clock_observation(self, event, event_type, ts_ms)
            return
        if ts_ms is None:
            ts_ms = int(datetime.now().timestamp() * 1000)
        self._last_ts_ms = ts_ms
        action = event.get("action") if event_type == "BattleOpTriggerAction" else None
        action_type = str(action.get("action_type") or "") if isinstance(action, dict) else ""
        is_create_buff_trigger = bool(
            event_type == "BattleOpTriggerAction"
            and isinstance(action, dict)
            and (action_type == "BattleActionCreateBuff" or "create_buff_action" in action)
        )
        if event_type != "BattleOpAddBuff":
            self._flush_pending_add_buffs()
        if not is_create_buff_trigger:
            self._flush_pending_create_buff_triggers()
        if event_type == "DUNGEON_CONTEXT":
            self._handle_dungeon_context(event, ts_ms)
        elif event_type == "CS_ENTER_DUNGEON":
            self._handle_scene_load_boundary(event_type, event, ts_ms)
        elif event_type == "CS_SCENE_LOAD_FINISH":
            self._handle_scene_load_boundary(event_type, event, ts_ms)
        elif event_type in {"CS_SCENE_SET_BATTLE", "SC_SCENE_SET_BATTLE"}:
            self._handle_scene_battle_state(event_type, event, ts_ms)
        elif event_type == "CONTRACT_TAGS":
            self._handle_contract_tags(event, ts_ms)
        elif event_type == "SC_SELF_SCENE_INFO":
            self._handle_scene_info(event, ts_ms)
        elif event_type == "SC_SELF_SCENE_INFO_SKILLS":
            self._handle_scene_info_skills(event, ts_ms)
        elif event_type == "SC_OBJECT_ENTER_VIEW":
            self._handle_object_enter(event, ts_ms)
        elif event_type == "SC_SYNC_ATTR":
            self._handle_sync_attr(event, ts_ms)
        elif event_type == "BattleOpSkillAttach":
            self._handle_skill_attach(event, ts_ms)
        elif event_type == "BattleOpSkillDetach":
            self._handle_skill_detach(event)
        elif event_type == "BattleOpSkillStartCast":
            self._handle_skill_start_cast(event, ts_ms)
        elif event_type == "BattleOpSkillEndCast":
            self._handle_skill_end_cast(event, ts_ms)
        elif event_type == "BattleOpUpdateAtbInfo":
            self._handle_update_atb_info(event, ts_ms)
        elif event_type == "BattleOpModifyPoiseValue":
            self._handle_modify_poise_value(event, ts_ms)
        elif event_type == "BattleOpModifyBattleState":
            self._handle_battle_state(event, ts_ms)
        elif event_type == "SC_RESET_BATTLE_STATUS":
            self._handle_reset_battle_status(event, ts_ms)
        elif event_type == "SC_SYNC_WEEK_RAID_SETTLEMENT":
            self._handle_week_raid_settlement(event, ts_ms)
        elif event_type in {
            "CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH",
            "CS_GAME_MECHANICS_REQ_START",
            "CS_GAME_MECHANICS_REQ_STOP",
            "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE",
            "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE",
            "SC_GAME_MECHANICS_SYNC_CHALLENGE_START",
            "SC_GAME_MECHANICS_SYNC_COMPLETION_REWARD",
            "SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST",
            "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST",
            "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST",
        }:
            self._handle_game_mechanics_event(event, ts_ms)
        elif event_type == "BattleOpAddBuff":
            if self._pending_add_buff_ts_ms is None or self._pending_add_buff_ts_ms == ts_ms:
                self._pending_add_buff_ts_ms = ts_ms
                self._pending_add_buff_events.append(event)
            else:
                self._flush_pending_add_buffs()
                self._pending_add_buff_ts_ms = ts_ms
                self._pending_add_buff_events.append(event)
        elif event_type == "BattleOpFinishBuff":
            self._handle_finish_buff_op(event, ts_ms)
        elif event_type == "BattleOpTriggerAction":
            if is_create_buff_trigger:
                if self._pending_create_buff_ts_ms is None or self._pending_create_buff_ts_ms == ts_ms:
                    self._pending_create_buff_ts_ms = ts_ms
                    self._pending_create_buff_events.append(event)
                else:
                    self._flush_pending_create_buff_triggers()
                    self._pending_create_buff_ts_ms = ts_ms
                    self._pending_create_buff_events.append(event)
            else:
                self._handle_trigger_action(event, ts_ms)
        elif event_type == 'BattleOpTriggerKeyword':
            write_keyword_update(self, event, ts_ms)
        elif event_type == 'BattleOpSetBuffEnableState':
            write_buff_enable(self, event, ts_ms)
        elif event_type == "BattleOpEntityDie":
            self._line(ts_ms, f"ENTITY_DIE id={event.get('entity_inst_id')}")
        elif event_type == "BattleOpEntityValueModify":
            write_entity_value(self, event, ts_ms)
        elif event_type == "SESSION_WARNING":
            self._line(
                ts_ms,
                (
                    f"SESSION_WARNING kind={event.get('kind') or 'unknown'} "
                    f"direction={event.get('direction') or 'unknown'} "
                    f"missingBytes={event.get('missing_bytes') if event.get('missing_bytes') is not None else 'unknown'} "
                    f"gapCount={event.get('startup_tcp_gap_count') if event.get('startup_tcp_gap_count') is not None else 'unknown'}"
                ),
            )
        elif event_type == "LOADOUT":
            self._handle_loadout(event, ts_ms)

    def end_capture_session(self, *, timestamp_ms: int | None = None) -> bool:
        """Handle an active battle when its packet capture session disappears.

        Use the last observed packet timestamp by default.  Advancing to wall
        clock time here would count loading/disconnect time that was never
        observed in the game stream. War Echo is official-only: a missing
        challenge-complete packet is reported, never synthesized as an end.
        """
        ts_ms = timestamp_ms if timestamp_ms is not None else self._last_ts_ms
        if ts_ms is None:
            ts_ms = int(datetime.now().timestamp() * 1000)
        self._last_ts_ms = ts_ms
        self._flush_pending_add_buffs()
        self._flush_pending_create_buff_triggers()
        self._flush_pending_buff_starts()
        self._record_missing_official_timer(ts_ms, boundary="CAPTURE_SESSION_LOST")
        return False

    def begin_capture_session(self, *, timestamp_ms: int | None = None) -> None:
        """Reset trace state before replaying packets from a new TCP flow."""
        ts_ms = timestamp_ms if timestamp_ms is not None else int(datetime.now().timestamp() * 1000)
        self._last_ts_ms = ts_ms
        self._emit_timer_reset(ts_ms, source="CAPTURE_SESSION_START")

        self.id_to_name.clear()
        self.skill_id_by_inst.clear()
        self.skill_source_by_inst.clear()
        self._char_skills_emitted.clear()
        self.skill_owner_by_int.clear()
        self.buff_id_by_uid.clear()
        self.buff_actor_ids_by_uid.clear()
        self.buff_values_by_uid.clear()
        self.buff_keys_by_uid.clear()
        self.actor_alias_by_raw_id.clear()
        self.learned_buff_mapping_by_signature.clear()
        self.learned_buff_mapping_conflicts.clear()
        self.resolver = PacketResolver()
        self.active_suits_by_char.clear()
        self.active_weapons_by_char.clear()
        self.loadout_actor_order.clear()
        self._next_loadout_actor_index = 0
        self.recent_dynamic_bb_by_inst.clear()
        self.recent_calc_bb_by_inst.clear()
        self.hit_seq = 0
        self.buff_seq = 0
        self._pending_add_buff_ts_ms = None
        self._pending_add_buff_events.clear()
        self._pending_create_buff_ts_ms = None
        self._pending_create_buff_events.clear()
        self._pending_buff_start_ts_ms = None
        self._pending_buff_start_order.clear()
        self._pending_buff_start_rows.clear()
        self._current_dungeon_context = None
        self._current_enemy_hint = ""
        self._current_enemy_hint_source = ""
        self._has_scene_squad = False

    def _line(self, ts_ms: int, body: str) -> None:
        self._flush_pending_buff_starts()
        self._append_line(ts_ms, body)

    def _append_line(self, ts_ms: int, body: str) -> None:
        stamp = datetime.fromtimestamp(ts_ms / 1000).strftime("%H:%M:%S.%f")[:-3]
        line = f"[{stamp}] {body}\n"
        if self.trace_file is not None:
            with self.trace_file.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line)
        if self.line_sink is not None:
            self.line_sink(line)
