using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record ReportParticipantInput(IReadOnlyList<string> Roster, IReadOnlyDictionary<string, EvidenceObject> Totals)
{
    public static ReportParticipantInput Capture(BattleIngestionStream stream) => new(stream.Party.Roster.ToArray(),
        stream.Party.Participants.ToDictionary(pair => pair.Key, pair => BuffEvidence.Object(
            ("character_key", new EvidenceText(pair.Key)), ("character_name", new EvidenceText(pair.Value.Name)),
            ("total_damage", new EvidenceInteger(pair.Value.Damage)), ("max_hit", new EvidenceInteger(pair.Value.Maximum)),
            ("crit_hits", new EvidenceInteger(pair.Value.CriticalHits)), ("hit_count", new EvidenceInteger(pair.Value.Count))), StringComparer.Ordinal));
}

public sealed record ReportParticipantProjection(IReadOnlyList<EvidenceObject> Participants, IReadOnlyList<EvidenceObject> Roster);

/// <summary>Observed counters and allocated rDMG share one rate and sorting projection.</summary>
public sealed class ReportParticipants(Func<string, string?> characterName)
{
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger Integer(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
    private static Dictionary<string, EvidenceValue> Fields(EvidenceObject row) => (Dictionary<string, EvidenceValue>)row.Fields;
    private static EvidenceObject Empty(string key, string name) => BuffEvidence.Object(
        ("character_key", new EvidenceText(key)), ("character_name", new EvidenceText(name)),
        ("total_damage", new EvidenceInteger(0)), ("max_hit", new EvidenceInteger(0)),
        ("crit_hits", new EvidenceInteger(0)), ("hit_count", new EvidenceInteger(0)));

    public ReportParticipantInput Prepare(ReportParticipantInput input, IReadOnlyList<ReportHitInput> hits,
        IReadOnlyList<EvidenceObject> records, bool rebuild)
        => PrepareCore(input, hits, records, rebuild, null);

    internal ReportParticipantInput PrepareOwned(ReportParticipantInput input, IReadOnlyList<ReportHitInput> hits,
        IReadOnlyList<EvidenceObject> records, bool rebuild, LiveParticipantCache cache)
        => PrepareCore(input, hits, records, rebuild, cache);

    private ReportParticipantInput PrepareCore(ReportParticipantInput input, IReadOnlyList<ReportHitInput> hits,
        IReadOnlyList<EvidenceObject> records, bool rebuild, LiveParticipantCache? cache)
    {
        var reused = rebuild ? cache?.Prepare(this, hits, characterName) : null;
        var roster = reused is not null ? reused.Roster.ToList() : rebuild ? new List<string>() : input.Roster.ToList();
        var seen = new HashSet<string>(roster, StringComparer.Ordinal);
        var totals = reused is not null ? reused.Totals.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal)
            : rebuild ? new Dictionary<string, EvidenceObject>(StringComparer.Ordinal)
            : input.Totals.ToDictionary(pair => pair.Key, pair => (EvidenceObject)BuffEvidence.Clone(pair.Value), StringComparer.Ordinal);
        EvidenceObject Ensure(string key)
        {
            if (seen.Add(key)) roster.Add(key);
            if (!totals.TryGetValue(key, out var row)) totals[key] = row = Empty(key, characterName(key) is { Length: > 0 } name ? name : key);
            return row;
        }
        if (rebuild && reused is null)
        {
            foreach (var hit in hits)
            {
                var key = Text(hit.Evidence.Get("character_key"));
                if (key.Length == 0) continue;
                var row = Ensure(key);
                var value = Integer(hit.Evidence.Get("hit_value"));
                Fields(row)["character_name"] = new EvidenceText(CatalogValues.Truth(hit.Evidence.Get("character_name"))
                    ? Text(hit.Evidence.Get("character_name")) : characterName(key) is { Length: > 0 } name ? name : key);
                Fields(row)["total_damage"] = new EvidenceInteger(Integer(row.Get("total_damage")) + value);
                Fields(row)["max_hit"] = new EvidenceInteger(BigInteger.Max(Integer(row.Get("max_hit")), value));
                Fields(row)["crit_hits"] = new EvidenceInteger(Integer(row.Get("crit_hits")) + (Integer(hit.Evidence.Get("crit_flag")) != 0 ? 1 : 0));
                Fields(row)["hit_count"] = new EvidenceInteger(Integer(row.Get("hit_count")) + 1);
            }
        }
        foreach (var record in records)
            foreach (var field in rebuild ? new[] { "source_character_key", "target_character_key" } : new[] { "source_character_key" })
            {
                if (!CatalogValues.Truth(record.Get(field))) continue;
                var key = Text(record.Get(field));
                Fields(Ensure(key))["character_name"] = new EvidenceText(characterName(key) is { Length: > 0 } name ? name : key);
            }
        if (rebuild && reused is null)
        {
            Dictionary<(string Character, string Target, string Skill), (BigInteger Time, BigInteger Sum)> groups = [];
            foreach (var hit in hits.OrderBy(hit => Integer(hit.Evidence.Get("ts_ms")))
                         .ThenBy(hit => Text(hit.Evidence.Get("character_key")), PythonDisplay.CodePointComparer)
                         .ThenBy(hit => Text(hit.Evidence.Get("skill_key")), PythonDisplay.CodePointComparer))
            {
                var row = hit.Evidence;
                var character = Text(row.Get("character_key"));
                if (character.Length == 0) continue;
                var group = (character, Text(row.Get("target_enemy_key")), Text(row.Get("skill_key")));
                var time = Integer(row.Get("ts_ms"));
                var sum = Integer(row.Get("hit_value"));
                if (groups.TryGetValue(group, out var previous) && time - previous.Time <= 120) sum += previous.Sum;
                groups[group] = (time, sum);
                var participant = totals[character];
                Fields(participant)["max_hit"] = new EvidenceInteger(BigInteger.Max(Integer(participant.Get("max_hit")), sum));
            }
        }
        return new(roster, totals);
    }

    public ReportParticipantProjection Project(ReportParticipantInput input, IReadOnlyDictionary<string, EvidenceObject> loadouts,
        IReadOnlyDictionary<string, double> allocated, BigInteger durationMs)
    {
        List<EvidenceObject> participants = [];
        var seconds = PythonIntegerDivision.Divide(durationMs, 1000);
        foreach (var key in input.Roster)
        {
            if (!input.Totals.TryGetValue(key, out var row) || !CatalogValues.Truth(row.Get("character_name"))) continue;
            var damage = Integer(row.Get("total_damage"));
            if (loadouts.Count > 0 && !loadouts.ContainsKey(key) && damage <= 0) continue;
            var rd = allocated.TryGetValue(key, out var share) ? share : (double)damage;
            if (damage <= 0 && rd <= 0) continue;
            var count = Integer(row.Get("hit_count"));
            var critical = Integer(row.Get("crit_hits"));
            static EvidenceValue Optional(BigInteger value) => value.IsZero ? EvidenceNull.Value : new EvidenceInteger(value);
            participants.Add(BuffEvidence.Object(("character_key", new EvidenceText(key)), ("character_name", BuffEvidence.Clone(row.Get("character_name"))),
                ("total_damage", new EvidenceInteger(damage)), ("total_rd", new EvidenceReal(rd)),
                ("dps", new EvidenceReal(PythonDecimalRounding.Round((double)damage / seconds, 2))),
                ("rdps", new EvidenceReal(PythonDecimalRounding.Round(rd / seconds, 2))),
                ("max_hit", Optional(Integer(row.Get("max_hit")))), ("hit_count", Optional(count)), ("crit_hits", Optional(critical)),
                ("crit_rate", count.IsZero ? EvidenceNull.Value : new EvidenceReal(PythonDecimalRounding.Round(PythonIntegerDivision.Divide(critical, count), 4)))));
        }
        var ordered = participants.OrderByDescending(row => ((EvidenceReal)row.Get("dps")).Value)
            .ThenByDescending(row => ((EvidenceReal)row.Get("rdps")).Value)
            .ThenBy(row => Text(row.Get("character_name")), PythonDisplay.CodePointComparer).ToArray();
        return new(ordered, ordered.Select((row, index) => BuffEvidence.Object(("slot", new EvidenceInteger(index + 1)),
            ("character_key", row.Get("character_key")), ("character_name", row.Get("character_name")))).ToArray());
    }
}
