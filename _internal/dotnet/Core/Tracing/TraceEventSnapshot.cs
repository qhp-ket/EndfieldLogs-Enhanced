using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Tracing;

/// <summary>Detach mutable producer evidence once; share internally owned immutable events between consumers.</summary>
public static class TraceEventSnapshot
{
    public static TraceEvent Capture(TraceEvent item)
    {
        var data = (EvidenceObject)FrozenEvidence.Capture(item.Data);
        var source = (EvidenceObject)FrozenEvidence.Capture(item.Source);
        return ReferenceEquals(data, item.Data) && ReferenceEquals(source, item.Source)
            ? item : item with { Data = data, Source = source };
    }
}
