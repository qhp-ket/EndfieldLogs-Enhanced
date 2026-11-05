using System.Text.Json.Nodes;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class ComboWindowSpecs
{
    public static void Run(Action<bool, string> check)
    {
        // Inputs come from the fixed synthetic chain; expected behavior below is independent of its golden output.
        var fixture = JsonNode.Parse(File.ReadAllText(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../Fixtures/combo-windows.json"))))!;
        var root = (EvidenceObject)EvidenceJson.Parse(fixture["roots_json"]!.GetValue<string>());
        var roots = root.Fields.ToDictionary(row => row.Key, row => (EvidenceObject)row.Value);
        var registry = (EvidenceObject)EvidenceJson.Parse(fixture["registry_json"]!.GetValue<string>());
        var input = (EvidenceObject)EvidenceJson.Parse(fixture["cases"]![0]!["config_json"]!.GetValue<string>());
        var hits = ((EvidenceArray)input.Get("hits")).Items.Cast<EvidenceObject>().ToArray();
        var records = ((EvidenceArray)input.Get("records")).Items.Cast<EvidenceObject>().ToArray();
        SpecialComboWindowBuilder Builder(EvidenceObject approvalRegistry) => new(roots, new Dictionary<string, string>(),
            new(approvalRegistry, roots, new Dictionary<string, string>(), new Dictionary<string, string>()));
        var builder = Builder(registry);
        var signature = EvidenceJsonSignature.Sorted(input);
        var result = builder.Build(hits, records);
        check(result.Windows is [var window] && window.Get("combo_source_uids") is EvidenceArray
            { Items: [EvidenceText { Value: "10001" }, EvidenceText { Value: "10002" }, EvidenceText { Value: "10003" }] }
            && window.Get("source_character_key") is EvidenceText { Value: "chr_0019_karin" },
            "The exact modifier resolves to its two explicit origins and original provider");
        var effect = (EvidenceObject)((EvidenceArray)result.Windows.Single().Get("zone_effects")).Items.Single();
        check(effect.Get("rate") is EvidenceReal rate && Math.Abs(rate.Value - .3) < 1e-15
            && effect.Get("rdps_whitelist_keys") is EvidenceArray { Items: [EvidenceText { Value: "buff_common_affixes_combo_trigger::" }] },
            "The observed 0.2 scale contributes 0.3 to a skill hit under the reviewed 1.5 factor");
        var exact = EffectWindowEvaluation.At(result.Windows.Single(), new(1500, 50, 20, "synthetic-combo-session"));
        var adjacent = EffectWindowEvaluation.At(result.Windows.Single(), new(1500, 51, 21, "synthetic-combo-session"));
        check(exact.Effects.Count == 1 && adjacent.Effects.Count == 0,
            "A single-hit projection includes the observed line and excludes the adjacent hit at the same millisecond");
        check(EvidenceJsonSignature.Sorted(input) == signature && result.Hits[0].Get("rdps_unresolved_effect_conditions") is EvidenceNull,
            "Successful window construction preserves source hits and BUFF records");
        var broken = records.Select(record => new EvidenceObject(new Dictionary<string, EvidenceValue>(record.Fields))).ToArray();
        broken[2] = new(new Dictionary<string, EvidenceValue>(broken[2].Fields) { ["origin_observations"] = new EvidenceArray([]) });
        var rejected = builder.Build(hits, broken);
        check(rejected.Windows.Count == 0 && rejected.Hits[0].Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true }
            && rejected.Hits[0].Get("combo_unresolved_reasons") is EvidenceArray { Items: [EvidenceObject reason] }
            && reason.Get("reason") is EvidenceText { Value: "missing_or_conflicting_combo_creation_origin" },
            "A missing origin produces an explicit unresolved reason without guessing a nearby provider");
        var again = builder.Build(hits, records);
        check(again.Windows.Count == 1 && again.Hits[0].Get("combo_unresolved_reasons") is EvidenceNull
            && hits[0].Get("rdps_unresolved_effect_conditions") is EvidenceNull,
            "A failed analysis does not contaminate later calls or the caller's evidence");
        var unauthorized = Builder((EvidenceObject)EvidenceJson.Parse("{}")).Build(hits, records);
        check(unauthorized.Windows.Count == 0 && unauthorized.Hits[0].Get("combo_unresolved_reasons") is EvidenceNull,
            "A complete creation chain alone cannot authorize external credit without its reviewed projection");
        var mismatched = new EvidenceObject(new Dictionary<string, EvidenceValue>(hits[0].Fields) { ["packet_session_id"] = new EvidenceText("other") });
        var other = builder.Build([mismatched], records);
        check(other.Windows.Count == 0 && other.Hits[0].Get("combo_unresolved_reasons") is EvidenceArray { Items: [EvidenceObject failure] }
            && failure.Get("reason") is EvidenceText { Value: "missing_combo_creation_parameters" },
            "Creation anchors from another packet session never supply a rate");
    }
}
