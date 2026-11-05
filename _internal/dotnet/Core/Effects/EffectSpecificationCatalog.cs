using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Intersect current typed branches with approved allocation scopes without duplicating a branch.</summary>
public sealed class EffectSpecificationCatalog(EffectApproval approval, SemanticEffectCatalog semantics, EffectStructureCatalog structure)
{
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceObject Obj(params (string Key, EvidenceValue Value)[] fields) => BuffEvidence.Object(fields);
    private static EvidenceArray Strings(IEnumerable<string> values) => new(values.Select(value => (EvidenceValue)Text(value)).ToArray());
    private static EvidenceArray Array(IEnumerable<EvidenceObject> values) => new(values.Cast<EvidenceValue>().ToArray());
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static string String(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, Text("")));
    private static Dictionary<string, EvidenceValue> Copy(EvidenceObject value) => new(value.Fields, StringComparer.Ordinal);

    public RegistryEffectsResult CollectStatic(EvidenceObject source)
        => CollectStaticCore(source, ownsEvidence: false);

    internal RegistryEffectsResult CollectStaticOwned(EvidenceObject source)
        => CollectStaticCore(source, ownsEvidence: true);

    private RegistryEffectsResult CollectStaticCore(EvidenceObject source, bool ownsEvidence)
    {
        var record = ownsEvidence ? source : (EvidenceObject)BuffEvidence.Clone(source);
        RegistryEffectsResult Error(string reason) => new(new(new Dictionary<string, EvidenceValue>(record.Fields, StringComparer.Ordinal)
        {
            ["rdps_unresolved_semantic_condition"] = Strings([reason]),
        }), []);
        if (CatalogValues.Truth(record.Get("rdps_live_identity_conflict"))) return Error("conflicting_live_buff_identity");
        var entry = approval.Match(record);
        if (entry is null && structure.Classify(record) is not null) return new(record, []);
        if (entry is null)
        {
            var current = semantics.Collect(record);
            record = current.Record;
            var effects = current.Effects.Select(effect => new EvidenceObject(new Dictionary<string, EvidenceValue>(effect.Fields, StringComparer.Ordinal)
            {
                ["external_rdps_allowed"] = new EvidenceBoolean(false), ["rdps_whitelist_keys"] = Strings([]),
            })).ToArray();
            return effects.Length == 0 && !CatalogValues.Truth(record.Get("rdps_unresolved_semantic_condition"))
                ? Error("missing_verified_semantics") : new(record, effects);
        }
        var declared = EffectRegistryRules.ZoneEffects(record, entry);
        var typed = semantics.Collect(declared.Record);
        record = typed.Record;
        if (CatalogValues.Truth(record.Get("rdps_unresolved_semantic_condition"))) return new(record, []);
        if (declared.Effects.Count > 0 && typed.Effects.Count == 0) return Error("missing_current_semantic_effect");
        // Preserve first declaration order, which can differ from the typed branch order.
        List<(int Index, List<EvidenceObject> Specs)> branches = [];
        foreach (var effect in declared.Effects)
        {
            var keys = Items(CatalogValues.Or(effect.Get("_registry_bb_keys"), Strings([String(effect.Get("_registry_bb_key"))]))).ToArray();
            var matches = typed.Effects.Select((semantic, index) => (Semantic: semantic, Index: index))
                .Where(row => EvidenceJson.PythonEquals(effect.Get("zone"), row.Semantic.Get("zone"))
                    && keys.Any(key => EvidenceJson.PythonEquals(Text(String(row.Semantic.Get("bb_key"))), key))).ToArray();
            if (matches.Length == 0) return Error("registry_effect_not_in_current_typed_root");
            if (matches.Any(row => !EvidenceJson.PythonEquals(row.Semantic.Get("rate"), effect.Get("rate"))))
                return Error("conflicting_declared_rates");
            foreach (var match in matches)
            {
                var index = branches.FindIndex(row => row.Index == match.Index);
                if (index < 0) branches.Add((match.Index, [effect]));
                else branches[index].Specs.Add(effect);
            }
        }
        List<EvidenceObject> result = [];
        foreach (var (index, specs) in branches)
        {
            var approved = Copy(typed.Effects[index]);
            approved["external_rdps_allowed"] = new EvidenceBoolean(true);
            approved["rdps_whitelist_keys"] = new EvidenceArray(Items(entry.Get("_rdps_whitelist_keys")).ToArray());
            if (CatalogValues.Truth(entry.Get("_keyword_origin"))) approved["keyword_origin"] = BuffEvidence.Clone(entry.Get("_keyword_origin"));
            List<EvidenceObject> alternatives = [];
            foreach (var spec in specs)
            {
                List<EvidenceValue> terms = [];
                if (spec.Fields.TryGetValue("condition", out var condition)) terms.Add(BuffEvidence.Clone(condition));
                var element = spec.Fields.TryGetValue("element", out var scope) ? scope : Text("all");
                if (!EvidenceJson.PythonEquals(element, Text("all")))
                    terms.Add(Obj(("type", Text("damage_type_in")), ("source", Text("rdps_whitelist")),
                        ("elements", EvidenceJson.PythonEquals(element, Text("spell")) ? Strings(["fire", "pulse", "cryst", "natural"]) : new EvidenceArray([element]))));
                alternatives.Add(terms.Count > 0 ? Obj(("type", Text("all")), ("conditions", new EvidenceArray(terms))) : Obj(("type", Text("always"))));
            }
            if (!alternatives.Any(branch => branch.Get("type") is EvidenceText { Value: "always" }))
            {
                var restriction = Obj(("type", Text("any")), ("source", Text("rdps_whitelist")), ("conditions", Array(alternatives)));
                approved["condition"] = approved.TryGetValue("condition", out var condition)
                    ? Obj(("type", Text("all")), ("source", Text("typed_and_whitelist")), ("conditions", new EvidenceArray([condition, restriction]))) : restriction;
            }
            approved.Remove("_registry_bb_key");
            result.Add(new(approved));
        }
        return new(record, CatalogValues.Truth(entry.Get("dynamic")) ? [] : result);
    }
}
