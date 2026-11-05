using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Observed hit counters for an immutable, time-ordered live selection. Records remain report-local.</summary>
internal sealed class LiveParticipantCache
{
    private sealed record Counter(string Name, BigInteger Damage, BigInteger Maximum, BigInteger Critical, BigInteger Count);
    private readonly List<EvidenceObject> accepted = [];
    private readonly List<string> roster = [];
    private readonly Dictionary<string, Counter> totals = new(StringComparer.Ordinal);
    private readonly Dictionary<(string Character, string Target, string Skill), (BigInteger Time, BigInteger Sum)> groups = [];
    private ReportParticipants? owner;
    private BigInteger? latest;
    internal long PreparedHits { get; private set; }
    internal long Rebuilds { get; private set; }
    private static readonly EvidenceText EmptyText = new("");
    private static readonly EvidenceInteger Zero = new(0);
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Truth(value) ? value : EmptyText);
    private static BigInteger Integer(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Truth(value) ? value : Zero);

    private void Clear()
    {
        accepted.Clear(); roster.Clear(); totals.Clear(); groups.Clear(); latest = null;
    }

    internal ReportParticipantInput? Prepare(ReportParticipants analyzer, IReadOnlyList<ReportHitInput> hits,
        Func<string, string?> characterName)
    {
        if (!ReferenceEquals(owner, analyzer)) { Clear(); owner = analyzer; }
        var first = 0;
        while (first < Math.Min(accepted.Count, hits.Count) && ReferenceEquals(accepted[first], hits[first].Evidence)) first++;
        if (first < accepted.Count) { Clear(); first = 0; Rebuilds++; }
        try
        {
            for (var index = first; index < hits.Count; index++)
            {
                var hit = hits[index].Evidence;
                // Caller-owned roots and backdated selections retain the original complete algorithm.
                if (!FrozenEvidence.IsFrozenRoot(hit)) { Clear(); return null; }
                var character = Text(hit.Get("character_key"));
                var time = Integer(hit.Get("ts_ms"));
                if (character.Length == 0) { accepted.Add(hit); continue; }
                if (latest is { } previousTime && time < previousTime) { Clear(); return null; }
                latest = time;
                var damage = Integer(hit.Get("hit_value"));
                var critical = Integer(hit.Get("crit_flag")) != 0 ? 1 : 0;
                var name = CatalogValues.Truth(hit.Get("character_name")) ? Text(hit.Get("character_name"))
                    : characterName(character) is { Length: > 0 } label ? label : character;
                if (!totals.TryGetValue(character, out var counter))
                {
                    roster.Add(character); counter = new(name, 0, 0, 0, 0);
                }
                var group = (character, Text(hit.Get("target_enemy_key")), Text(hit.Get("skill_key")));
                var sum = damage;
                if (groups.TryGetValue(group, out var previous) && time - previous.Time <= 120) sum += previous.Sum;
                groups[group] = (time, sum);
                totals[character] = new(name, counter.Damage + damage,
                    BigInteger.Max(counter.Maximum, BigInteger.Max(damage, sum)), counter.Critical + critical, counter.Count + 1);
                accepted.Add(hit); PreparedHits++;
            }
        }
        catch { Clear(); throw; }
        return new(roster.ToArray(), totals.ToDictionary(pair => pair.Key, pair => BuffEvidence.Object(
            ("character_key", new EvidenceText(pair.Key)), ("character_name", new EvidenceText(pair.Value.Name)),
            ("total_damage", new EvidenceInteger(pair.Value.Damage)), ("max_hit", new EvidenceInteger(pair.Value.Maximum)),
            ("crit_hits", new EvidenceInteger(pair.Value.Critical)), ("hit_count", new EvidenceInteger(pair.Value.Count))), StringComparer.Ordinal));
    }
}
