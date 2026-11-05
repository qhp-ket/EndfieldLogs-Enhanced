using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record ReportCriticalResult(IReadOnlyList<ReportHitInput> Hits, IReadOnlyList<EvidenceObject> Windows);

/// <summary>Resolve exact critical resources and state-change boundaries before presentation and diagnostics.</summary>
public sealed class ReportCriticalEvidence(IReadOnlyDictionary<string, EvidenceObject> roots, IReadOnlyDictionary<string, string> numbers)
{
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => (value as EvidenceArray)?.Items ?? [];
    private static Dictionary<string, EvidenceValue> Fields(EvidenceObject row) => (Dictionary<string, EvidenceValue>)row.Fields;

    public static ReportCriticalEvidence Load(ResourceFiles files) => new(new BuffRootCatalog(files).Roots, new SkillResourceCatalog(files).Buffs);

    public ReportCriticalResult Attach(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> records, IReadOnlyList<EvidenceObject> sourceWindows)
        => AttachCore(source, records, sourceWindows, ownsInput: false);

    // Only report-local hits/windows may be transferred here. Public callers retain copy isolation.
    internal ReportCriticalResult AttachOwned(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> records, IReadOnlyList<EvidenceObject> sourceWindows)
        => AttachCore(source, records, sourceWindows, ownsInput: true);

    private ReportCriticalResult AttachCore(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> records,
        IReadOnlyList<EvidenceObject> sourceWindows, bool ownsInput)
    {
        var hits = ownsInput ? source.ToArray() : source.Select(hit => hit with { Evidence = (EvidenceObject)BuffEvidence.Clone(hit.Evidence) }).ToArray();
        var windows = ownsInput ? sourceWindows.ToArray() : sourceWindows.Select(window => (EvidenceObject)BuffEvidence.Clone(window)).ToArray();
        var ids = records.Select(row => Text(row.Get("event_key"))).ToHashSet(StringComparer.Ordinal);
        foreach (var hit in hits)
        {
            ids.UnionWith(Items(hit.Evidence.Get("_active_attacker_buff_ids")).Select(Text));
            ids.UnionWith(Items(hit.Evidence.Get("_active_target_buff_ids")).Select(Text));
        }
        var profiles = ids.ToDictionary(key => key, key => CriticalEvidence.Profile(roots.GetValueOrDefault(numbers.GetValueOrDefault(key, key))
            ?? (EvidenceValue)EvidenceNull.Value), StringComparer.Ordinal);
        Dictionary<(string Uid, string Actor, string Resource), HashSet<BigInteger>> changes = [];
        foreach (var record in records)
        {
            var resource = Text(record.Get("event_key"));
            if (!profiles.TryGetValue(resource, out var profile) || profile.Attributes.Count == 0) continue;
            var identity = (Text(record.Get("uid")), Text(record.Get("target_actor_id")), resource);
            foreach (var key in new[] { "dynamic_bb_events", "enable_observations", "repeated_creation_observations" })
                foreach (var value in Items(record.Get(key)))
                {
                    if (value is not EvidenceObject observation || observation.Get("line_no") is not EvidenceInteger line
                        || observation.Get("status") is EvidenceText { Value: "duplicate" }) continue;
                    if (!changes.TryGetValue(identity, out var lines)) changes[identity] = lines = [];
                    lines.Add(line.Value);
                }
        }
        foreach (var window in windows)
        {
            var identities = Items(window.Get("uid_aliases")).Select(Text).Append(Text(window.Get("uid"))).Distinct(StringComparer.Ordinal);
            HashSet<BigInteger> lines = [];
            foreach (var uid in identities)
                if (changes.TryGetValue((uid, Text(window.Get("target_actor_id")), Text(window.Get("event_key"))), out var found)) lines.UnionWith(found);
            if (lines.Count > 0) Fields(window)["critical_state_change_lines"] = new EvidenceArray(lines.Order().Select(line => (EvidenceValue)new EvidenceInteger(line)).ToArray());
        }
        var criticalWindows = windows.Where(window => profiles.TryGetValue(Text(window.Get("event_key")), out var profile)
            && profile.Attributes.Count > 0 && !profile.Processors).ToArray();
        foreach (var hit in hits) Fields(hit.Evidence)["critical_context"] = CriticalEvidence.Build(hit.Evidence,
            hit.Evidence.Get("critical_observation") as EvidenceObject, profiles, criticalWindows);
        return new(hits, windows);
    }
}
