"""Choose battle coordinates and restrict evidence to the observed lifecycle."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from parser_core.reporting.state import ReportState
from parser_core.reporting.timing import _filter_buff_starts_for_timer_window
from parser_core.reporting.totals import _rebuild_hit_totals


@dataclass
class HitWindow:
    start_ms: int
    end_ms: int
    time_source: str
    zero_source: str
    has_game_timer: bool = False


@dataclass(frozen=True)
class BattleTimeline:
    start_ms: int
    end_ms: int
    scale: float

    def offset_ms(self, ts_ms: int) -> int:
        return max(int(round((int(ts_ms) - self.start_ms) * self.scale)), 0)

    def offset_ms_unclamped(self, ts_ms: int) -> int:
        return int(round((int(ts_ms) - self.start_ms) * self.scale))


@dataclass(frozen=True)
class FallbackWindow:
    state: ReportState
    first_party_hit_ms: int | None
    first_party_boss_hit_ms: int | None

    def resolve(self) -> tuple[int, int, str]:
        report_state = self.state
        first_party_hit_ms = self.first_party_hit_ms
        first_party_boss_hit_ms = self.first_party_boss_hit_ms
        if report_state.first_hit_hint_ms is not None:
            return (
                report_state.first_hit_hint_ms,
                report_state.last_hit_hint_ms if report_state.last_hit_hint_ms is not None else report_state.hits[-1]["ts_ms"],
                "hit_hint_window",
            )
        if report_state.first_party_action_ms is not None:
            return report_state.first_party_action_ms, report_state.last_hit_hint_ms if report_state.last_hit_hint_ms is not None else report_state.hits[-1]["ts_ms"], "party_action_window"
        if first_party_boss_hit_ms is not None:
            return first_party_boss_hit_ms, report_state.last_hit_hint_ms if report_state.last_hit_hint_ms is not None else report_state.hits[-1]["ts_ms"], "party_boss_hit_window"
        if first_party_hit_ms is not None:
            return first_party_hit_ms, report_state.last_hit_hint_ms if report_state.last_hit_hint_ms is not None else report_state.hits[-1]["ts_ms"], "party_hit_window"
        return (
            report_state.first_hit_hint_ms if report_state.first_hit_hint_ms is not None else report_state.hits[0]["ts_ms"],
            report_state.last_hit_hint_ms if report_state.last_hit_hint_ms is not None else report_state.hits[-1]["ts_ms"],
            "hit_window",
        )


def initial_hit_window(report_state: ReportState, timer_evidence: dict[str, Any] | None) -> tuple[HitWindow, FallbackWindow]:
    initial_boss_key = report_state.enemy_counter.most_common(1)[0][0] if report_state.enemy_counter else "unknown_boss"
    first_party_hit_ms = next(
        (
            int(hit["ts_ms"])
            for hit in report_state.hits
            if str(hit.get("character_key") or "").startswith("chr_")
            and str(hit.get("target_enemy_key") or "").startswith("eny_")
        ),
        None,
    )
    first_party_boss_hit_ms = next(
        (
            int(hit["ts_ms"])
            for hit in report_state.hits
            if str(hit.get("character_key") or "").startswith("chr_")
            and str(hit.get("target_enemy_key") or "") == initial_boss_key
        ),
        None,
    )

    fallback = FallbackWindow(report_state, first_party_hit_ms, first_party_boss_hit_ms)

    time_source = "observed_challenge_window" if timer_evidence is not None and report_state.official_timer_elapsed_ms is None else "game_timer"
    timeline_zero_source = "game_timer"
    if report_state.game_timer_elapsed_ms is not None:
        timer_window_elapsed_ms = report_state.game_timer_window_elapsed_ms or report_state.game_timer_elapsed_ms
        if (
            report_state.official_timer_elapsed_ms is not None
            and report_state.game_timer_start_ms is not None
            and report_state.game_timer_end_ms is not None
            and report_state.game_timer_end_ms >= report_state.game_timer_start_ms
        ):
            first_hit_ms = report_state.game_timer_start_ms
            last_hit_ms = report_state.game_timer_end_ms
            timeline_zero_source = (
                "official_timer_start"
                if report_state.official_timer_start_ms is not None and report_state.official_timer_start_ms == report_state.game_timer_start_ms
                else "game_timer_start"
            )
        elif report_state.game_timer_start_ms is not None:
            first_hit_ms = report_state.game_timer_start_ms
            last_hit_ms = first_hit_ms + timer_window_elapsed_ms
            timeline_zero_source = (
                "official_timer_start"
                if report_state.official_timer_start_ms is not None and report_state.official_timer_start_ms == report_state.game_timer_start_ms
                else "game_timer_start"
            )
        elif report_state.game_timer_end_ms is not None:
            last_hit_ms = report_state.game_timer_end_ms
            first_hit_ms = last_hit_ms - timer_window_elapsed_ms
            timeline_zero_source = "timer_end_inferred"
        else:
            first_hit_ms = report_state.first_hit_hint_ms if report_state.first_hit_hint_ms is not None else report_state.hits[0]["ts_ms"]
            last_hit_ms = first_hit_ms + timer_window_elapsed_ms
            timeline_zero_source = "timer_elapsed_first_hit_inferred"
    elif report_state.game_timer_start_ms is not None:
        _, fallback_last_hit_ms, _ = fallback.resolve()
        first_hit_ms = report_state.game_timer_start_ms
        last_hit_ms = max(fallback_last_hit_ms, report_state.hits[-1]["ts_ms"])
        timeline_zero_source = (
            "official_timer_start"
            if report_state.official_timer_start_ms is not None and report_state.official_timer_start_ms == report_state.game_timer_start_ms
            else "game_timer_start"
        )
    else:
        first_hit_ms, last_hit_ms, time_source = fallback.resolve()
        timeline_zero_source = time_source
    if last_hit_ms < first_hit_ms:
        last_hit_ms += 24 * 60 * 60 * 1000
    return HitWindow(first_hit_ms, last_hit_ms, time_source, timeline_zero_source), fallback


def crop_hit_window(report_state: ReportState, window: HitWindow, fallback: FallbackWindow,
                    official_scope: dict[str, Any] | None) -> None:
    window.has_game_timer = report_state.game_timer_start_ms is not None or report_state.game_timer_elapsed_ms is not None
    if window.has_game_timer:
        windowed_hits = report_state.hits if official_scope is not None else [
            hit for hit in report_state.hits if window.start_ms <= int(hit["ts_ms"]) <= window.end_ms]
        if windowed_hits:
            report_state.buff_starts = _filter_buff_starts_for_timer_window(
                report_state.buff_starts,
                battle_start_ms=window.start_ms,
            )
            report_state.hits = windowed_hits
            (
                report_state.participant_totals,
                skill_totals,
                report_state.roster_order,
                report_state.roster_seen,
                report_state.enemy_counter,
            ) = _rebuild_hit_totals(report_state.hits, report_state.buff_starts)
        else:
            report_state.timer_window_valid = False
            report_state.game_timer_start_ms = None
            report_state.game_timer_end_ms = None
            report_state.game_timer_elapsed_ms = None
            report_state.game_timer_window_elapsed_ms = None
            window.has_game_timer = False
            window.start_ms, window.end_ms, window.time_source = fallback.resolve()
            window.time_source = "invalid_timer_window"
            window.zero_source = "invalid_timer_window"
            if window.end_ms < window.start_ms:
                window.end_ms += 24 * 60 * 60 * 1000
            if window.time_source in {"party_boss_hit_window", "party_hit_window"}:
                report_state.buff_starts = _filter_buff_starts_for_timer_window(
                    report_state.buff_starts,
                    battle_start_ms=window.start_ms,
                )
                windowed_hits = [hit for hit in report_state.hits if int(hit["ts_ms"]) >= window.start_ms]
                if windowed_hits:
                    report_state.hits = windowed_hits
                    (
                        report_state.participant_totals,
                        skill_totals,
                        report_state.roster_order,
                        report_state.roster_seen,
                        report_state.enemy_counter,
                    ) = _rebuild_hit_totals(report_state.hits, report_state.buff_starts)
    elif window.time_source in {"party_boss_hit_window", "party_hit_window"}:
        report_state.buff_starts = _filter_buff_starts_for_timer_window(
            report_state.buff_starts,
            battle_start_ms=window.start_ms,
        )
        windowed_hits = [hit for hit in report_state.hits if int(hit["ts_ms"]) >= window.start_ms]
        if windowed_hits:
            report_state.hits = windowed_hits
            (
                report_state.participant_totals,
                skill_totals,
                report_state.roster_order,
                report_state.roster_seen,
                report_state.enemy_counter,
            ) = _rebuild_hit_totals(report_state.hits, report_state.buff_starts)


def select_hit_window(report_state: ReportState, timer_evidence: dict[str, Any] | None,
                      official_scope: dict[str, Any] | None) -> HitWindow:
    window, fallback = initial_hit_window(report_state, timer_evidence)
    crop_hit_window(report_state, window, fallback, official_scope)
    return window
