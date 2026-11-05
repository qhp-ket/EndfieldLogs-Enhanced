using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

public sealed record EffectHitPosition(long TimestampMs, int? LineNumber = null, BigInteger? PacketSequence = null, string? PacketSession = null);
public sealed record EffectWindowResult(IReadOnlyList<EvidenceValue> Effects, EvidenceObject Window);

/// <summary>Resolve a window at exact hit coordinates, preserving every unresolved-evidence flag.</summary>
public static class EffectWindowEvaluation
{
    private static EvidenceText Text(string value) => new(value);
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static BigInteger Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value) => new BigInteger(real.Value),
        EvidenceText text => TraceFields.OptionalInteger(text.Value) ?? throw new FormatException("Invalid integer coordinate"),
        _ => throw new InvalidCastException("Missing integer coordinate"),
    };
    private static IReadOnlyList<EvidenceValue> Items(EvidenceValue value) => Truth(value)
        ? value is EvidenceArray array ? array.Items : throw new InvalidCastException("Window rows must be an array") : [];
    private static EvidenceObject Obj(EvidenceValue value) => value as EvidenceObject ?? throw new InvalidCastException("Window row must be an object");
    private static double FloatOrZero(EvidenceValue value)
    {
        if (!Truth(value)) return 0;
        if (value is EvidenceReal real) return real.Value;
        if (value is EvidenceBoolean flag) return flag.Value ? 1 : 0;
        if (value is EvidenceInteger integer)
        {
            var converted = (double)integer.Value;
            return double.IsFinite(converted) ? converted : throw new OverflowException("Dynamic rate integer overflow");
        }
        return value is EvidenceText text && TraceFields.TryFloat(text.Value, out var number) ? number : throw new FormatException("Invalid dynamic rate");
    }

    public static EffectWindowResult At(EvidenceObject window, EffectHitPosition hit)
    {
        Dictionary<string, EvidenceValue> updated = new(window.Fields, StringComparer.Ordinal)
        {
            ["_enable_state_unobserved_at_hit"] = new EvidenceBoolean(false),
            ["_effect_state_unresolved_at_hit"] = new EvidenceBoolean(false),
            ["_buff_enabled_at_hit"] = EvidenceNull.Value,
        };
        void Flag(string key) => updated[key] = new EvidenceBoolean(true);
        EffectWindowResult Finish(IReadOnlyList<EvidenceValue>? effects = null) => new(effects ?? [], new(updated));
        EffectWindowResult Unresolved() { Flag("_effect_state_unresolved_at_hit"); return Finish(); }
        var time = new EvidenceInteger(hit.TimestampMs);
        var start = window.Get("start_ts_ms");
        var end = window.Get("end_ts_ms");
        var lineKnown = hit.LineNumber is not (null or 0);
        if (start is EvidenceInteger startTime && hit.TimestampMs < startTime.Value
            || end is EvidenceInteger endTime && hit.TimestampMs > endTime.Value) return Finish();
        if (lineKnown)
        {
            if (EvidenceJson.PythonEquals(start, time) && Integer(CatalogValues.Or(window.Get("start_line_no"), new EvidenceInteger(0))) > hit.LineNumber
                || EvidenceJson.PythonEquals(end, time) && Truth(window.Get("end_line_no")) && hit.LineNumber >= Integer(window.Get("end_line_no"))) return Finish();
        }
        else if (Truth(window.Get("snapshot_update")) && EvidenceJson.PythonEquals(start, time)
            || EvidenceJson.PythonEquals(window.Get("snapshot_end_ts_ms"), time))
        {
            Flag("rdps_snapshot_order_unresolved");
            return Unresolved();
        }
        var observations = Items(window.Get("enable_observations")).Select(Obj).ToArray();
        if (Truth(window.Get("rdps_conflicting_enable_state")) && observations.Length == 0) return Unresolved();
        var priorEnable = observations.Where(row => hit.PacketSequence is BigInteger seq
            ? Integer(row.Get("operationSeq")) <= seq
            : Integer(row.Get("ts_ms")) < hit.TimestampMs || Integer(row.Get("ts_ms")) == hit.TimestampMs
                && (!lineKnown || Integer(row.Get("line_no")) <= hit.LineNumber))
            .OrderBy(row => Integer(row.Get(hit.PacketSequence is null ? "ts_ms" : "operationSeq")))
            .ThenBy(row => Integer(row.Get("line_no"))).ToArray();
        if (priorEnable.Length > 0)
        {
            var latest = priorEnable[^1];
            var matching = observations.Where(row => EvidenceJson.PythonEquals(row.Get("operationSeq"), latest.Get("operationSeq"))).ToArray();
            if (matching.Any(row => !EvidenceJson.PythonEquals(row.Get("enabled"), matching[0].Get("enabled")))) return Unresolved();
            if (latest.Get("enabled") is EvidenceBoolean { Value: false })
            {
                updated["_buff_enabled_at_hit"] = new EvidenceBoolean(false);
                return Finish();
            }
        }
        if (Truth(window.Get("requires_enable_observation")) && priorEnable.Length == 0)
        {
            Flag("_enable_state_unobserved_at_hit");
            Flag("rdps_unresolved_enable_evidence");
            return Unresolved();
        }
        updated["_buff_enabled_at_hit"] = new EvidenceBoolean(true);
        var specifications = Items(window.Get("dynamic_effects"));
        if (specifications.Count == 0) return Finish(Items(window.Get("zone_effects")).ToArray());
        List<EvidenceValue> effects = [];
        bool BeforeLine(EvidenceObject row) => Integer(row.Get("ts_ms")) < hit.TimestampMs
            || Integer(row.Get("ts_ms")) == hit.TimestampMs && lineKnown && Integer(row.Get("line_no")) <= hit.LineNumber;
        foreach (var item in specifications)
        {
            var spec = Obj(item);
            double? rate;
            if (spec.Fields.ContainsKey("keyword_rate_snapshots"))
            {
                if (hit.PacketSession is not null && !EvidenceJson.PythonEquals(Text(hit.PacketSession), spec.Get("keyword_session_id"))
                    || hit.PacketSequence is not null && hit.PacketSession is null) return Unresolved();
                var prior = Items(spec.Get("keyword_rate_snapshots")).Select(Obj).Where(row =>
                    EvidenceJson.PythonEquals(row.Get("session_id"), spec.Get("keyword_session_id"))
                    && (hit.PacketSequence is BigInteger seq ? Integer(row.Get("operation_seq")) <= seq : BeforeLine(row)))
                    .OrderBy(row => Integer(row.Get("operation_seq"))).ThenBy(row => Integer(row.Get("line_no"))).ToArray();
                rate = BuffEvidence.OptionalFloat(spec.Get("base_rate"));
                if (prior.Length > 0)
                    rate = prior[^1].Get("status") is EvidenceText { Value: "observed" } ? BuffEvidence.OptionalFloat(prior[^1].Get("rate_after")) : null;
                if (rate is null or < 0) return Unresolved();
                if (rate > 0)
                {
                    var fields = Select(spec, "zone", "element", "condition", "external_rdps_allowed", "rdps_whitelist_keys", "keyword_origin");
                    fields["rate"] = new EvidenceReal(rate.Value);
                    effects.Add(new EvidenceObject(fields));
                }
                continue;
            }
            if (spec.Fields.ContainsKey("parameter_snapshots"))
            {
                var prior = Items(spec.Get("parameter_snapshots")).Select(Obj).Where(row => hit.PacketSequence is BigInteger seq
                    ? row.Get("operation_seq") is EvidenceInteger operation && operation.Value <= seq : BeforeLine(row))
                    .OrderBy(row => Integer(row.Get("operation_seq"))).ThenBy(row => Integer(row.Get("line_no"))).ToArray();
                if (prior.Length == 0) return Unresolved();
                var snapshot = prior[^1];
                var identity = snapshot.Get("identity") as EvidenceObject;
                var session = CatalogValues.Or(snapshot.Get("session_id"), identity?.Get("sessionId"));
                if (hit.PacketSession is not null && session is not EvidenceNull && !EvidenceJson.PythonEquals(Text(hit.PacketSession), session)) return Unresolved();
                var blackboard = snapshot.Get("bb_values") as EvidenceObject;
                var values = Items(spec.Get("parameter_keys")).Select(key => BuffEvidence.OptionalFloat(blackboard?.Get(CatalogValues.Text(key)) ?? EvidenceNull.Value)).ToArray();
                if (snapshot.Get("status") is not EvidenceText { Value: "attribute_parameters_observed" } || values.Length == 0 || values.Any(value => value is null or > 0)) return Unresolved();
                rate = -PythonFloatSum.Sum(values.Select(value => value!.Value));
                if (!double.IsFinite(rate.Value)) return Unresolved();
                if (rate > 0) effects.Add(BuffEvidence.Object(("zone", Text("res")), ("element", spec.Get("element")), ("rate", new EvidenceReal(rate.Value)),
                    ("external_rdps_allowed", spec.Get("external_rdps_allowed")), ("rdps_whitelist_keys", new EvidenceArray(Items(spec.Get("rdps_whitelist_keys")).ToArray())),
                    ("resistance_point_source", Text("packet_bb_update_and_refresh")), ("resistance_snapshot_seq", snapshot.Get("operation_seq"))));
                continue;
            }
            if (Truth(spec.Get("observed_points")) && spec.Get("observed_points_source") is not EvidenceText { Value: "typed_runtime_dynamic_action" }
                || FloatOrZero(spec.Get("tick_rate")) != 0 || FloatOrZero(spec.Get("delayed_add_rate")) != 0)
            {
                Flag("rdps_invalid_dynamic_evaluation");
                return Finish();
            }
            rate = FloatOrZero(spec.Get("base_rate"));
            if (Truth(spec.Get("observed_points")))
            {
                var points = Items(spec.Get("observed_points")).OfType<EvidenceArray>().Where(point => point.Items.Count == 2 && Integer(point.Items[0]) <= hit.TimestampMs).ToArray();
                if (points.Length == 0) continue;
                var observed = FloatOrZero(points[^1].Items[1]);
                rate = observed > 0 ? observed : 0.0;
            }
            if (!double.IsFinite(rate.Value))
            {
                Flag("rdps_invalid_dynamic_evaluation");
                return Finish();
            }
            if (rate <= 0) continue;
            var effect = Select(spec, "condition", "external_rdps_allowed", "rdps_whitelist_keys");
            effect["zone"] = Text(CatalogValues.Text(spec.Get("zone")));
            effect["element"] = CatalogValues.Or(spec.Get("element"), Text("all"));
            effect["rate"] = new EvidenceReal(rate.Value);
            effects.Add(new EvidenceObject(effect));
        }
        return Finish(effects);
    }

    private static Dictionary<string, EvidenceValue> Select(EvidenceObject source, params string[] keys) => keys.Where(source.Fields.ContainsKey)
        .ToDictionary(key => key, key => BuffEvidence.Clone(source.Get(key)), StringComparer.Ordinal);

}
