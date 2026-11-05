using System.Globalization;
using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Project the computed allocation and recorded packet details; this layer does not infer new effects.</summary>
public sealed class AllocationExplanation(AllocationDebug debug, Func<EvidenceObject, BuffLabelsResult> labels)
{
    internal IReadOnlyList<EvidenceObject> RecordedContributionRows(EvidenceObject values) => debug.RecordedContributionRows(values);
    private static EvidenceArray Array(IEnumerable<EvidenceValue> rows) => new(rows.ToArray());
    private static EvidenceText Text(string value) => new(value);
    private static string String(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, Text("")));
    private static EvidenceValue Round(double value) => AllocationDebug.Round4(new EvidenceReal(value));
    private static double Number(EvidenceValue value) => EffectIdentity.Float(CatalogValues.Or(value, new EvidenceReal(0)));
    private static EvidenceObject Obj(params (string Key, EvidenceValue Value)[] values) => BuffEvidence.Object(values);
    private static Dictionary<string, EvidenceValue> Fields(EvidenceObject value) => (Dictionary<string, EvidenceValue>)value.Fields;

    public EvidenceObject Project(HitAllocation state, ContributionShares shares)
    {
        var result = Obj(("allocation_policy", Text("log_marginal_v1")), ("allocation_policy_basis", Text("accounting_convention")),
            ("contributions_map", new EvidenceObject(shares.Contributions.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value)))),
            ("contributions_list", Array(debug.ContributionRows(shares.Contributions, true))));
        if (!state.IncludeDebug) return result;
        var logTotal = shares.ProductExternal > 1 ? PythonFloatSum.Sum(state.Multipliers.Values.Select(value => Math.Log(value))) : 0;
        Dictionary<string, double> zoneShares = new(StringComparer.Ordinal);
        if (logTotal > 0 && shares.ExternalPool > 0)
            foreach (var zone in state.ExternalByZone.Keys)
                if (state.Multipliers.TryGetValue(zone, out var multiplier)) zoneShares[zone] = shares.ExternalPool * (Math.Log(multiplier) / logTotal);
        List<EvidenceObject> zones = [];
        foreach (var zone in state.SelfByZone.Keys.Concat(state.SelfFactorByZone.Keys).Concat(state.ExternalByZone.Keys).Distinct(StringComparer.Ordinal))
        {
            var product = zone.StartsWith("prod_", StringComparison.Ordinal);
            var self = product ? state.SelfFactorByZone.GetValueOrDefault(zone, 1) - 1 : state.SelfByZone.GetValueOrDefault(zone);
            // Python evaluates the fallback sum even when this key has a stored sum.
            var fallback = PythonFloatSum.Sum((state.ExternalByZone.GetValueOrDefault(zone) ?? []).Select(row => row.Rate));
            var external = state.ExternalSums.GetValueOrDefault(zone, fallback);
            var total = self + external;
            var multiplier = product ? state.SelfFactorByZone.GetValueOrDefault(zone, 1) * state.Multipliers.GetValueOrDefault(zone, 1)
                : zone == "res" && state.ResistanceNumerator is double resistance ? resistance / 100
                : zone == "arts_strength" ? Math.Pow(1 + Math.Max(total, 0) / 100, state.ArtsStrength.FactorCount == 0 ? 1 : state.ArtsStrength.FactorCount)
                : 1 + total;
            if (product) total = multiplier - 1;
            var bucket = PacketAllocationEvidence.Bucket(zone, state.Hit.Get("dpd_raw") as EvidenceObject);
            var bucketPosition = zone switch { "dmg_inc" => ("atk", 1), "amp" => ("atk", 3), "combo" => ("atk", 4), "vuln_taken" => ("def", 1), "fragile" => ("def", 5), _ => ("", 0) };
            var contributors = (state.ContributorsByZone.GetValueOrDefault(zone) ?? []).OrderBy(row => row.Get("scope") is EvidenceText { Value: "external" } ? 0 : 1)
                .ThenBy(row => -Number(row.Get("rate"))).ThenBy(row => String(row.Get("source_character_name")), PythonDisplay.CodePointComparer)
                .ThenBy(row => String(row.Get("event_key")), PythonDisplay.CodePointComparer);
            var row = Obj(("zone", Text(zone)), ("zone_label", Text(StaticLoadoutEvidence.ZoneLabels.GetValueOrDefault(zone, zone))),
                ("self_rate", Round(self)), ("external_rate", Round(external)), ("total_rate", Round(total)), ("total_multiplier", Round(multiplier)),
                ("external_multiplier", Round(state.Multipliers.GetValueOrDefault(zone, 1))), ("zone_external_share", Round(zoneShares.GetValueOrDefault(zone))),
                ("dpd_bucket", bucketPosition.Item1.Length > 0 && bucket is double value
                    ? Obj(("side", Text(bucketPosition.Item1)), ("index", new EvidenceInteger(bucketPosition.Item2)), ("value", Round(value))) : EvidenceNull.Value),
                ("contributors", Array(contributors)));
            if (zone == "res" && state.EffectiveResistance is double effective)
            {
                Fields(row)["rate_unit"] = Text("resistance_points");
                Fields(row)["effective_resistance"] = new EvidenceReal(effective);
                Fields(row)["effective_resistance_source"] = Text(state.ResistanceSource);
                Fields(row)["without_external_resistance"] = new EvidenceReal(effective + external);
            }
            zones.Add(row);
        }
        var orderedZones = debug.SortZones(zones);
        Dictionary<string, EvidenceObject> sources = new(StringComparer.Ordinal);
        foreach (var rows in state.ExternalByZone.Values)
            foreach (var contribution in rows)
            {
                if (!sources.TryGetValue(contribution.Provider, out var row))
                    sources[contribution.Provider] = row = Obj(("character_key", Text(contribution.Provider)),
                        ("character_name", CatalogValues.Or(contribution.Evidence?.Get("source_character_name") ?? EvidenceNull.Value,
                            debug.Name(Text(contribution.Provider)), Text(contribution.Provider))),
                        ("effect_count", new EvidenceInteger(0)), ("rdps_credit", new EvidenceReal(0)));
                Fields(row)["effect_count"] = new EvidenceInteger(((EvidenceInteger)row.Get("effect_count")).Value + 1);
                if (contribution.Evidence is not null) Fields(row)["rdps_credit"] = new EvidenceReal(Number(row.Get("rdps_credit")) + Number(contribution.Evidence.Get("rdps_credit")));
            }
        foreach (var row in sources.Values) Fields(row)["rdps_credit"] = Round(Number(row.Get("rdps_credit")));
        var orderedSources = sources.Values.OrderBy(row => -Number(row.Get("rdps_credit")))
            .ThenBy(row => String(row.Get("character_name")), PythonDisplay.CodePointComparer).ToArray();
        var fields = Fields(result);
        fields["zones"] = Array(orderedZones);
        fields["ignored_effects"] = Array(state.IgnoredEffects);
        fields["product_external_multiplier"] = Round(shares.ProductExternal);
        fields["attacker_share"] = Round(shares.AttackerShare);
        fields["external_pool"] = Round(shares.ExternalPool);
        fields["external_sources"] = Array(orderedSources);
        fields["zone_summary"] = Text(string.Join(" / ", orderedZones.Where(row => Number(row.Get("external_multiplier")) > 1.0001)
            .Select(row => $"{String(row.Get("zone_label"))} x{Number(row.Get("external_multiplier")).ToString("F4", CultureInfo.InvariantCulture)}")));
        fields["buff_source_summary"] = Text(string.Join(" / ", orderedSources.Where(row => Number(row.Get("rdps_credit")) > .0001)
            .Select(row => $"{String(row.Get("character_name"))} +{Number(row.Get("rdps_credit")).ToString("F1", CultureInfo.InvariantCulture)}")));
        fields["packet_modifier_uids"] = Obj(("attacker", Array(state.AttackerModifierUids.Order(PythonDisplay.CodePointComparer).Select(Text))),
            ("defender", Array(state.DefenderModifierUids.Order(PythonDisplay.CodePointComparer).Select(Text))));
        fields["packet_modifier_details"] = Array(ModifierDetails(state));
        return result;
    }

    private IEnumerable<EvidenceObject> ModifierDetails(HitAllocation state)
    {
        var current = ((BigInteger)state.TimestampMs, (BigInteger)state.LineNumber);
        static BigInteger Int(EvidenceValue value) => EffectIdentity.Integer(CatalogValues.Or(value, new EvidenceInteger(0)));
        static (BigInteger, BigInteger) Stamp(EvidenceObject row, string time, string line) => (Int(row.Get(time)), Int(row.Get(line)));
        foreach (var (side, uids) in new[] { ("attacker", state.AttackerModifierUids), ("defender", state.DefenderModifierUids) })
            foreach (var uid in uids.Order(PythonDisplay.CodePointComparer))
            {
                var matches = (state.Input.BuffRecordsByUid?.GetValueOrDefault(uid) ?? []).Where(row =>
                    current.CompareTo(Stamp(row, "ts_ms", "line_no")) >= 0
                    && (row.Get("end_ts_ms") is EvidenceNull || current.CompareTo(Stamp(row, "end_ts_ms", "end_line_no")) < 0)
                    && (row.Get("snapshot_end_ts_ms") is EvidenceNull || current.CompareTo(Stamp(row, "snapshot_end_ts_ms", "snapshot_end_line_no")) < 0)
                    && (state.LineNumber != 0 || !new[] { "ts_ms", "end_ts_ms", "snapshot_end_ts_ms" }.Any(key => EvidenceJson.PythonEquals(row.Get(key), new EvidenceInteger(state.TimestampMs))))).ToArray();
                if (matches.Length != 1)
                {
                    yield return Obj(("side", Text(side)), ("uid", Text(uid)), ("event_key", Text("")), ("event_name", Text("")),
                        ("source_character_name", Text("")), ("target_name", Text("")), ("bb_values", BuffEvidence.Object()));
                    continue;
                }
                var labeled = labels(matches[0]);
                var record = labeled.Record;
                var blackboard = CatalogValues.Or(record.Get("bb_values"), BuffEvidence.Object()) as EvidenceObject ?? throw new InvalidDataException("Modifier blackboard must be an object");
                var keys = CatalogValues.Iterable(CatalogValues.Or(record.Get("bb_keys"), new EvidenceArray([]))).Select(CatalogValues.Text).Distinct(StringComparer.Ordinal).Order(PythonDisplay.CodePointComparer);
                yield return Obj(("side", Text(side)), ("uid", Text(uid)), ("event_key", record.Get("event_key")),
                    ("event_name", CatalogValues.Or(Text(string.Join(" / ", labeled.Labels)), record.Get("event_key"), Text(""))),
                    ("source_character_key", record.Get("source_character_key")), ("source_character_name", record.Get("source_character_name")),
                    ("target_key", CatalogValues.Or(record.Get("target_character_key"), record.Get("target_enemy_key"))),
                    ("target_name", CatalogValues.Or(record.Get("target_character_name"), record.Get("target_enemy_name"), record.Get("owner_raw"), Text(""))),
                    ("bb_values", BuffEvidence.Clone(blackboard)), ("bb_keys", Array(keys.Select(Text))));
            }
    }
}
