using System.Numerics;
using System.Text;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Timing;

namespace EndfieldLogs.Core.Reporting;

public sealed record BattleReportWindow(BigInteger StartMs, BigInteger EndMs, string TimeSource, string ZeroSource, bool HasGameTimer);

public sealed record ReportLifecycleResult(ReportCalculationInput Input, ReportTimingInput Timing,
    BattleReportWindow? Window, OfficialTimerEvidence? OfficialEvidence, BigInteger? ObservedOfficialElapsedMs,
    bool RebuildTotals)
{
    public BigInteger DurationMs => BigInteger.Max(Timing.GameElapsedMs ?? (Window is null ? 0 : Window.EndMs - Window.StartMs), 1);
    public double TimelineScale => Window is { HasGameTimer: true } window
        ? PythonIntegerDivision.Divide(DurationMs, BigInteger.Max(window.EndMs - window.StartMs, 1)) : 1.0;
    public BigInteger OffsetMs(BigInteger timestampMs, bool clamp = true)
    {
        if (Window is null) throw new InvalidOperationException("An empty report has no hit timeline");
        var value = Math.Round((double)(timestampMs - Window.StartMs) * TimelineScale, MidpointRounding.ToEven);
        var offset = new BigInteger(value);
        return clamp ? BigInteger.Max(offset, 0) : offset;
    }
}

/// <summary>Report-local challenge scope and coordinates; receipt clocks never replace server duration.</summary>
public sealed class ReportLifecycle(Func<string, DungeonContext?> resolveDungeon)
{
    private const int DayMs = 86_400_000;
    private static BigInteger Integer(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Time(ReportHitInput hit) => Integer(hit.Evidence.Get("ts_ms"));

    public static ReportLifecycle Load(ResourceFiles files) => new(new DungeonCatalog(files).Resolve);

    public ReportLifecycleResult Select(ReportCalculationInput input, ReportTimingInput timing, string text,
        int? lineCount = null, IEnumerable<(int LineNumber, string Text)>? indexedTimerLines = null)
    {
        var evidence = timing.HasCollectedOfficialEvidence && indexedTimerLines is null ? timing.CollectedOfficialEvidence
            : TimerEvidenceCollector.Collect(text, timing.ObservedTimes, indexedTimerLines);
        var timer = timing;
        if (evidence is not null)
        {
            var start = evidence.Start;
            var complete = evidence.Complete;
            var raw = complete?.PassTimeMs;
            BigInteger? elapsed = raw is { Length: > 0 } && raw.EnumerateRunes().All(Rune.IsDigit)
                && TraceFields.OptionalInteger(raw) is { } positive && positive > 0 ? positive : null;
            var passed = complete?.IsPass == "1";
            timer = timer with
            {
                DungeonId = start?.GameId is { Length: > 0 } id ? id : timer.DungeonId,
                Dungeon = start?.GameId is { Length: > 0 } game ? resolveDungeon(game) : timer.Dungeon,
                OfficialStartMs = start?.ObservedMs, OfficialEndMs = complete?.ObservedMs, OfficialElapsedMs = elapsed,
                OfficialPassConfirmed = passed, ChallengePassConfirmed = timer.ChallengePassConfirmed || passed,
                GameStartMs = start?.ObservedMs, GameEndMs = complete?.ObservedMs,
                GameElapsedMs = elapsed ?? timer.LiveElapsedMs, GameWindowElapsedMs = elapsed ?? timer.LiveElapsedMs,
                StartSeen = start?.ObservedMs is not null, EndSeen = complete?.ObservedMs is not null,
                CompletionSource = passed ? "official_timer_end" : timer.CompletionSource,
            };
        }
        BigInteger? observedElapsed = timer.OfficialStartMs is { } observedStart && timer.OfficialEndMs is { } observedEnd
            && observedEnd >= observedStart ? observedEnd - observedStart : null;
        var hits = input.Baseline.Hits;
        if (evidence?.Start is { } scope)
        {
            var endLine = (BigInteger?)evidence.Complete?.Line ?? (BigInteger)(lineCount ?? timing.EvidenceCount ?? PythonTextLines.Split(text).Count()) + 1;
            foreach (var boundary in evidence.Events.Where(row => row.Kind == TimerLifecycleKind.Boundary
                         && (string.IsNullOrEmpty(row.GameId) || row.GameId == scope.GameId)))
                endLine = BigInteger.Min(endLine, boundary.Line);
            hits = hits.Where(hit => Integer(hit.Evidence.Get("line_no")) > scope.Line
                && Integer(hit.Evidence.Get("line_no")) < endLine).ToArray();
        }
        ReportCalculationInput Selected(IReadOnlyList<ReportHitInput> selected, IReadOnlyList<EvidenceObject> records) =>
            input with { Baseline = input.Baseline with { Hits = selected }, Records = records };
        if (hits.Count == 0) return new(Selected(hits, input.Records), timer, null, evidence, observedElapsed, false);

        // The reference chooses the initial boss from pre-crop counters, preserving insertion order on ties.
        var boss = timer.EnemyCounts.OrderByDescending(pair => pair.Value).FirstOrDefault().Key ?? "unknown_boss";
        var firstParty = hits.FirstOrDefault(hit => Text(hit.Evidence.Get("character_key")).StartsWith("chr_", StringComparison.Ordinal)
            && Text(hit.Evidence.Get("target_enemy_key")).StartsWith("eny_", StringComparison.Ordinal));
        var firstBoss = hits.FirstOrDefault(hit => Text(hit.Evidence.Get("character_key")).StartsWith("chr_", StringComparison.Ordinal)
            && Text(hit.Evidence.Get("target_enemy_key")) == boss);
        (BigInteger Start, BigInteger End, string Source) Fallback()
        {
            var last = timer.LastHitHintMs ?? Time(hits[^1]);
            if (timer.FirstHitHintMs is { } hint) return (hint, last, "hit_hint_window");
            if (timer.FirstPartyActionMs is { } action) return (action, last, "party_action_window");
            if (firstBoss is not null) return (Time(firstBoss), last, "party_boss_hit_window");
            if (firstParty is not null) return (Time(firstParty), last, "party_hit_window");
            return (Time(hits[0]), last, "hit_window");
        }
        var source = evidence is not null && timer.OfficialElapsedMs is null ? "observed_challenge_window" : "game_timer";
        var zero = "game_timer";
        string StartSource() => timer.OfficialStartMs is not null && timer.OfficialStartMs == timer.GameStartMs
            ? "official_timer_start" : "game_timer_start";
        BigInteger first, last;
        if (timer.GameElapsedMs is { } gameElapsed)
        {
            var span = timer.GameWindowElapsedMs is { IsZero: false } windowElapsed ? windowElapsed : gameElapsed;
            if (timer.OfficialElapsedMs is not null && timer.GameStartMs is { } gameStart && timer.GameEndMs is { } gameEnd && gameEnd >= gameStart)
                (first, last, zero) = (gameStart, gameEnd, StartSource());
            else if (timer.GameStartMs is { } start) (first, last, zero) = (start, start + span, StartSource());
            else if (timer.GameEndMs is { } end) (first, last, zero) = (end - span, end, "timer_end_inferred");
            else
            {
                first = timer.FirstHitHintMs ?? Time(hits[0]);
                (last, zero) = (first + span, "timer_elapsed_first_hit_inferred");
            }
        }
        else if (timer.GameStartMs is { } start)
            (first, last, zero) = (start, BigInteger.Max(Fallback().End, Time(hits[^1])), StartSource());
        else
        {
            (first, last, source) = Fallback();
            zero = source;
        }
        if (last < first) last += DayMs;
        var hasTimer = timer.GameStartMs is not null || timer.GameElapsedMs is not null;
        var records = input.Records;
        var rebuild = false;
        if (hasTimer)
        {
            var cropped = evidence?.Start is not null ? hits : hits.Where(hit => first <= Time(hit) && Time(hit) <= last).ToArray();
            if (cropped.Count > 0)
            {
                records = FilterRecords(records, first);
                hits = cropped;
                rebuild = true;
            }
            else
            {
                timer = timer with { WindowValid = false, GameStartMs = null, GameEndMs = null, GameElapsedMs = null, GameWindowElapsedMs = null };
                hasTimer = false;
                (first, last, _) = Fallback();
                source = zero = "invalid_timer_window";
                if (last < first) last += DayMs;
            }
        }
        else if (source is "party_boss_hit_window" or "party_hit_window")
        {
            records = FilterRecords(records, first);
            var cropped = hits.Where(hit => Time(hit) >= first).ToArray();
            if (cropped.Length > 0) { hits = cropped; rebuild = true; }
        }
        return new(Selected(hits, records), timer, new(first, last, source, zero, hasTimer), evidence, observedElapsed, rebuild);
    }

    private static IReadOnlyList<EvidenceObject> FilterRecords(IReadOnlyList<EvidenceObject> records, BigInteger start) => records.Where(row =>
    {
        var time = Integer(row.Get("ts_ms"));
        if (!CatalogValues.Truth(row.Get("target_enemy_key")) || time >= start) return true;
        if (row.Get("end_ts_ms") is not EvidenceNull) return Integer(row.Get("end_ts_ms")) >= start;
        if (row.Get("raw_duration_ms") is not EvidenceNull && Integer(row.Get("raw_duration_ms")) > 0)
            return time + Integer(row.Get("raw_duration_ms")) >= start;
        return row.Get("packet_modifier_last_seen_ts_ms") is not EvidenceNull && Integer(row.Get("packet_modifier_last_seen_ts_ms")) >= start;
    }).ToArray();
}
