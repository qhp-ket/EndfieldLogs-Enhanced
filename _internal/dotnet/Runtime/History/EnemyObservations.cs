using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

public sealed record EnemyIdentity(string Character, string Actor);
public sealed record PoiseObservation(double Time, double Value, EvidenceValue Change, bool Ambiguous);
public sealed record EnemyObservationTrack(EnemyIdentity Key, string Name, IReadOnlyList<PoiseObservation> Samples, double? Peak);
public sealed record EnemyObservationResult(IReadOnlyList<EnemyObservationTrack> Tracks, IReadOnlyList<EvidenceObject> Snapshots);

/// <summary>Instance-separated entity snapshots and per-hit evidence; no simulation between observations.</summary>
public static class EnemyObservations
{
    public static IReadOnlyList<(string Key, string Name, int Attribute)> Elements { get; } =
        [("physical", "物理", 94), ("natural", "自然", 95), ("cryst", "寒冷", 96), ("pulse", "电磁", 97), ("fire", "灼热", 98), ("ether", "源石", 99)];
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static string Text(EvidenceValue value, string fallback = "") => SettingsData.Truth(value) ? PythonDisplay.String(value) : fallback;
    private static double? Number(EvidenceValue value) => value is EvidenceBoolean flag ? flag.Value ? 1 : 0 : SettingsData.Number(value, double.NaN) is var number && double.IsFinite(number) ? number : null;
    private static EvidenceValue NumericKey(EvidenceValue value) => value switch
    {
        EvidenceBoolean flag => new EvidenceInteger(flag.Value ? 1 : 0),
        EvidenceReal real when double.IsFinite(real.Value) && Math.Truncate(real.Value) == real.Value => new EvidenceInteger(new System.Numerics.BigInteger(real.Value)),
        EvidenceArray array => new EvidenceArray(array.Items.Select(NumericKey).ToArray()), _ => value,
    };
    private static string Signature(params object?[] fields) => PythonSortedJson.Serialize(NumericKey(SettingsData.Value(fields)), compact: true);
    public static EnemyIdentity Identity(EvidenceObject row) => new(Text(row.Get("target_character_key")), Text(row.Get("target_actor_id")));
    public static string Label(EvidenceObject row)
    {
        var name = Text(row.Get("target_character_name"), Text(row.Get("target_character_key"), "未知目标")); var actor = Text(row.Get("target_actor_id"));
        return actor.Length > 0 ? name + " #" + actor : name + "（实例未知）";
    }
    public static double? HitResistance(EvidenceObject row)
    {
        var element = Elements.FirstOrDefault(element => element.Key == Text(row.Get("damage_element")));
        if (element.Key is null || row.Get("packet_attr_conflict") is not EvidenceBoolean { Value: false }) return null;
        var tokens = ((row.Get("packet_attr_details") as EvidenceObject)?.Get("defender") as EvidenceArray)?.Items ?? [];
        List<double?> values = [];
        foreach (var token in tokens)
        {
            var text = PythonDisplay.String(token); var separator = text.IndexOf(':');
            if ((separator < 0 ? text : text[..separator]) != element.Attribute.ToString(System.Globalization.CultureInfo.InvariantCulture)) continue;
            foreach (var value in (separator < 0 ? "" : text[(separator + 1)..]).Split(',')) values.Add(Number(new EvidenceText(value)));
        }
        return values.Count > 0 && values.All(value => value is not null) && values.Distinct().Count() == 1 ? values[0] : null;
    }
    public static EnemyObservationResult Build(EvidenceObject snapshot)
    {
        Dictionary<EnemyIdentity, (string Name, List<PoiseObservation> Samples)> tracks = []; List<EvidenceObject> snapshots = []; HashSet<string> seen = [];
        Dictionary<string, (double Time, double Value, EvidenceValue Change, List<EnemyIdentity> Targets)> candidates = new(StringComparer.Ordinal);
        foreach (var row in Rows(snapshot.Get("timeline_events")).Where(row => Text(row.Get("event_type")) == "damage"))
        {
            var key = Identity(row); if (key.Character.Length == 0) continue;
            tracks.TryAdd(key, (Label(row), [])); var entity = row.Get("target_entity") as EvidenceObject;
            var signature = Signature(key.Character, key.Actor, entity?.Get("target_stats_snapshot_ts_ms"), entity?.Get("target_stats_snapshot_line_no"));
            if (entity is { Fields.Count: > 0 } && seen.Add(signature))
            {
                var values = SettingsData.Make(("name", Label(row)), ("key", new[] { key.Character, key.Actor })).Fields.ToDictionary();
                foreach (var (field, value) in entity.Fields) values[field] = value;
                snapshots.Add(new(values));
            }
            var poise = row.Get("poise_damage") as EvidenceObject;
            if (poise is null || Number(poise.Get("current_value")) is not { } current) continue;
            var stamp = Number(row.Get("ts_ms_from_start")) ?? 0;
            signature = Signature(stamp, poise.Get("source"), poise.Get("source_int"), poise.Get("orig_source_int"), current, poise.Get("value"));
            if (!candidates.TryGetValue(signature, out var candidate)) candidates[signature] = candidate = (stamp, current, poise.Get("value"), []);
            candidate.Targets.Add(key);
        }
        foreach (var candidate in candidates.Values)
        {
            var ambiguous = candidate.Targets.Distinct().Count() > 1; var key = ambiguous ? new EnemyIdentity("", "unbound") : candidate.Targets[^1];
            if (ambiguous) tracks.TryAdd(key, ("目标未绑定（同刻多目标命中）", []));
            tracks[key].Samples.Add(new(candidate.Time, candidate.Value, candidate.Change, ambiguous));
        }
        return new(tracks.Select(pair =>
        {
            // Stable last-wins at each timestamp, separately for each enemy instance.
            var points = pair.Value.Samples.OrderBy(point => point.Time).GroupBy(point => point.Time).Select(group => group.Last()).ToArray();
            return new EnemyObservationTrack(pair.Key, pair.Value.Name, points, points.Length > 0 ? points.Max(point => point.Value) : null);
        }).ToArray(), snapshots);
    }
}
