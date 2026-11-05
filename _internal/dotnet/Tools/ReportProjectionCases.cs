using System.Numerics;
using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Reporting;

internal static class ReportProjectionCases
{
    private static IReadOnlyList<EvidenceObject> Rows(EvidenceValue value) => ((EvidenceArray)value).Items.Cast<EvidenceObject>().ToArray();
    private static readonly IReadOnlyDictionary<string, string> Labels = new Dictionary<string, string>
        { ["a"] = "阿尔法", ["b"] = "贝塔", ["c"] = "Gamma", ["supp"] = "辅助", ["emoji"] = "😀", ["private"] = "\ue000" };
    private static ReportHitInput Hit(EvidenceObject row) => new(row, new Dictionary<BigInteger, EvidenceValue>(),
        new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>());

    public static int Run(string inputPath, string outputPath)
    {
        var cases = JsonNode.Parse(File.ReadAllText(inputPath))!.AsArray();
        JsonArray results = [];
        var ownedComparisons = 0;
        foreach (var test in cases)
        {
            var config = (EvidenceObject)EvidenceJson.Parse(test!["config_json"]!.GetValue<string>());
            var before = EvidenceJsonSignature.Sorted(config);
            var hits = Rows(config.Get("hits")).Select(Hit).ToArray();
            var records = Rows(config.Get("records"));
            object projected;
            if (config.Get("operation") is EvidenceText { Value: "sources" })
            {
                var calculation = new ReportCalculationInput(new(new([], new Dictionary<string, EvidenceObject>()), hits,
                    new Dictionary<string, HashSet<string>>()), records, [], []);
                var sources = new ReportSourceInput(Rows(config.Get("casts")), Rows(config.Get("dynamic")), Rows(config.Get("refresh")),
                    Rows(config.Get("poise")), ((EvidenceObject)config.Get("last_seen")).Fields.ToDictionary(pair => pair.Key,
                        pair => (long)((EvidenceInteger)pair.Value).Value), Rows(config.Get("atb")));
                var prepared = ReportSourcePreparation.Prepare(calculation, sources);
                projected = new Dictionary<string, object?>
                {
                    ["hits"] = prepared.Calculation.Baseline.Hits.Select(hit => hit.Evidence).ToArray(), ["records"] = prepared.Calculation.Records,
                    ["casts"] = prepared.Sources.Casts, ["dynamic"] = prepared.Sources.DynamicEvents, ["refresh"] = prepared.Sources.RefreshEvents,
                    ["poise"] = prepared.Sources.PoiseEvents, ["atb"] = prepared.Sources.AtbEvents, ["last_seen"] = prepared.Sources.ModifierLastSeen,
                };
            }
            else
            {
                ReportParticipants participants = new(key => Labels.GetValueOrDefault(key));
                var counters = participants.Prepare(new(((EvidenceArray)config.Get("roster")).Items.Cast<EvidenceText>().Select(value => value.Value).ToArray(),
                    ((EvidenceObject)config.Get("totals")).Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value)), hits, records,
                    config.Get("rebuild") is EvidenceBoolean { Value: true });
                var projection = participants.Project(counters, ((EvidenceObject)config.Get("loadouts")).Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value),
                    ((EvidenceObject)config.Get("allocated")).Fields.ToDictionary(pair => pair.Key, pair => pair.Value is EvidenceReal value
                        ? value.Value : (double)((EvidenceInteger)pair.Value).Value), ((EvidenceInteger)config.Get("duration_ms")).Value);
                projected = new Dictionary<string, object?> { ["totals"] = counters.Totals, ["roster"] = counters.Roster,
                    ["participants"] = projection.Participants, ["roster_projection"] = projection.Roster };
                var immutable = hits.Select(hit => hit with { Evidence = (EvidenceObject)FrozenEvidence.Capture(hit.Evidence) }).ToArray();
                var participantInput = new ReportParticipantInput(((EvidenceArray)config.Get("roster")).Items.Cast<EvidenceText>().Select(value => value.Value).ToArray(),
                    ((EvidenceObject)config.Get("totals")).Fields.ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value));
                LiveParticipantCache cache = new();
                for (var repeat = 0; repeat < 3; repeat++)
                {
                    if (repeat == 2)
                    {
                        cache = new();
                        participants.PrepareOwned(participantInput, immutable.Take(Math.Max(0, immutable.Length - 1)).ToArray(), records,
                            config.Get("rebuild") is EvidenceBoolean { Value: true }, cache);
                    }
                    var owned = participants.PrepareOwned(participantInput, immutable, records,
                        config.Get("rebuild") is EvidenceBoolean { Value: true }, cache);
                    if (!owned.Roster.SequenceEqual(counters.Roster) || owned.Totals.Count != counters.Totals.Count
                        || !owned.Totals.All(pair => counters.Totals.TryGetValue(pair.Key, out var value) && EffectRecordCache.Same(pair.Value, value)))
                        throw new InvalidOperationException("Immutable participant counters differ: " + test["name"]);
                    ownedComparisons++;
                }
            }
            var actual = FieldCases.Canonical(projected);
            results.Add(new JsonObject { ["name"] = test["name"]!.GetValue<string>(), ["actual"] = actual,
                ["passed"] = JsonNode.DeepEquals(actual, test["expected"]) && before == EvidenceJsonSignature.Sorted(config) });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, results.ToJsonString());
        var failed = results.Count(row => !row!["passed"]!.GetValue<bool>());
        Console.WriteLine($"Report projection differential: {results.Count} cases, {failed} differences; {ownedComparisons} immutable cold/hot/append comparisons");
        return failed == 0 ? 0 : 1;
    }
}
