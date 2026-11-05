using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Reviewed runtime semantics have a separate provenance from full typed-root projections.</summary>
internal static class NativeDamageSemanticsBinding
{
    public static EvidenceObject Evidence { get; } = new(new Dictionary<string, EvidenceValue>(StringComparer.Ordinal)
    {
        ["gameAssemblySha256"] = new EvidenceText("c24495e51b406f03b03890c4788ee618ae022c991405be5d5b8b787cb775ae89"),
        ["metadataSha256"] = new EvidenceText("0076743397acadf03d3b0064343a963c7c88863b8160526d397e4b3efb96f02e"),
    });
}
