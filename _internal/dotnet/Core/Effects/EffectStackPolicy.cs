using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

public sealed record EffectStackGroup(string OwnerKind, string Owner, string Key, string Reserved = "")
{
    public string[] Fields => [OwnerKind, Owner, Key, Reserved];
}

/// <summary>Native BUFF container ownership and declared limits, independent of source or skill.</summary>
public sealed class EffectStackPolicy(IReadOnlyDictionary<string, EvidenceObject> roots,
    IReadOnlyDictionary<string, EvidenceObject>? semantics = null, IReadOnlyDictionary<string, BigInteger>? weaponLimits = null)
{
    public EvidenceObject? Settings(string key) => roots.GetValueOrDefault(key)?.Get("stackingSettings") as EvidenceObject;
    internal static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    internal static BigInteger? Positive(EvidenceValue value) => TraceFields.PositiveInteger(value switch
    {
        EvidenceInteger integer => integer.Value, EvidenceReal real => real.Value, EvidenceBoolean flag => flag.Value,
        EvidenceText text => text.Value, _ => null,
    });

    public bool IsUnique(string key) => Settings(key)?.Get("stackingType") is EvidenceText { Value: "Unique" };
    public static bool IsFoodPotion(string key) => Regex.IsMatch(key, @"^buff_common_.*_potion(?:_\d+)?$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    public BigInteger? Limit(string key, EvidenceObject? blackboard = null)
    {
        if (key.Length == 0) return null;
        if (Settings(key) is { } settings)
        {
            if (settings.Get("stackingType") is EvidenceText { Value: "HighPriority" }) return BigInteger.One;
            if (settings.Get("stackingType") is EvidenceText { Value: "Unique" } && settings.Get("useMaxStackCntKey") is EvidenceBoolean { Value: false })
                return Positive(settings.Get("maxStackCnt")) ?? BigInteger.One;
            if (settings.Get("useMaxStackCntKey") is EvidenceBoolean { Value: true })
                return Positive(blackboard?.Get(Text(settings.Get("maxStackCntKey"))) ?? EvidenceNull.Value);
            return Positive(settings.Get("maxStackCnt"));
        }
        if (semantics?.GetValueOrDefault(key)?.Get("stacking") is EvidenceObject stacking && Positive(stacking.Get("maxStackCnt")) is BigInteger limit)
            return limit;
        return weaponLimits is not null && weaponLimits.TryGetValue(key, out var exact) ? exact : null;
    }

    public EffectStackGroup Group(EvidenceObject window)
    {
        var key = Text(window.Get("event_key"));
        if (Settings(key) is { } settings && settings.Get("identifierType") is EvidenceText { Value: "StackingKey" })
            key = Text(settings.Get("stackingKey"));
        var actor = Text(window.Get("target_actor_id"));
        return new(actor.Length > 0 ? "actor" : "unresolved_actor", actor.Length > 0 ? actor : Text(window.Get("target_character_key")), key);
    }

    public static EffectStackPolicy Load(ResourceFiles files, IReadOnlyDictionary<string, EvidenceObject>? roots = null)
    {
        var semanticDocument = files.ReadOnlyRelative("data/local_semantics/buff/details.json");
        if (semanticDocument is not (null or EvidenceObject)) throw new InvalidDataException("BUFF semantics must be an object");
        var entries = (semanticDocument as EvidenceObject)?.Get("entries") as EvidenceObject;
        var semantics = entries?.Fields.Where(pair => pair.Value is EvidenceObject)
            .ToDictionary(pair => pair.Key, pair => (EvidenceObject)pair.Value, StringComparer.Ordinal) ?? [];
        Dictionary<string, BigInteger> limits = new(StringComparer.Ordinal);
        foreach (var entry in CatalogValues.Entries(files.ReadRelative("data/local_static/skill/manifest.json")))
        {
            if (!Text(entry.Get("id")).StartsWith("sk_wpn_", StringComparison.Ordinal) || entry.Get("binaryProbe") is not EvidenceObject probe) continue;
            BigInteger? limit = null;
            foreach (var hint in CatalogValues.Iterable(CatalogValues.Or(probe.Get("blackboardDoubleHints"), new EvidenceArray([]))).OfType<EvidenceObject>())
                if (hint.Get("key") is EvidenceText { Value: "max_stack" } && Positive(hint.Get("value")) is BigInteger found) { limit = found; break; }
            if (limit is null || CatalogValues.Or(probe.Get("highConfidenceCreatedBuffIds"), probe.Get("createdBuffIds"), new EvidenceArray([])) is not EvidenceArray ids) continue;
            foreach (var value in ids.Items)
            {
                var key = Text(value);
                if (key.StartsWith("buff_wpn_", StringComparison.Ordinal)) limits[key] = limit.Value;
            }
        }
        return new(roots ?? new BuffRootCatalog(files).Roots, semantics, limits);
    }
}
