using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using static EndfieldLogs.Runtime.Tracing.TraceData;

namespace EndfieldLogs.Runtime.Tracing;

public sealed partial class TraceBridge
{
    private void EmitStructured(long ts, string type, EvidenceObject data, EvidenceObject origin)
    {
        FlushStarts();
        AppendStructured(ts, type, data, origin);
    }
    private void AppendStructured(long ts, string type, EvidenceObject data, EvidenceObject origin)
    {
        Dictionary<string, EvidenceValue> source = [];
        if (origin.Get("session_id") is EvidenceText { Value.Length: > 0 } session) source["session_id"] = session;
        if (origin.Get("seq_id") is EvidenceInteger seq) source["operation_seq"] = seq;
        if (origin.Get("generation") is EvidenceInteger generation && generation.Value >= 0 && generation.Value < BigInteger.One << 32) source["generation"] = generation;
        if (DecimalRange(origin.Get("operation_owner_id"), 0, BigInteger.One << 64)) source["owner_id"] = new EvidenceText(S(origin.Get("operation_owner_id")));
        var projection = TraceValueProjection.Capture(data);
        var fields = ((EvidenceObject)projection.Value).Fields.ToDictionary(); fields["legacy_layout"] = projection.Layout;
        eventOutput!(new(++structuredEventSequence, ts, type, new(fields), new(source),
            origin.Get("client_tick_tms") is EvidenceInteger tick && tick.Value >= long.MinValue && tick.Value <= long.MaxValue ? (long)tick.Value : null));
    }
}
