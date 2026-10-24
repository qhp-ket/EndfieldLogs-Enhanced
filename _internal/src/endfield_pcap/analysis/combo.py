"""Four-slot presentation state from already decoded skill trigger events.

Durations and refresh/reset IDs are the official distribution's overlay table.
These are estimates, not a decoded authoritative remaining-CD measurement.
No capture, protocol, damage parser, or game timer code is involved.
"""
from __future__ import annotations
import json
import logging
import time
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Callable
from uuid import uuid4


LOGGER = logging.getLogger(__name__)


class ComboCooldownPublisher:
    def __init__(self, *, config: dict | None = None,
                 wall_ms: Callable[[], float] | None = None,
                 monotonic_ms: Callable[[], float] | None = None) -> None:
        if config is None:
            config = json.loads((Path(__file__).parents[1] / "data/assets/combo_skills.json").read_text(encoding="utf-8"))
        self.config = {int(key): value for key, value in config.items()}
        self._wall_ms = wall_ms or (lambda: time.time() * 1000)
        self._monotonic_ms = monotonic_ms or (lambda: time.monotonic() * 1000)
        self._stream_id = str(uuid4())
        self._sequence = -1
        self._message: dict | None = None
        self._dirty = True
        self.session_id: str | None = None
        self._slots: list[dict | None] = [None] * 4
        self._bars: dict[str, dict] = {}
        self._last_trigger: dict[tuple[str, int], float] = {}
        self._seen: OrderedDict[tuple, None] = OrderedDict()
        self._skills: dict[str, dict] = {}
        self._cast_skills: set[tuple[str, int]] = set()

    def clear_cooldowns(self) -> None:
        self._bars.clear()
        self._last_trigger.clear()
        self._seen.clear()
        self._cast_skills.clear()
        self._dirty = True

    def reset(self, *, new_stream: bool = False) -> None:
        if new_stream:
            self._stream_id = str(uuid4())
            self._sequence = -1
        self.session_id = None
        self._slots = [None] * 4
        self._skills.clear()
        self.clear_cooldowns()

    @staticmethod
    def _number(value, default=0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return default

    @staticmethod
    def _adjust(values: list | None, index: int) -> float:
        if not values:
            return 0
        return float(values[max(0, min(index, len(values) - 1))])

    def feed_event(self, event: dict) -> None:
        session_id = event.get("session_id")
        if session_id is not None and session_id != self.session_id:
            self.reset()
            self.session_id = session_id
        kind = event.get("type")
        if kind in {"SC_SELF_SCENE_INFO_SKILLS", "SC_BATTLE_SKILL_ATTACH", "SC_BATTLE_SKILL_UPDATE"}:
            for skill in event.get("skills", []):
                instance = skill.get("skill_inst_id")
                if instance is not None:
                    previous = self._skills.get(str(instance), {})
                    self._skills[str(instance)] = {**previous, **skill,
                        "owner_id": skill.get("owner_inst_id", event.get("owner_inst_id", previous.get("owner_id")))}
            return
        if kind == "BattleOpSkillAttach":
            instance = event.get("skill_inst_id")
            if instance is not None:
                self._skills[str(instance)] = {**event, "level": event.get("skill_lv", 1)}
            return
        if kind == "BattleOpSkillDetach":
            self._skills.pop(str(event.get("skill_inst_id")), None)
            return
        from_cast = kind == "BattleOpSkillStartCast"
        if from_cast:
            skill = self._skills.get(str(event.get("skill_inst_id")))
            if not skill or str(skill.get("owner_id")) != str(event.get("owner_id")):
                return
            event = {**event, "template_type": "Skill", "template_int_id": skill.get("template_int_id"),
                     "level": skill.get("level", 1)}
        if kind == "SC_SELF_SCENE_INFO":
            slots: list[dict | None] = [None] * 4
            for member in event.get("char_list", []):
                index = self._number(member.get("squad_index"), -1)
                owner = member.get("battle_inst_id")
                if 0 <= index < 4 and owner is not None:
                    slots[index] = {
                        "slot_index": index, "battle_inst_id": str(owner),
                        "name": str(member.get("display_name") or member.get("templateid") or owner),
                        "potential_level": max(0, self._number(member.get("potential_level"))),
                    }
            keep = {slot["battle_inst_id"] for i, slot in enumerate(slots)
                    if slot and self._slots[i] == slot}
            self._bars = {key: bar for key, bar in self._bars.items() if key in keep}
            self._last_trigger = {key: value for key, value in self._last_trigger.items() if key[0] in keep}
            self._slots = slots
            self._dirty = True
            return
        if kind in {"SC_RESET_BATTLE_STATUS", "CS_ENTER_DUNGEON", "CS_SCENE_LOAD_FINISH"} or (
            kind == "BattleOpModifyBattleState" and event.get("is_in_battle") is False
        ):
            self.clear_cooldowns()
            return
        if (kind != "BattleOpTriggerAction" and not from_cast) or str(event.get("template_type", "")).lower() != "skill":
            return
        owner = str(event.get("owner_id"))
        member = next((slot for slot in self._slots if slot and slot["battle_inst_id"] == owner), None)
        skill_id = self._number(event.get("template_int_id"), -1)
        if not member:
            return
        existing = self._bars.get(owner)
        main = self.config.get(skill_id)
        reset_id = next((key for key, value in self.config.items() if skill_id in value.get("reset_skill", [])
                         and (not existing or existing["skill_id"] == key)), None)
        refresh = existing and skill_id in self.config[existing["skill_id"]].get("Refresh_skill", [])
        if not main and reset_id is None and not refresh:
            return
        cast_key = (owner, skill_id)
        if main and not from_cast and cast_key in self._cast_skills:
            # Later damage/buff actions belong to the cast already observed.
            return
        # Exact retransmissions cannot restart a timer, even after the original
        # distribution's three-second multi-action debounce has elapsed.
        identity = tuple(str(event.get(key)) for key in (
            "type", "session_id", "owner_id", "seq_id", "client_tick_tms", "inst_id", "template_int_id", "timestamp_ms"))
        if identity in self._seen:
            return
        self._seen[identity] = None
        if len(self._seen) > 4096:
            self._seen.popitem(last=False)
        now = self._monotonic_ms()
        if from_cast and main:
            self._cast_skills.add(cast_key)
        if main and not from_cast and existing and existing["skill_id"] == skill_id and now < existing["started_ms"] + existing["total_ms"]:
            # Without cast evidence, actions cannot safely imply a new cast.
            return
        if refresh:
            existing["started_ms"] = now - existing["total_ms"]
            existing["evidence"] = self._evidence(event)
            self._dirty = True
        selected_id = skill_id if main else reset_id
        if selected_id is None:
            return
        # Reuse the distribution's trigger/reset guard, scoped to the owner.
        last = self._last_trigger.get((owner, skill_id))
        if not from_cast and last is not None and now - last < 3000:
            return
        self._last_trigger[owner, skill_id] = now
        entry = self.config[selected_id]
        duration = entry["duration"]
        level = max(1, self._number(event.get("level"), 1))
        total_ms = max(0, round((float(duration.get("default", 0))
                                + self._adjust(duration.get("skill_level"), level - 1)
                                + self._adjust(duration.get("potential_level"), member["potential_level"])) * 1000))
        captured = self._number(event.get("timestamp_ms"))
        age = max(0, self._wall_ms() - captured) if captured > 0 else 0
        evidence = self._evidence(event)
        evidence["capture_to_observer_ms"] = round(age)
        if from_cast and age > 1000:
            LOGGER.warning("combo cast observed late owner=%s skill=%s capture_to_observer_ms=%d", owner, skill_id, age)
        self._bars[owner] = {
            "skill_id": selected_id, "total_ms": total_ms, "started_ms": now - age,
            "notice_ms": max(0, round(float(entry.get("notice_time", 0)) * 1000)),
            "evidence": evidence,
        }
        self._dirty = True

    @staticmethod
    def _evidence(event: dict) -> dict:
        return {key: str(event[key]) if event.get(key) is not None else None for key in (
            "type", "skill_inst_id",
            "timestamp_ms", "seq_id", "client_tick_tms", "template_int_id", "level")}

    def _snapshot(self) -> dict:
        now = self._monotonic_ms()
        slots = []
        for index, member in enumerate(self._slots):
            row = {"slot_index": index, "name": f"角色 {index + 1}", "battle_inst_id": None,
                   "status": "unknown", "remaining_ms": None, "total_ms": None}
            if member:
                row.update(member)
                bar = self._bars.get(member["battle_inst_id"])
                if bar:
                    # Quantize to the displayed tenth; no client-side timer.
                    remaining = max(0, int((bar["total_ms"] - (now - bar["started_ms"]) + 99) // 100) * 100)
                    row.update({"status": "ready" if remaining == 0 else "cooldown",
                                "remaining_ms": remaining, "total_ms": bar["total_ms"],
                                "skill_id": bar["skill_id"], "notice_ms": bar["notice_ms"],
                                "evidence": bar["evidence"]})
            slots.append(row)
        return {"session_id": self.session_id, "slots": slots,
                "quality": "provisional", "basis": "captured_trigger_and_distribution_duration",
                "clock_basis": "capture_timestamp_then_monotonic_estimate"}

    def current_message(self) -> dict:
        snapshot = self._snapshot()
        if self._message is None or snapshot != self._message["snapshot"] or self._dirty:
            self._sequence += 1
            self._message = {"type": "combo_snapshot", "schema_version": 1,
                             "stream_id": self._stream_id, "sequence": self._sequence, "snapshot": snapshot}
            self._dirty = False
        return deepcopy(self._message)
