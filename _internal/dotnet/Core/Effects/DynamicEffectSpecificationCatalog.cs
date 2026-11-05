using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Bind approved dynamic formulas to observed parameters without synthesizing refreshes.</summary>
public sealed class DynamicEffectSpecificationCatalog(EffectApproval approval, EffectSpecificationCatalog staticEffects,
    IReadOnlyDictionary<string, EvidenceObject> roots, PacketBuffCatalog packets)
{
    private static readonly string[] Zones = ["atk", "dmg_inc", "amp", "fragile", "vuln_taken", "res", "combo", "arts_strength", "prod_dmg_inc", "prod_vuln_taken"];
    private static readonly string[] Elements = ["all", "physical", "spell", "fire", "pulse", "cryst", "natural"];
    private static readonly (string Parameter, string Key, string Aliases, string Provenance)[] Parameters =
    [
        ("base_rate", "base_bb_key", "base_bb_keys", "bb_key"),
        ("tick_rate", "tick_bb_key", "tick_bb_keys", "tick_bb_key"),
        ("delayed_add_rate", "add_bb_key", "", "add_bb_key"),
        ("delay_sec", "delay_bb_key", "", "delay_bb_key"),
        ("max_rate", "max_bb_key", "", "max_bb_key"),
    ];
    private static EvidenceText Text(string value) => new(value);
    private static string String(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, Text("")));
    private static EvidenceObject Object(EvidenceValue value) => value as EvidenceObject ?? throw new InvalidDataException("Expected an evidence object");
    private static EvidenceObject Empty { get; } = new(new Dictionary<string, EvidenceValue>());
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])));
    private static EvidenceArray Array(IEnumerable<EvidenceValue> items) => new(items.ToArray());
    private static bool Truth(EvidenceValue value) => CatalogValues.Truth(value);
    private static bool Same(EvidenceValue left, EvidenceValue right) => EvidenceJson.PythonEquals(left, right);

    public RegistryEffectsResult Collect(EvidenceObject source)
        => CollectCore(source, ownsEvidence: false);

    internal RegistryEffectsResult CollectOwned(EvidenceObject source)
        => CollectCore(source, ownsEvidence: true);

    private RegistryEffectsResult CollectCore(EvidenceObject source, bool ownsEvidence)
    {
        var fields = new Dictionary<string, EvidenceValue>((ownsEvidence ? source
            : (EvidenceObject)BuffEvidence.Clone(source)).Fields, StringComparer.Ordinal);
        fields.Remove("rdps_unresolved_dynamic_effect");
        EvidenceObject Record() => new(fields);
        RegistryEffectsResult Unresolved(string? reason = null)
        {
            fields["rdps_unresolved_dynamic_effect"] = new EvidenceBoolean(true);
            if (reason is not null) fields["rdps_whitelist_rejection"] = Text(reason);
            return new(Record(), []);
        }
        var record = Record();
        if (Truth(record.Get("rdps_live_identity_conflict"))) return Unresolved();
        var entry = approval.Match(record);
        if (entry is null || !Truth(entry.Get("dynamic")) || Truth(record.Get("packet_mapping_rejected"))) return new(record, []);

        if (Items(entry.Get("_rdps_whitelist_keys")).Any(key => Same(key, Text("buff_chr_0023_antal_normal_fragile"))))
        {
            var snapshots = record.Get("keyword_rate_snapshots");
            if (Truth(snapshots) && Truth(entry.Get("_keyword_origin")))
            {
                var baseFields = new Dictionary<string, EvidenceValue>(fields, StringComparer.Ordinal);
                baseFields.Remove("keyword_rate_snapshots");
                var effects = (ownsEvidence ? staticEffects.CollectStaticOwned(new(baseFields)) : staticEffects.CollectStatic(new(baseFields))).Effects;
                List<EvidenceValue> sessions = [];
                foreach (var row in Items(snapshots))
                {
                    var session = Object(row).Get("session_id");
                    if (!sessions.Any(value => Same(value, session))) sessions.Add(session);
                }
                if (sessions is [var identity] && identity is not EvidenceNull && effects.Count > 0)
                    return new(record, effects.Select(effect => new EvidenceObject(new Dictionary<string, EvidenceValue>(effect.Fields, StringComparer.Ordinal)
                    {
                        ["base_rate"] = effect.Get("rate"), ["keyword_rate_snapshots"] = BuffEvidence.Clone(snapshots),
                        ["keyword_session_id"] = identity,
                    })).ToArray());
            }
            return Unresolved();
        }

        if (String(record.Get("event_key")) is "buff_common_natural_natural_corrupt_do" or "buff_common_natural_cryst_triggered" or "buff_common_natural_fire_triggered")
        {
            var snapshots = CatalogValues.Or(record.Get("attribute_refresh_snapshots"), record.Get("resistance_parameter_snapshots"));
            if (Truth(snapshots))
            {
                var root = roots.GetValueOrDefault(String(record.Get("event_key"))) ?? Empty;
                var attributes = Object(CatalogValues.Or(root.Get("attributeModifier"), Empty));
                var approvedKeys = Items(entry.Get("effects")).Select(Object).Where(item => Same(item.Get("zone"), Text("res")))
                    .Select(item => item.Get("bb_key")).ToArray();
                Dictionary<string, List<EvidenceValue>> byElement = new(StringComparer.Ordinal);
                foreach (var value in Items(attributes.Get("attributeModifiers")))
                {
                    var modifier = Object(value);
                    var element = String(modifier.Get("attributeType")) switch
                    {
                        "PhysicalResistance" => "physical", "NaturalResistance" => "natural", "CrystResistance" => "cryst",
                        "PulseResistance" => "pulse", "FireResistance" => "fire", "EtherResistance" => "ether", _ => null,
                    };
                    if (element is null) continue;
                    var parameter = Object(CatalogValues.Or(modifier.Get("param"), Empty));
                    var key = parameter.Get("blackboardKey");
                    if (!Same(modifier.Get("formulaItem"), Text("BaseAddition")) || !Same(modifier.Get("modifyAttributeType"), Text("Specific"))
                        || parameter.Get("useBlackboardKey") is not EvidenceBoolean { Value: true } || !approvedKeys.Any(value => Same(value, key)))
                        return Unresolved();
                    if (!byElement.TryGetValue(element, out var keys)) byElement[element] = keys = [];
                    keys.Add(key);
                }
                if (byElement.Count > 0)
                    return new(record, byElement.Select(row => new EvidenceObject(new Dictionary<string, EvidenceValue>
                    {
                        ["zone"] = Text("res"), ["element"] = Text(row.Key), ["base_rate"] = new EvidenceReal(0),
                        ["parameter_keys"] = Array(row.Value), ["parameter_snapshots"] = BuffEvidence.Clone(snapshots),
                        ["external_rdps_allowed"] = new EvidenceBoolean(true), ["rdps_whitelist_keys"] = Array(Items(entry.Get("_rdps_whitelist_keys"))),
                    })).ToArray());
            }
        }

        var hint = record.Get("packet_mapping") as EvidenceObject
            ?? packets.Hint(String(CatalogValues.Or(record.Get("raw_event_key"), record.Get("event_key")))) ?? Empty;
        var specs = hint.Get("dynamic_effects") as EvidenceArray;
        if (specs is null || specs.Items.Count == 0) specs = entry.Get("dynamic_effects") as EvidenceArray;
        if (specs is null || specs.Items.Count == 0) return Unresolved();
        var blackboard = Object(CatalogValues.Or(record.Get("bb_values"), Empty));
        var allowConstant = Truth(hint.Get("allow_static_rate")) || Truth(hint.Get("allow_static_rates"))
            || String(hint.Get("value_source")).ToLowerInvariant() is "static_literal" or "constant";
        List<EvidenceObject> result = [];
        foreach (var value in specs.Items)
        {
            if (value is not EvidenceObject spec || !Zones.Contains(String(spec.Get("zone")), StringComparer.Ordinal)
                || !Elements.Contains(String(spec.Get("element")), StringComparer.Ordinal)) return Unresolved();
            var declared = Items(CatalogValues.Or(entry.Get("dynamic_effects"), entry.Get("effects"))).Select(Object)
                .Where(item => Same(item.Get("zone"), spec.Get("zone"))
                    && Same(item.Fields.GetValueOrDefault("element", Text("all")), spec.Get("element"))).ToArray();
            if (declared.Length == 0) return Unresolved("dynamic_effect_not_declared");
            Dictionary<string, EvidenceValue> effect = new(StringComparer.Ordinal) { ["zone"] = spec.Get("zone"), ["element"] = spec.Get("element") };
            foreach (var (parameter, keyField, aliasesField, provenance) in Parameters)
            {
                var aliases = aliasesField.Length > 0 ? spec.Get(aliasesField) : new EvidenceArray([]);
                if (aliases is not EvidenceNull and not EvidenceArray) return Unresolved();
                var keys = Items(aliases).Where(Truth).Select(CatalogValues.Text).Distinct(StringComparer.Ordinal).ToList();
                var primary = CatalogValues.Or(spec.Get(keyField), parameter == "base_rate" ? spec.Get("bb_key") : EvidenceNull.Value);
                if (Truth(primary) && !keys.Contains(CatalogValues.Text(primary), StringComparer.Ordinal)) keys.Insert(0, CatalogValues.Text(primary));
                var values = keys.Where(blackboard.Fields.ContainsKey).Select(key => (Key: key, Value: BuffEvidence.OptionalFloat(blackboard.Get(key))))
                    .Select(row => (row.Key, Value: String(spec.Get("zone")) == "res" && row.Value < 0 ? -row.Value : row.Value)).ToArray();
                if (values.Length > 0)
                {
                    if (values.Any(row => row.Value is null or < 0) || values.Select(row => row.Value).Distinct().Count() != 1) return Unresolved();
                    effect[parameter] = new EvidenceReal(values[0].Value!.Value);
                    effect[provenance] = Text(values[0].Key);
                }
                else if (spec.Fields.TryGetValue(parameter, out var literal) && allowConstant)
                {
                    var number = BuffEvidence.OptionalFloat(literal);
                    if (number is null or < 0) return Unresolved();
                    effect[parameter] = new EvidenceReal(number.Value);
                }
                else if (keys.Count > 0 || spec.Fields.ContainsKey(parameter)) return Unresolved();
                else effect[parameter] = new EvidenceReal(0);
            }
            var multiplier = BuffEvidence.OptionalFloat(spec.Fields.GetValueOrDefault("tick_multiplier", new EvidenceInteger(1)));
            var tick = ((EvidenceReal)effect["tick_rate"]).Value;
            if (multiplier is null or < 0 || !double.IsFinite(tick * multiplier.Value)) return Unresolved();
            effect["tick_rate"] = new EvidenceReal(tick * multiplier.Value);
            HashSet<string> declaredKeys = new(StringComparer.Ordinal);
            foreach (var item in declared)
            {
                foreach (var key in new[] { "bb_key", "base_bb_key", "tick_bb_key", "add_bb_key", "delay_bb_key", "max_bb_key" })
                    if (Truth(item.Get(key))) declaredKeys.Add(CatalogValues.Text(item.Get(key)));
                foreach (var key in new[] { "bb_keys", "base_bb_keys", "tick_bb_keys", "required_bb_keys" })
                    declaredKeys.UnionWith(Items(item.Get(key)).Select(CatalogValues.Text));
            }
            if (Parameters.Select(row => row.Provenance).Where(key => Truth(effect.GetValueOrDefault(key, EvidenceNull.Value)))
                .Select(key => CatalogValues.Text(effect[key])).Any(key => !declaredKeys.Contains(key))) return Unresolved("dynamic_operand_not_declared");
            foreach (var (parameter, _, _, provenance) in Parameters)
                if (spec.Fields.ContainsKey(parameter) && !Truth(effect.GetValueOrDefault(provenance, EvidenceNull.Value))
                    && !declared.Any(item => item.Fields.ContainsKey(parameter) && BuffEvidence.OptionalFloat(item.Get(parameter)) == ((EvidenceReal)effect[parameter]).Value))
                    return Unresolved("dynamic_literal_not_declared");
            // Assignment results do not prove a modifier refresh. Configured tick/delay terms cannot be integrated.
            if (((EvidenceReal)effect["tick_rate"]).Value != 0 || ((EvidenceReal)effect["delayed_add_rate"]).Value != 0) return Unresolved();
            if (Truth(spec.Get("dynamic_key"))) effect["dynamic_key"] = spec.Get("dynamic_key");
            if (spec.Fields.TryGetValue("condition", out var condition)) effect["condition"] = BuffEvidence.Clone(condition);
            if (declared.All(item => item.Fields.ContainsKey("condition")))
            {
                var restriction = BuffEvidence.Object(("type", Text("any")), ("source", Text("rdps_whitelist")),
                    ("conditions", Array(declared.Select(item => BuffEvidence.Clone(item.Get("condition"))))));
                effect["condition"] = effect.TryGetValue("condition", out var own)
                    ? BuffEvidence.Object(("type", Text("all")), ("conditions", new EvidenceArray([own, restriction]))) : restriction;
            }
            effect["external_rdps_allowed"] = new EvidenceBoolean(true);
            effect["rdps_whitelist_keys"] = Array(Items(entry.Get("_rdps_whitelist_keys")));
            result.Add(new(effect));
        }
        return new(record, result);
    }
}
