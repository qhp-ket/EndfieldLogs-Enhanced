using System.Numerics;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public sealed record EntityStatsSnapshot(string? Template, string? Kind, BigInteger? Level,
    IReadOnlyDictionary<BigInteger, double> Attributes, IReadOnlyDictionary<BigInteger, double> BasicAttributes,
    long? TimestampMs, IReadOnlyList<BigInteger> InvalidAttributeTypes, IReadOnlyList<string> InvalidAttributeTokens,
    bool AttributeListPresent, int? LineNumber=null);
public sealed record EntityStatsEvidence(string EntityId, EntityStatsSnapshot Snapshot);
public sealed record EntityAttributeObservation(BigInteger? Type, double? Value, double? BasicValue, string? InvalidToken = null);

public sealed class CriticalAttributeObservation(string? template)
{
    public string? Template { get; } = template;
    public Dictionary<int, double> Values { get; } = [];
    public Dictionary<int, int> Lines { get; } = [];
    public Dictionary<int, long?> Times { get; } = [];
}

public static class EntityStatsDecoder
{
    public static EntityStatsSnapshot Snapshot(string? template, string? kind, BigInteger? level,
        IEnumerable<EntityAttributeObservation> observations, long? timestampMs, bool attributeListPresent)
    {
        Dictionary<BigInteger, double> attrs = [], basic = [];
        HashSet<BigInteger> seen = [], invalid = [];
        List<string> invalidTokens = [];
        foreach (var row in observations)
        {
            if (row.Type is not BigInteger attr)
            { if (row.InvalidToken is not null) invalidTokens.Add(row.InvalidToken); continue; }
            if (seen.Contains(attr) || row.Value is null)
            { invalid.Add(attr); attrs.Remove(attr); basic.Remove(attr); }
            else if (!invalid.Contains(attr))
            { attrs[attr] = row.Value.Value; if (row.BasicValue is double baseValue) basic[attr] = baseValue; }
            seen.Add(attr);
        }
        return new(template, kind, level, attrs, basic, timestampMs, invalid.Order().ToArray(), invalidTokens, attributeListPresent);
    }

    public static EntityStatsEvidence? Parse(string line)
    {
        if (!line.Contains(" ENTITY_STATS ", StringComparison.Ordinal)) return null;
        var fields = TraceFields.Extract(line);
        var entityId = fields.GetValueOrDefault("id") ?? "";
        if (!Regex.IsMatch(entityId, @"\A[1-9]\d*\z")) return null;
        List<EntityAttributeObservation> observations = [];
        var match = Regex.Match(line, @"\battrs=\[(?<attrs>[^\]]*)\]");
        foreach (var token in Regex.Split(match.Groups["attrs"].Value, @"\s+").Where(value => value.Length > 0))
        {
            var separator = token.IndexOf(':');
            if (separator < 0) { observations.Add(new(null, null, null, token)); continue; }
            var type = TraceFields.OptionalInteger(token[..separator]);
            var raw = token[(separator+1)..];
            var slash = raw.IndexOf('/');
            var value = TraceFields.OptionalFloat(slash < 0 ? raw : raw[..slash]);
            observations.Add(new(type, value, slash >= 0 ? TraceFields.OptionalFloat(raw[(slash+1)..]) : null, type is null ? token : null));
        }
        return new(entityId, Snapshot(fields.GetValueOrDefault("template"), fields.GetValueOrDefault("kind"),
            TraceFields.OptionalInteger(fields.GetValueOrDefault("level")), observations, TraceFields.PrefixedTimestampMs(line), match.Success));
    }
}

/// <summary>Full snapshots form a timeline; partial updates affect only critical observations.</summary>
public sealed class EntityObservationState
{
    public Dictionary<string, List<(long TimestampMs, EntityStatsSnapshot Snapshot)>> Timelines { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, CriticalAttributeObservation> CriticalAttributesByActor { get; } = new(StringComparer.Ordinal);

    public EntityStatsSnapshot? SnapshotAt(string? entityId, long timestampMs)
    {
        if (!Timelines.TryGetValue(entityId ?? "", out var rows)) return null;
        EntityStatsSnapshot? chosen = null;
        long? chosenTime = null;
        foreach (var row in rows)
            if (row.TimestampMs <= timestampMs && (chosenTime is null || row.TimestampMs >= chosenTime))
            { chosen = row.Snapshot; chosenTime = row.TimestampMs; }
        return chosen;
    }

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        if (EntityStatsDecoder.Parse(line) is { } full)
        {
            Observe(full, lineNumber, timestampMs);
            return true;
        }
        const string partial = " ENTITY_ATTR_UPDATE ";
        var index = line.IndexOf(partial, StringComparison.Ordinal);
        if (index < 0) return false;
        var replaced = line[..index]+" ENTITY_STATS "+line[(index+partial.Length)..];
        if (EntityStatsDecoder.Parse(replaced) is { } update)
            Observe(update, lineNumber, timestampMs, partial: true);
        return true;
    }

    public void Observe(EntityStatsEvidence evidence, int lineNumber, long timestampMs, bool partial = false)
    {
        var snapshot = evidence.Snapshot with { TimestampMs = timestampMs, LineNumber = partial ? null : lineNumber };
        if (!partial)
        {
            if (!Timelines.TryGetValue(evidence.EntityId, out var rows)) Timelines[evidence.EntityId] = rows = [];
            rows.Add((timestampMs, snapshot));
        }
        UpdateCritical(evidence.EntityId, snapshot, lineNumber, partial);
    }

    private void UpdateCritical(string entityId, EntityStatsSnapshot snapshot, int lineNumber, bool partial)
    {
        if (!partial)
        {
            if (snapshot.Kind != "character") { CriticalAttributesByActor.Remove(entityId); return; }
            var state = new CriticalAttributeObservation(snapshot.Template);
            foreach (var attr in new[] { 9, 10 })
            {
                if (snapshot.Attributes.TryGetValue(attr, out var value)) state.Values[attr] = value;
                state.Lines[attr] = lineNumber;
                state.Times[attr] = snapshot.TimestampMs;
            }
            CriticalAttributesByActor[entityId] = state;
            return;
        }
        if (!CriticalAttributesByActor.TryGetValue(entityId, out var prior)) return;
        if (prior.Template != snapshot.Template) { CriticalAttributesByActor.Remove(entityId); return; }
        foreach (var attr in new[] { 9, 10 })
        {
            if (snapshot.InvalidAttributeTypes.Contains(attr)) prior.Values.Remove(attr);
            else if (snapshot.Attributes.TryGetValue(attr, out var value))
            {
                prior.Values[attr] = value;
                prior.Lines[attr] = lineNumber;
                prior.Times[attr] = snapshot.TimestampMs;
            }
        }
    }
}
