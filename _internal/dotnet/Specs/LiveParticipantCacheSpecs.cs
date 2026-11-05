using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class LiveParticipantCacheSpecs
{
    private static readonly ReportParticipantInput Empty = new([], new Dictionary<string, EvidenceObject>());
    private static ReportHitInput Hit(int time, int damage, int critical = 0) => new((EvidenceObject)FrozenEvidence.Capture(BuffEvidence.Object(
        ("character_key", new EvidenceText("a")), ("target_enemy_key", new EvidenceText("enemy")), ("skill_key", new EvidenceText("skill")),
        ("hit_value", new EvidenceInteger(damage)), ("ts_ms", new EvidenceInteger(time)), ("crit_flag", new EvidenceInteger(critical)))),
        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());
    private static BigInteger Number(ReportParticipantInput value, string field) => ((EvidenceInteger)value.Totals["a"].Get(field)).Value;
    private static bool Same(ReportParticipantInput left, ReportParticipantInput right) => left.Roster.SequenceEqual(right.Roster)
        && left.Totals.Count == right.Totals.Count && left.Totals.All(pair => right.Totals.TryGetValue(pair.Key, out var other) && EvidenceJson.PythonEquals(pair.Value, other));

    public static void Run(Action<bool, string> check)
    {
        ReportParticipants analyzer = new(key => "name-" + key);
        LiveParticipantCache cache = new();
        var one = Hit(1000, 60, 1); var two = Hit(1100, 40); var three = Hit(1200, 20, 1);
        var first = analyzer.PrepareOwned(Empty, [one, two], [], true, cache);
        var prepared = cache.PreparedHits;
        var appended = analyzer.PrepareOwned(Empty, [one, two, three], [], true, cache);
        check(cache.PreparedHits == prepared + 1 && Number(first, "max_hit") == 100 && Number(appended, "max_hit") == 120
            && Number(appended, "total_damage") == 120 && Number(appended, "crit_hits") == 2 && Number(appended, "hit_count") == 3,
            "A live append updates only the new observed hit and continues the existing 120ms grouped maximum");
        ((IDictionary<string, EvidenceValue>)appended.Totals["a"].Fields)["total_damage"] = new EvidenceInteger(-1);
        var repeated = analyzer.PrepareOwned(Empty, [one, two, three], [], true, cache);
        check(Number(repeated, "total_damage") == 120 && Number(first, "total_damage") == 100,
            "Editable participant snapshots cannot change cached counters or an earlier published snapshot");
        var corrected = Hit(1100, 10);
        var changed = analyzer.PrepareOwned(Empty, [one, corrected, three], [], true, cache);
        check(cache.Rebuilds == 1 && Number(changed, "total_damage") == 90 && Number(changed, "max_hit") == 90
            && Same(changed, analyzer.Prepare(Empty, [one, corrected, three], [], true)),
            "A revised old hit rebuilds observed totals and grouped maxima with the original ordering semantics");
        var selected = analyzer.PrepareOwned(Empty, [corrected, three], [], true, cache);
        var empty = analyzer.PrepareOwned(Empty, [], [], true, cache);
        check(Number(selected, "max_hit") == 30 && empty.Roster.Count == 0 && empty.Totals.Count == 0,
            "Changing the selected window and clearing it retracts earlier counters and maxima");
        var unordered = analyzer.PrepareOwned(Empty, [three, corrected, one], [], true, cache);
        check(Same(unordered, analyzer.Prepare(Empty, [three, corrected, one], [], true)),
            "Backdated input falls back to the original sorted grouping instead of treating arrival order as time order");
        var record = BuffEvidence.Object(("source_character_key", new EvidenceText("b")), ("target_character_key", new EvidenceText("c")));
        var named = analyzer.PrepareOwned(Empty, [one], [record], true, cache);
        var removed = analyzer.PrepareOwned(Empty, [one], [], true, cache);
        check(named.Roster.SequenceEqual(new[] { "a", "b", "c" }) && removed.Roster.SequenceEqual(new[] { "a" })
            && Same(named, analyzer.Prepare(Empty, [one], [record], true)),
            "Current record participants remain report-local and disappear when their evidence leaves the selection");
        ReportParticipants other = new(_ => "different-name");
        check(other.PrepareOwned(Empty, [one], [], true, cache).Totals["a"].Get("character_name") is EvidenceText { Value: "different-name" },
            "A different participant resolver cannot reuse the previous owner's cached names");
        long Cost(int count)
        {
            LiveParticipantCache sized = new(); var hits = Enumerable.Range(0, count + 1).Select(index => Hit(index, 1)).ToArray();
            analyzer.PrepareOwned(Empty, hits[..count], [], true, sized); var before = sized.PreparedHits;
            analyzer.PrepareOwned(Empty, hits, [], true, sized); return sized.PreparedHits - before;
        }
        check(Cost(8) == 1 && Cost(1024) == 1,
            "The same appended hit requires one counter update after short or long completed history");
    }
}
