using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Realtime;

/// <summary>Clock-only suffixes may reuse membership only when every semantic record is inside the old window.</summary>
public static class LiveClockProjection
{
    private static double Number(EvidenceValue value) => EffectIdentity.Float(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static double Rate(EvidenceValue total, double seconds) => PythonDecimalRounding.Round(Number(total) / seconds, 2);
    public static EvidenceObject? TryAdvance(EvidenceObject previous, BigInteger? officialStart,
        IEnumerable<EvidenceValue> semanticTimes, DateOnly referenceDate, string? timerLine, TimeZoneInfo? timeZone = null)
        => string.IsNullOrEmpty(timerLine) ? null : TryAdvance(previous, officialStart, semanticTimes, referenceDate,
            TraceFields.OptionalInteger(TraceFields.Extract(timerLine).GetValueOrDefault("elapsedMs")) ?? BigInteger.Zero, timeZone);

    public static EvidenceObject? TryAdvance(EvidenceObject previous, BigInteger? officialStart,
        IEnumerable<EvidenceValue> semanticTimes, DateOnly referenceDate, BigInteger elapsed, TimeZoneInfo? timeZone = null)
    {
        var battle = (EvidenceObject)previous.Get("battle");
        if (battle.Get("time_source") is not EvidenceText { Value: "game_timer" }
            || !CatalogValues.Truth(battle.Get("official_timer_start_seen")) || CatalogValues.Truth(battle.Get("official_timer_end_seen"))
            || battle.Get("timer_window_valid") is not EvidenceBoolean { Value: true }
            || battle.Get("duration_ms") is not EvidenceInteger duration || duration.Value <= 0 || officialStart is null) return null;
        if (elapsed < duration.Value) return null;
        var oldEnd = new EvidenceInteger(officialStart.Value + duration.Value);
        if (semanticTimes.Any(value => EffectIdentity.CompareKeys(CatalogValues.Or(value, new EvidenceInteger(0)), oldEnd) > 0)) return null;
        var result = (EvidenceObject)BuffEvidence.Clone(previous);
        var updated = (Dictionary<string, EvidenceValue>)((EvidenceObject)result.Get("battle")).Fields;
        var seconds = PythonIntegerDivision.Divide(elapsed, 1000);
        updated["duration_ms"] = new EvidenceInteger(elapsed);
        updated["battle_end_at"] = new EvidenceText(ReportExport.LocalIso(referenceDate, officialStart.Value + elapsed, timeZone));
        updated["total_dps"] = new EvidenceReal(Rate(battle.Get("total_damage"), seconds));
        List<EvidenceObject> active = [], zero = [];
        foreach (var row in ((EvidenceArray)result.Get("participants")).Items.Cast<EvidenceObject>())
        {
            if (!CatalogValues.Truth(row.Get("total_damage")) && !CatalogValues.Truth(row.Get("total_rd"))) { zero.Add(row); continue; }
            var fields = (Dictionary<string, EvidenceValue>)row.Fields;
            fields["dps"] = new EvidenceReal(Rate(row.Get("total_damage"), seconds));
            fields["rdps"] = new EvidenceReal(seconds > .5 ? Number(row.Get("total_rd")) / seconds : 0);
            active.Add(row);
        }
        var ordered = active.OrderByDescending(row => Number(row.Get("dps")))
            .ThenByDescending(row => Rate(row.Get("total_rd"), seconds))
            .ThenBy(row => PythonDisplay.String(row.Get("character_name")), PythonDisplay.CodePointComparer).ToArray();
        ((Dictionary<string, EvidenceValue>)result.Fields)["participants"] = new EvidenceArray(ordered.Concat(zero).ToArray());
        updated["roster"] = new EvidenceArray(ordered.Select((row, index) => (EvidenceValue)BuffEvidence.Object(
            ("slot", new EvidenceInteger(index + 1)), ("character_key", row.Get("character_key")), ("character_name", row.Get("character_name")))).ToArray());
        return result;
    }

    public static IEnumerable<EvidenceValue> SemanticTimes(BattleIngestionStream stream) =>
        stream.Hits.Hits.Select(row => (EvidenceValue)new EvidenceInteger(row.Identity.TimestampMs))
        .Concat(stream.Buffs.Records.Select(row => (EvidenceValue)new EvidenceInteger(row.TimestampMs)))
        .Concat(stream.Hits.Unresolved.Select(row => (EvidenceValue)new EvidenceInteger(row.TimestampMs)))
        .Concat(stream.Buffs.UnresolvedActions.Select(row => row.Evidence.Get("ts_ms")))
        .Concat(stream.Skills.Casts.Select(row => (EvidenceValue)new EvidenceInteger(row.TimestampMs)))
        .Concat(stream.Buffs.DynamicEvents.Select(row => row.Evidence.Get("ts_ms")));
}
