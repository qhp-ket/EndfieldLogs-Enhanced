using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Evidence quality projection; no damage allocation or availability inference.</summary>
public static class SnapshotQuality
{
    public const int SchemaVersion = 1;
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static readonly string[] TimingFields = ["duration_ms", "time_source", "timeline_zero_source", "timer_start_seen", "timer_end_seen",
        "official_timer_start_seen", "official_timer_end_seen", "official_timer_observed_elapsed_ms", "packet_timer_elapsed_ms",
        "timer_integrity_ok", "timer_integrity_reasons", "timer_evidence", "timer_start_inferred", "timer_window_valid", "official_pass_confirmed", "completion_source"];
    private static bool Positive(EvidenceValue value) => value switch
    {
        EvidenceInteger number => number.Value > 0, EvidenceReal number => double.IsFinite(number.Value) && number.Value > 0, _ => false,
    };
    private static EvidenceArray Texts(IEnumerable<string> values) => new(values.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
    public static EvidenceValue JsonEvidence(EvidenceValue value) => value switch
    {
        EvidenceInteger number when BigInteger.Abs(number.Value) > 9007199254740991 => new EvidenceText(number.Value.ToString(System.Globalization.CultureInfo.InvariantCulture)),
        EvidenceReal number when !double.IsFinite(number.Value) => EvidenceNull.Value,
        EvidenceObject row => new EvidenceObject(row.Fields.ToDictionary(pair => pair.Key, pair => JsonEvidence(pair.Value), StringComparer.Ordinal)),
        EvidenceArray array => new EvidenceArray(array.Items.Select(JsonEvidence).ToArray()), _ => value,
    };

    // Consume a report-local graph once. Shared immutable descendants still cross the
    // ordinary copy boundary; repeated mutable containers remain independent in output.
    internal static EvidenceValue JsonEvidenceOwned(EvidenceValue value)
    {
        HashSet<object> transferred = new(ReferenceEqualityComparer.Instance);
        EvidenceValue Convert(EvidenceValue item)
        {
            if (item is EvidenceObject { Fields: Dictionary<string, EvidenceValue> fields } row && transferred.Add(fields))
            {
                // Values change, never dictionary membership or insertion order.
                foreach (var pair in fields) fields[pair.Key] = Convert(pair.Value);
                return row.SourcePairs is null ? row : row with { SourcePairs = null };
            }
            if (item is EvidenceArray { Items: EvidenceValue[] items } array && transferred.Add(items))
            {
                for (var index = 0; index < items.Length; index++) items[index] = Convert(items[index]);
                return array;
            }
            return JsonEvidence(item);
        }
        return Convert(value);
    }

    public static EvidenceObject Build(EvidenceObject report, bool includeEvidence = true)
    {
        var battle = report.Get("battle") as EvidenceObject ?? Empty;
        var preflight = report.Get("rdps_preflight");
        var basis = report.Get("rdps_damage_basis") is EvidenceNull ? battle.Get("rdps_damage_basis") : report.Get("rdps_damage_basis");
        var checks = preflight as EvidenceObject ?? Empty;
        var damage = basis as EvidenceObject ?? Empty;
        List<string> rdpsReasons = [];
        if (preflight is not EvidenceObject) rdpsReasons.Add("missing_rdps_preflight");
        if (basis is not EvidenceObject) rdpsReasons.Add("missing_rdps_damage_basis");
        foreach (var (name, value) in new (string, EvidenceValue)[] { ("rdps_preflight_ok", checks.Get("ok")),
            ("rdps_damage_basis_preflight_ok", damage.Get("rdps_preflight_ok")), ("rdps_strict_ok", damage.Get("rdps_strict_ok")),
            ("rdps_conservation_ok", damage.Get("rdps_conservation_ok")) })
            if (value is not EvidenceBoolean { Value: true }) rdpsReasons.Add(name + (value is EvidenceBoolean { Value: false } ? "_failed" : "_unknown"));
        if (checks.Get("blocker_count") is not EvidenceInteger { Value.IsZero: true } || checks.Get("blockers") is not EvidenceArray { Items.Count: 0 })
            rdpsReasons.Add("rdps_blockers_present_or_unknown");
        if (CatalogValues.Truth(damage.Get("unresolved_damage_actor_count"))) rdpsReasons.Add("unresolved_damage_actors");
        if (CatalogValues.Truth(damage.Get("missing_packet_hit_count"))) rdpsReasons.Add("missing_packet_hits");
        if (CatalogValues.Truth(damage.Get("hit_conservation_mismatch_count"))) rdpsReasons.Add("hit_conservation_mismatches");
        var hitCount = damage.Get("hit_count");
        if (hitCount is not EvidenceInteger count || count.Value <= 0)
            rdpsReasons.Add(EvidenceJson.PythonEquals(hitCount, new EvidenceInteger(0)) ? "missing_damage_events" : "damage_hit_count_unknown");
        var rdpsStatus = rdpsReasons.Count > 0 ? "provisional" : "verified";
        if (basis is not EvidenceObject || hitCount is EvidenceInteger nonpositive && nonpositive.Value <= 0) rdpsStatus = "unavailable";

        List<string> timingReasons = [];
        var duration = battle.Get("duration_ms");
        if (!Positive(duration)) timingReasons.Add("duration_missing_or_nonpositive");
        var integrity = battle.Get("timer_integrity_ok");
        if (integrity is not EvidenceBoolean { Value: true }) timingReasons.Add(integrity is EvidenceBoolean { Value: false } ? "timer_integrity_failed" : "timer_integrity_unknown");
        if (battle.Get("timer_integrity_reasons") is not EvidenceArray { Items.Count: 0 }) timingReasons.Add("timer_integrity_reasons_present_or_unknown");
        var validity = battle.Get("timer_window_valid");
        if (validity is not EvidenceBoolean { Value: true }) timingReasons.Add(validity is EvidenceBoolean { Value: false } ? "timer_window_invalid" : "timer_window_validity_unknown");
        if (!CatalogValues.Truth(battle.Get("time_source"))) timingReasons.Add("time_source_unknown");
        if (battle.Get("timer_start_inferred") is EvidenceBoolean { Value: true }) timingReasons.Add("timer_start_inferred");
        else if (battle.Get("timer_start_inferred") is not EvidenceBoolean { Value: false }) timingReasons.Add("timer_start_inference_unknown");
        var timingStatus = timingReasons.Count > 0 ? "provisional" : "verified";
        if (!Positive(duration) || validity is EvidenceBoolean { Value: false }) timingStatus = "unavailable";
        var status = rdpsStatus == "unavailable" || timingStatus == "unavailable" ? "unavailable"
            : rdpsStatus == "provisional" || timingStatus == "provisional" ? "provisional" : "verified";
        Dictionary<string, EvidenceValue> rdps = new() { ["status"] = new EvidenceText(rdpsStatus), ["reasons"] = Texts(rdpsReasons) };
        Dictionary<string, EvidenceValue> timing = new() { ["status"] = new EvidenceText(timingStatus), ["reasons"] = Texts(timingReasons) };
        if (includeEvidence)
        {
            rdps["evidence"] = JsonEvidence(BuffEvidence.Object(("rdps_preflight", preflight), ("rdps_damage_basis", basis),
                ("unresolved_hits", report.Get("unresolved_hits")), ("unresolved_buff_actions", report.Get("unresolved_buff_actions"))));
            timing["evidence"] = JsonEvidence(new EvidenceObject(TimingFields.ToDictionary(key => key, battle.Get, StringComparer.Ordinal)));
        }
        return BuffEvidence.Object(("schema_version", new EvidenceInteger(SchemaVersion)), ("status", new EvidenceText(status)),
            ("rdps", new EvidenceObject(rdps)), ("timing", new EvidenceObject(timing)));
    }

    public static EvidenceObject Attach(EvidenceObject report)
    {
        var fields = new Dictionary<string, EvidenceValue>(report.Fields, StringComparer.Ordinal) { ["snapshot_quality"] = Build(report) };
        return new(fields);
    }
}
