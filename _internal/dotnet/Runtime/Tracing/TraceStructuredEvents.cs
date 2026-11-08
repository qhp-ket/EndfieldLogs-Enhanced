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
        if (DecimalRange(origin.Get("operation_owner_id"), 0, BigInteger.One << 64)) source["owner_id"] = TraceModel.Normalize(origin.Get("operation_owner_id"), identity: true);
        var tickValue = origin.Get("client_tick_tms") is EvidenceInteger rawTick && rawTick.Value >= long.MinValue && rawTick.Value <= long.MaxValue ? (long?)rawTick.Value : null;
        if (type is "loadout_slot" or "loadout_stats") data = TraceLoadout.Native(data);
        var fields = TraceModel.Compact(data, new(source), tickValue, type);
        eventOutput!(new(++structuredEventSequence, ts, type, fields, new(source),
            origin.Get("client_tick_tms") is EvidenceInteger tick && tick.Value >= long.MinValue && tick.Value <= long.MaxValue ? (long)tick.Value : null));
    }
}
