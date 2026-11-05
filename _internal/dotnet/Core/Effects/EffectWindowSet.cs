using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Order observations and remove only exact repeated instance windows.</summary>
public static class EffectWindowSet
{
    private static readonly string[] IdentityFields = ["uid", "uid_aliases", "source_character_key", "target_character_key", "event_key", "target_actor_id", "source_actor_id",
        "start_ts_ms", "end_ts_ms", "zone_effects", "dynamic_effects", "effect_segments", "start_line_no", "end_line_no", "snapshot_end_ts_ms", "snapshot_end_line_no",
        "enable_observations", "snapshot_update"];
    private static BigInteger Int(EvidenceValue value) => value switch
    {
        EvidenceInteger number => number.Value, EvidenceBoolean flag => flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal number when double.IsFinite(number.Value) => new BigInteger(number.Value),
        EvidenceText text => TraceFields.OptionalInteger(text.Value) ?? throw new FormatException("Invalid window coordinate"),
        _ when !CatalogValues.Truth(value) => BigInteger.Zero, _ => throw new InvalidCastException("Invalid window coordinate"),
    };

    public static IReadOnlyList<EvidenceObject> Ordered(IEnumerable<EvidenceObject> windows) => windows.OrderBy(window => Int(window.Get("start_ts_ms")))
        .ThenBy(window => Int(window.Get("line_no"))).ToArray();

    public static IReadOnlyList<EvidenceObject> Deduplicate(IEnumerable<EvidenceObject> windows)
    {
        Dictionary<(string Uid, BigInteger Start, BigInteger? Line), (EvidenceObject First, HashSet<string>? Signatures)> groups = [];
        HashSet<string>? otherSignatures = null;
        List<EvidenceObject> result = [];
        static string Signature(EvidenceObject window) => EvidenceJsonSignature.Sorted(
            new EvidenceObject(IdentityFields.ToDictionary(key => key, window.Get, StringComparer.Ordinal)));
        foreach (var window in windows)
        {
            if (EffectStackPolicy.Text(window.Get("uid")).Length == 0) { result.Add(window); continue; }
            var line = window.Get("start_line_no");
            if (window.Get("uid") is not EvidenceText uid || window.Get("start_ts_ms") is not EvidenceInteger start
                || line is not (EvidenceInteger or EvidenceNull))
            {
                otherSignatures ??= new(StringComparer.Ordinal);
                if (otherSignatures.Add(Signature(window))) result.Add(window);
                continue;
            }
            // Equal full signatures must have this same typed coordinate key. Most windows
            // are unique here, so only collisions need the complete nested evidence signature.
            var key = (uid.Value, start.Value, (line as EvidenceInteger)?.Value);
            if (!groups.TryGetValue(key, out var group))
            {
                groups.Add(key, (window, null));
                result.Add(window);
                continue;
            }
            if (group.Signatures is null)
            {
                group.Signatures = new(StringComparer.Ordinal) { Signature(group.First) };
                groups[key] = group;
            }
            if (group.Signatures.Add(Signature(window))) result.Add(window);
        }
        return result;
    }

    public static IReadOnlyList<EvidenceObject> ApplyLimits(IEnumerable<EvidenceObject> windows, EffectStackPolicy policy)
    {
        List<EvidenceObject> result = [];
        foreach (var window in windows)
            if (ApplyLimit(window, policy) is { } limited) result.Add(limited);
        return OrderLimited(result);
    }

    internal static EvidenceObject? ApplyLimit(EvidenceObject window, EffectStackPolicy policy)
    {
        Dictionary<string, EvidenceValue> updated = new(window.Fields, StringComparer.Ordinal);
        var key = EffectStackPolicy.Text(window.Get("event_key"));
        BigInteger? limit;
        if (policy.Settings(key) is { } settings)
        {
            updated["stacking_type"] = settings.Get("stackingType");
            limit = policy.Limit(key, window.Get("bb_values") as EvidenceObject);
            if (settings.Get("stackingType") is EvidenceText { Value: "Unlimited" }) limit = null;
            else if (limit is null) updated["rdps_unresolved_stack_evidence"] = new EvidenceBoolean(true);
        }
        else limit = EffectStackPolicy.Positive(window.Get("stack_limit"));
        updated["stack_limit"] = limit is null ? EvidenceNull.Value : new EvidenceInteger(limit.Value);
        var start = Int(window.Get("start_ts_ms"));
        var end = Int(window.Get("end_ts_ms"));
        if (end < start) return null;
        updated["duration_ms"] = new EvidenceInteger(BigInteger.Max(end - start, BigInteger.One));
        return new(updated);
    }

    internal static IReadOnlyList<EvidenceObject> OrderLimited(IEnumerable<EvidenceObject> windows)
        => windows.OrderBy(window => Int(window.Get("start_ts_ms")))
            .ThenBy(window => EffectStackPolicy.Text(window.Get("event_key")), PythonDisplay.CodePointComparer).ToArray();
}
