using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Observed packet projections for labels. These hints do not authorize rDPS allocation.</summary>
public sealed class PacketEffectDisplayCatalog(PacketBuffCatalog packets, EnhancedChildEffectCatalog enhanced)
{
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static bool Allowed(string zone) => zone is "dmg_inc" or "amp" or "combo" or "vuln_taken" or "fragile" or "crit";
    private static double? Positive(EvidenceValue value) => BuffEvidence.OptionalFloat(value) is > 0 and var number ? number : null;
    private static EvidenceReal Real(double value) => new(value);
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());

    private EvidenceObject Hint(EvidenceObject record) => record.Get("packet_mapping") as EvidenceObject
        ?? packets.Hint(CatalogValues.Text(CatalogValues.Or(record.Get("raw_event_key"), record.Get("event_key"), new EvidenceText("unknown_buff")))) ?? Empty;

    private static bool AllowsConstants(EvidenceObject hint) => CatalogValues.Truth(hint.Get("allow_static_rate"))
        || CatalogValues.Truth(hint.Get("allow_static_rates")) || Text(hint.Get("value_source")).ToLowerInvariant() is "static_literal" or "constant";

    private static EvidenceObject Blackboard(EvidenceObject record)
    {
        var value = CatalogValues.Or(record.Get("bb_values"), Empty);
        return value as EvidenceObject ?? throw new InvalidDataException("Packet blackboard must be an object");
    }

    public IReadOnlyList<EvidenceObject> Static(EvidenceObject record)
    {
        var hint = Hint(record);
        var bb = Blackboard(record);
        var specs = hint.Get("effects") is EvidenceArray array ? array.Items.OfType<EvidenceObject>()
            : enhanced.For(Text(record.Get("event_key")));
        var constants = AllowsConstants(hint);
        List<EvidenceObject> effects = [];
        foreach (var spec in specs)
        {
            var zone = Text(spec.Get("zone"));
            if (!Allowed(zone)) continue;
            var element = CatalogValues.Text(CatalogValues.Or(spec.Get("element"), new EvidenceText("all")));
            var key = Text(spec.Get("bb_key"));
            var preferred = Text(spec.Get("prefer_runtime_rate_key"));
            var rate = key.Length > 0 ? Positive(bb.Get(key)) : null;
            if (rate is null && preferred.Length > 0) rate = Positive(bb.Get(preferred));
            if (rate is null && constants) rate = Positive(spec.Get("rate"));
            if (rate is null) continue;
            var effect = BuffEvidence.Object(("zone", new EvidenceText(zone)), ("element", new EvidenceText(element)), ("rate", Real(rate.Value)));
            if (key.Length > 0)
            {
                effect = new(new Dictionary<string, EvidenceValue>(effect.Fields) { ["bb_key"] = new EvidenceText(key) });
                effect = EffectConditions.AttachBlackboardCondition(effect, key);
            }
            effects.Add(effect);
        }
        return effects;
    }

    public IReadOnlyList<EvidenceObject> Dynamic(EvidenceObject record)
    {
        var hint = Hint(record);
        if (hint.Get("dynamic_effects") is not EvidenceArray specs) return [];
        var bb = Blackboard(record);
        var constants = AllowsConstants(hint);
        List<EvidenceObject> effects = [];
        foreach (var spec in specs.Items.OfType<EvidenceObject>())
        {
            var zone = Text(spec.Get("zone"));
            if (!Allowed(zone)) continue;
            var element = CatalogValues.Text(CatalogValues.Or(spec.Get("element"), new EvidenceText("all")));
            var baseKeys = Keys(spec.Get("base_bb_keys")).ToArray();
            var baseKey = CatalogValues.Text(CatalogValues.Or(spec.Get("base_bb_key"), spec.Get("bb_key"), new EvidenceText("")));
            if (baseKeys.Length == 0 && baseKey.Length > 0) baseKeys = [baseKey];
            double? baseRate = null;
            foreach (var candidate in baseKeys)
                if (Positive(bb.Get(candidate)) is double rate) { baseRate = rate; baseKey = candidate; break; }
            baseRate ??= constants ? Positive(spec.Get("base_rate")) ?? 0 : 0;
            var addKey = Text(spec.Get("add_bb_key"));
            var delayKey = Text(spec.Get("delay_bb_key"));
            var maxKey = Text(spec.Get("max_bb_key"));
            double RuntimeOrLiteral(string key, string literal) =>
                (key.Length > 0 ? Positive(bb.Get(key)) : null) ?? (constants ? Positive(spec.Get(literal)) ?? 0 : 0);
            var addition = RuntimeOrLiteral(addKey, "delayed_add_rate");
            var delay = RuntimeOrLiteral(delayKey, "delay_sec");
            var maximum = RuntimeOrLiteral(maxKey, "max_rate");
            var tick = constants ? Positive(spec.Get("tick_rate")) ?? 0 : 0;
            var tickKey = "";
            foreach (var candidate in Keys(spec.Get("tick_bb_keys")))
                if (Positive(bb.Get(candidate)) is double rate)
                {
                    tickKey = candidate;
                    tick = rate * Multiplier(CatalogValues.Or(spec.Get("tick_multiplier"), Real(1)));
                    break;
                }
            if (baseRate <= 0 && addition <= 0 && tick <= 0) continue;
            Dictionary<string, EvidenceValue> fields = new(StringComparer.Ordinal)
            {
                ["zone"] = new EvidenceText(zone), ["element"] = new EvidenceText(element), ["base_rate"] = Real(baseRate.Value),
                ["tick_rate"] = Real(tick), ["max_rate"] = Real(maximum), ["delayed_add_rate"] = Real(addition), ["delay_sec"] = Real(delay),
            };
            foreach (var (field, key) in new[] { ("bb_key", baseKey), ("add_bb_key", addKey), ("delay_bb_key", delayKey), ("tick_bb_key", tickKey), ("max_bb_key", maxKey) })
                if (key.Length > 0) fields[field] = new EvidenceText(key);
            if (CatalogValues.Truth(spec.Get("dynamic_key"))) fields["dynamic_key"] = BuffEvidence.Clone(spec.Get("dynamic_key"));
            effects.Add(new(fields));
        }
        return effects;
    }

    private static IEnumerable<string> Keys(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value, new EvidenceArray([])))
        .Select(CatalogValues.Text).Where(key => key.Length > 0);

    private static double Multiplier(EvidenceValue value) => value switch
    {
        EvidenceBoolean flag => flag.Value ? 1 : 0,
        EvidenceInteger integer when double.IsFinite((double)integer.Value) => (double)integer.Value,
        EvidenceInteger => throw new OverflowException("int too large to convert to float"),
        EvidenceReal real => real.Value,
        EvidenceText text => TraceFields.TryFloat(text.Value, out var number) ? number : throw new FormatException("Invalid tick multiplier"),
        _ => throw new InvalidCastException("Tick multiplier must be numeric"),
    };

    public BigInteger? StackLimit(EvidenceObject record)
    {
        var bb = record.Get("bb_values") as EvidenceObject ?? Empty;
        foreach (var key in new[] { "max_stack", "stack_limit", "maxStack", "stackLimit" })
            if (EffectStackPolicy.Positive(bb.Get(key)) is BigInteger limit) return limit;
        return EffectStackPolicy.Positive(Hint(record).Get("stack_limit"));
    }
}
