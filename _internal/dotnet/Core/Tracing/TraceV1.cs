using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

/// <summary>Compatibility boundary for the original JSONL format.</summary>
public static class TraceV1
{
    public static EvidenceObject NativeData(EvidenceObject data) => TraceModel.Compact(
        TraceLoadout.Native(new(ExportData(data).Fields.Where(pair => pair.Key != "legacy_layout").ToDictionary())),
        new EvidenceObject(new Dictionary<string, EvidenceValue>()), null);
    public static EvidenceObject ExportData(EvidenceObject data) => (EvidenceObject)TraceValueProjection.Restore(data, (EvidenceObject)data.Get("legacy_layout"));
}
