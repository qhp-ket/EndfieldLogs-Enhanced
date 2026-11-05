using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Runtime.History;

public sealed record DamageSeriesPoint(double TimeMs, IReadOnlyDictionary<string, double> Values);
public sealed record DamageSeriesResult(string Metric, IReadOnlyList<DamageSeriesPoint> Points, int Missing, int Hits, double DurationMs);

/// <summary>Read-only one-second canonical damage projection, matching the maintained Qt view.</summary>
public static class DamageSeries
{
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue? value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static double? Number(EvidenceValue? value)
    {
        var result = value switch { EvidenceReal real => real.Value, EvidenceInteger integer => (double)integer.Value,
            EvidenceBoolean boolean => boolean.Value ? 1d : 0d, EvidenceText text => TraceFields.Float(text.Value, double.NaN), _ => double.NaN };
        return double.IsFinite(result) ? result : null;
    }
    private static string Text(EvidenceValue value) => value is EvidenceText text ? text.Value : "";
    public static DamageSeriesResult Build(EvidenceObject snapshot, string metric = "rdmg", string character = "")
    {
        var duration = Number((snapshot.Get("battle") as EvidenceObject)?.Get("duration_ms")) ?? 0;
        if (duration <= 0 || metric is not ("dmg" or "dps" or "rdmg" or "rdps")) return new(metric, [], 0, 0, Math.Max(0, duration));
        var relative = metric is "rdmg" or "rdps"; var buckets = new Dictionary<double, Dictionary<string, double>>();
        var owners = new HashSet<string>(Rows(snapshot.Get("participants")).Select(row => Text(row.Get("character_key"))).Where(key => key.Length > 0), StringComparer.Ordinal);
        var missing = 0; var hits = 0; var count = Math.Ceiling(duration / 1000);
        foreach (var row in Rows(snapshot.Get("timeline_events")))
        {
            var stamp = Number(row.Get("ts_ms_from_start"));
            if (Text(row.Get("event_type")) != "damage" || stamp is null || stamp < 0 || stamp > duration) continue;
            hits++; var bucket = Math.Min(count - 1, Math.Floor(stamp.Value / 1000));
            var values = relative ? Rows(row.Get("rdps_contributions")).Select(item => (Owner: Text(item.Get("character_key")), Value: Number(item.Get("value"))))
                .Where(item => item.Owner.Length > 0 && item.Value is not null).ToArray() : [(Text(row.Get("source_character_key")), Number(row.Get("value")))];
            if (relative && values.Length == 0) missing++;
            foreach (var (owner, value) in values)
            {
                if (value is null || character.Length > 0 && owner != character) continue;
                owners.Add(owner); if (!buckets.TryGetValue(bucket, out var bin)) buckets[bucket] = bin = new(StringComparer.Ordinal);
                bin[owner] = bin.GetValueOrDefault(owner) + value.Value;
            }
        }
        if (relative && hits == missing) return new(metric, [], missing, hits, duration);
        var totals = owners.Where(owner => character.Length == 0 || owner == character).ToDictionary(owner => owner, _ => 0d, StringComparer.Ordinal);
        List<DamageSeriesPoint> points = [new(0, new Dictionary<string, double>(totals))];
        for (double bucket = 0; bucket < count; bucket++)
        {
            if (buckets.TryGetValue(bucket, out var bin)) foreach (var (owner, value) in bin) totals[owner] = totals.GetValueOrDefault(owner) + value;
            var end = Math.Min(duration, (bucket + 1) * 1000); var divisor = metric is "dps" or "rdps" ? end / 1000 : 1;
            points.Add(new(end, totals.ToDictionary(pair => pair.Key, pair => pair.Value / divisor, StringComparer.Ordinal)));
        }
        return new(metric, points, missing, hits, duration);
    }
}
