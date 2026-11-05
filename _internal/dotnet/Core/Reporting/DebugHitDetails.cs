using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record DebugHitResult(IReadOnlyList<EvidenceObject> Hits, IReadOnlyList<EvidenceObject> Windows);

/// <summary>Debug rows use the canonical allocator and preserve the report's numerical hit input.</summary>
public sealed class DebugHitDetails
{
    private readonly Lazy<HitAllocator> allocator;
    public DebugHitDetails(HitAllocator allocator) : this(() => allocator) { }
    private DebugHitDetails(Func<HitAllocator> load) => allocator = new(load);

    // Summary updates never request detail rows. Keep their independent allocator demand-loaded.
    public static DebugHitDetails Load(ResourceFiles files) => new(() => HitAllocator.Load(files));
    public DebugHitResult Build(IReadOnlyList<ReportHitInput> source, IReadOnlyList<EvidenceObject> windows, IReadOnlyList<EvidenceObject> records)
    {
        var byUid = records.GroupBy(record => CatalogValues.Text(CatalogValues.Or(record.Get("uid"), new EvidenceText(""))), StringComparer.Ordinal)
            .Where(group => group.Key.Length > 0)
            .ToDictionary(group => group.Key, group => (IReadOnlyList<EvidenceObject>)group.ToArray(), StringComparer.Ordinal);
        IReadOnlyList<EvidenceObject> current = windows.Select(window => (EvidenceObject)BuffEvidence.Clone(window)).ToArray();
        List<EvidenceObject> rows = [];
        foreach (var input in source)
        {
            var allocation = allocator.Value.Allocate(new(input, current, records, BuffRecordsByUid: byUid, IncludeDebug: true));
            current = allocation.Windows;
            var hit = (Dictionary<string, EvidenceValue>)allocation.Hit.Fields;
            hit["rdps_contributions"] = CatalogValues.Or(allocation.Allocation.Get("contributions_list"), new EvidenceArray([]));
            foreach (var key in new[] { "zones", "ignored_effects", "product_external_multiplier", "attacker_share", "external_pool", "external_sources",
                "zone_summary", "buff_source_summary", "packet_modifier_uids", "packet_modifier_details" })
                hit[key] = allocation.Allocation.Get(key);
            rows.Add(allocation.Hit);
        }
        return new(rows, current);
    }
}
