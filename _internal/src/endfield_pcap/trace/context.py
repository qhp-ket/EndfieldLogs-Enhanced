from __future__ import annotations
from typing import Any
from endfield_pcap.trace.formatting import _intish


class BattleContext:
    def _handle_dungeon_context(self, event: dict[str, Any], ts_ms: int) -> None:
        dungeon_id = str(event.get("dungeon_id") or event.get("dungeonId") or "").strip()
        if not dungeon_id:
            return
        self._current_dungeon_context = dict(event)
        self._current_dungeon_context["dungeon_id"] = dungeon_id
        self._battle_dungeon_context_emitted = False
        self._set_enemy_hint_from_dungeon_id(dungeon_id, "dungeon_context", clear_on_missing=True)
        is_calc = bool(event.get("is_calc"))
        is_pass = bool(event.get("is_pass"))
        if is_calc and is_pass:
            self._challenge_pass_confirmed = True
            self._line(
                ts_ms,
                (
                    f"BATTLE_RESULT source={event.get('source') or 'DUNGEON_CONTEXT'} "
                    f"dungeonId={dungeon_id} isCalc=1 isPass=1"
                ),
            )
        elif not self._battle_active and not self._official_timer_active:
            self._challenge_pass_confirmed = False
        self._write_dungeon_context(ts_ms, self._current_dungeon_context)

    def _write_dungeon_context(self, ts_ms: int, context: dict[str, Any]) -> None:
        dungeon_id = str(context.get("dungeon_id") or context.get("dungeonId") or "").strip()
        if not dungeon_id:
            return
        parts = [
            "DUNGEON_CONTEXT",
            f"dungeonId={dungeon_id}",
            f"source={context.get('source') or 'packet'}",
        ]
        optional_fields = (
            ("scene_num_id", "scene"),
            ("scene_id", "sceneId"),
            ("challenge_expire_ts", "challengeExpireTs"),
            ("leave_dungeon_ts", "leaveDungeonTs"),
            ("char_team_count", "charTeamCount"),
        )
        for source_key, output_key in optional_fields:
            value = context.get(source_key)
            if value is not None:
                parts.append(f"{output_key}={value}")
        for source_key, output_key in (
            ("is_reward", "isReward"),
            ("is_calc", "isCalc"),
            ("is_pass", "isPass"),
        ):
            value = context.get(source_key)
            if value is not None:
                parts.append(f"{output_key}={1 if bool(value) else 0}")
        self._line(ts_ms, " ".join(parts))

    def _handle_contract_tags(self, event: dict[str, Any], ts_ms: int) -> None:
        dungeon_id = str(event.get("dungeon_id") or event.get("dungeonId") or "").strip()
        raw_tag_ids = event.get("tag_ids") or event.get("tagIds") or event.get("display_tag_ids") or []
        tag_ids = [int(tag_id) for tag_id in raw_tag_ids if _intish(tag_id)]
        if not dungeon_id and not tag_ids:
            return
        parts = [
            "CONTRACT_TAGS",
            f"dungeonId={dungeon_id or 'unknown'}",
            f"source={event.get('source') or 'packet'}",
            f"tagIds=[{','.join(str(tag_id) for tag_id in tag_ids)}]",
        ]
        score = _intish(event.get("score"))
        if score is not None:
            parts.append(f"score={score}")
        direction = str(event.get("direction") or "")
        if direction:
            parts.append(f"direction={direction}")
        msg_id = _intish(event.get("msg_id") or event.get("msgId"))
        if msg_id is not None:
            parts.append(f"msgId={msg_id}")
        self._line(ts_ms, " ".join(parts))

    def _handle_reset_battle_status(self, event: dict[str, Any], ts_ms: int) -> None:
        reason = event.get("reason")
        inst_id = event.get("inst_id")
        battle_inst_id = event.get("battle_inst_id")
        parts = ["BATTLE_RESET_STATUS"]
        if reason is not None:
            parts.append(f"reason={reason}")
        if inst_id is not None:
            parts.append(f"inst={inst_id}")
        if battle_inst_id is not None:
            parts.append(f"battleInst={battle_inst_id}")
        self._line(ts_ms, " ".join(parts))

    def _handle_game_mechanics_event(self, event: dict[str, Any], ts_ms: int) -> None:
        event_type = str(event.get("type") or "")
        game_id = str(event.get("game_id") or event.get("cur_game_id") or "")
        self._set_enemy_hint_from_dungeon_id(game_id, "game_mechanics")
        if event_type == "SC_GAME_MECHANICS_SYNC_CHALLENGE_START":
            self._challenge_pass_confirmed = False
            self._official_timer_expected = True
            self._official_timer_active = True
            self._official_timer_observed_start_ts_ms = ts_ms
            self._official_timer_game_id = game_id
            raw_start_ts_ms = _intish(event.get("challenge_start_ts"))
            self._official_timer_start_ts_ms = raw_start_ts_ms if raw_start_ts_ms and raw_start_ts_ms > 0 else ts_ms
            parts = [
                "OFFICIAL_TIMER_START",
                "source=SC_GAME_MECHANICS_SYNC_CHALLENGE_START",
            ]
            if game_id:
                parts.append(f"gameId={game_id}")
            for source_key, output_key in (
                ("challenge_start_ts", "challengeStartTs"),
                ("challenge_expire_ts", "challengeExpireTs"),
                ("prepare_challenge_seconds", "prepareSeconds"),
            ):
                value = event.get(source_key)
                if value is not None:
                    parts.append(f"{output_key}={value}")
            self._line(ts_ms, " ".join(parts))
            return
        if event_type == "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE":
            self._challenge_pass_confirmed = bool(event.get("is_pass"))
            parts = [
                "OFFICIAL_TIMER_END",
                "source=SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE",
            ]
            if game_id:
                parts.append(f"gameId={game_id}")
            for source_key, output_key in (
                ("is_pass", "isPass"),
                ("pass_time", "passTime"),
                ("force_leave_ts", "forceLeaveTs"),
            ):
                value = event.get(source_key)
                if value is not None:
                    if source_key == "is_pass":
                        parts.append(f"{output_key}={1 if bool(value) else 0}")
                    else:
                        parts.append(f"{output_key}={value}")
            self._line(ts_ms, " ".join(parts))
            self._clear_packet_battle_window()
            self._official_timer_expected = False
            self._official_timer_active = False
            self._official_timer_start_ts_ms = None
            self._official_timer_observed_start_ts_ms = None
            self._official_timer_game_id = ""
            return
        labels = {
            "CS_GAME_MECHANICS_NTF_INST_PREPARE_FINISH": "GAME_MECHANICS_PREPARE_FINISH",
            "CS_GAME_MECHANICS_REQ_START": "GAME_MECHANICS_REQ_START",
            "CS_GAME_MECHANICS_REQ_STOP": "GAME_MECHANICS_REQ_STOP",
            "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE": "GAME_MECHANICS_TIME_FREEZE",
            "SC_GAME_MECHANICS_SYNC_ENTER_GAME_INST": "GAME_INST_ENTER",
            "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST": "GAME_INST_LEAVE",
            "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST": "GAME_INST_RESTART",
        }
        label = labels.get(event_type, event_type)
        parts = [label, f"source={event_type}"]
        if game_id:
            parts.append(f"gameId={game_id}")
        for source_key, output_key in (
            ("game_inst_id", "gameInstId"),
            ("game_unique_id", "gameUniqueId"),
            ("is_hunter_mode", "isHunterMode"),
            ("interactive_obj_id", "interactiveObjId"),
            ("npc_proxy_id", "npcProxyId"),
            ("npc_obj_id", "npcObjId"),
        ):
            value = event.get(source_key)
            if value is not None and value != "":
                if source_key == "is_hunter_mode":
                    parts.append(f"{output_key}={1 if bool(value) else 0}")
                else:
                    parts.append(f"{output_key}={value}")
        if event_type == "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE":
            freezes = event.get("time_freeze_infos")
            if isinstance(freezes, list):
                parts.append(f"count={len(freezes)}")
                freeze_tokens: list[str] = []
                total_freeze_ms = 0
                for freeze in freezes:
                    if not isinstance(freeze, dict):
                        continue
                    time_key = _intish(freeze.get("time_key")) or 0
                    freeze_ms = _intish(freeze.get("total_freeze_time_in_ms")) or 0
                    total_freeze_ms = max(total_freeze_ms, freeze_ms)
                    freeze_tokens.append(f"{time_key}:{freeze_ms}")
                if freeze_tokens:
                    parts.append(f"freezeInfos=[{','.join(freeze_tokens)}]")
                    parts.append(f"totalFreezeMs={total_freeze_ms}")
        self._line(ts_ms, " ".join(parts))

        if event_type == "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST":
            self._record_missing_official_timer(ts_ms, boundary=event_type)
            self._emit_timer_reset(ts_ms, source=event_type)
        elif event_type == "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST":
            self._record_missing_official_timer(ts_ms, boundary=event_type)
            self._emit_timer_reset(ts_ms, source=event_type)

    def _handle_week_raid_settlement(self, event: dict[str, Any], ts_ms: int) -> None:
        game_id = str(event.get("game_id") or "").strip()
        if not game_id.startswith("indie_battletower"):
            return
        has_active_run = (
            self._battle_active
            or self._official_timer_expected
            or self._official_timer_active
        )
        if not has_active_run:
            return
        total_playtime = _intish(event.get("total_playtime"))
        parts = [
            "OFFICIAL_TIMER_END",
            "source=SC_SYNC_WEEK_RAID_SETTLEMENT",
            f"gameId={game_id}",
            "isPass=1",
        ]
        if total_playtime is not None and total_playtime >= 0:
            parts.append(f"passTime={total_playtime}")
        for source_key, output_key in (
            ("bp_score", "bpScore"),
            ("danger_meter", "dangerMeter"),
        ):
            value = _intish(event.get(source_key))
            if value is not None:
                parts.append(f"{output_key}={value}")
        self._line(ts_ms, " ".join(parts))
        self._challenge_pass_confirmed = True
        self._clear_packet_battle_window()
        self._official_timer_expected = False
        self._official_timer_active = False
        self._official_timer_start_ts_ms = None
        self._official_timer_observed_start_ts_ms = None
        self._official_timer_game_id = ""

    def _activity_id(self) -> str:
        dungeon_id = ""
        if self._current_dungeon_context is not None:
            dungeon_id = str(
                self._current_dungeon_context.get("dungeon_id")
                or self._current_dungeon_context.get("dungeonId")
                or ""
            )
        return self._official_timer_game_id or dungeon_id

    def _official_timer_required(self) -> bool:
        return self._activity_id().startswith("indie_battletower")

    def _clear_packet_battle_window(self) -> None:
        self._battle_active = False
        self._battle_start_ts_ms = None
        self._battle_start_client_tick_ms = None
        self._battle_dungeon_context_emitted = False

    def _record_missing_official_timer(self, ts_ms: int, *, boundary: str) -> bool:
        if not self._battle_active and not self._official_timer_expected and not self._official_timer_active:
            return False
        activity_id = self._activity_id()
        label = (
            "OFFICIAL_TIMER_MISSING"
            if self._official_timer_expected or self._official_timer_active
            else "BATTLE_TIMER_MISSING"
        )
        parts = [
            label,
            f"boundary={boundary}",
            f"packetBattleActive={1 if self._battle_active else 0}",
            f"officialExpected={1 if self._official_timer_expected else 0}",
            f"officialStartSeen={1 if self._official_timer_active else 0}",
        ]
        if activity_id:
            parts.append(f"gameId={activity_id}")
        self._line(ts_ms, " ".join(parts))
        self._clear_packet_battle_window()
        self._official_timer_expected = False
        self._official_timer_active = False
        self._official_timer_start_ts_ms = None
        self._official_timer_observed_start_ts_ms = None
        self._official_timer_game_id = ""
        self._challenge_pass_confirmed = False
        return True

    def _emit_timer_reset(self, ts_ms: int, *, source: str, scene_num_id: int | None = None) -> None:
        parts = ["GAME_TIMER_RESET", f"source={source}"]
        if scene_num_id is not None:
            parts.append(f"scene={scene_num_id}")
        self._line(ts_ms, " ".join(parts))
        self._battle_active = False
        self._battle_start_ts_ms = None
        self._battle_start_client_tick_ms = None
        self._battle_dungeon_context_emitted = False
        self._official_timer_active = False
        self._official_timer_start_ts_ms = None
        self._official_timer_observed_start_ts_ms = None
        self._official_timer_game_id = ""
        self._official_timer_expected = False
        self._challenge_pass_confirmed = False

    def _handle_scene_load_boundary(
        self,
        event_type: str,
        event: dict[str, Any],
        ts_ms: int,
    ) -> None:
        self._record_missing_official_timer(ts_ms, boundary=event_type)
        self._emit_timer_reset(
            ts_ms,
            source=event_type,
            scene_num_id=_intish(event.get("scene_num_id")),
        )

    def _handle_scene_battle_state(
        self,
        event_type: str,
        event: dict[str, Any],
        ts_ms: int,
    ) -> None:
        in_battle = bool(event.get("in_battle"))
        self._line(
            ts_ms,
            f"SCENE_BATTLE_STATE source={event_type} inBattle={1 if in_battle else 0}",
        )
        if not in_battle and self._official_timer_required() and self._battle_active:
            self._line(
                ts_ms,
                (
                    "OFFICIAL_TIMER_AWAIT "
                    f"source={event_type} gameId={self._activity_id()} "
                    f"officialStartSeen={1 if self._official_timer_active else 0}"
                ),
            )
            self._clear_packet_battle_window()
