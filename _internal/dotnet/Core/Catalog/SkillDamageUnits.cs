using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

public sealed record SkillDamageUnit(EvidenceValue Index, string Element, string Attribute,
    BigInteger? StaticMask, string? StaticMaskSource, EvidenceObject? Calculation);

/// <summary>Exact typed action units. Static masks describe generation, never observed runtime propagation.</summary>
public sealed class SkillDamageUnits(SkillResourceCatalog skills, BuffRootCatalog buffs)
{
    private readonly Dictionary<string, (IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> Value,
        LinkedListNode<string> Node)> cache = new(StringComparer.Ordinal);
    private readonly LinkedList<string> recency = [];
    private SkillIdentityCatalog? identities;

    public IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> For(string skill)
    {
        if (cache.TryGetValue(skill, out var existing))
        {
            recency.Remove(existing.Node);
            recency.AddLast(existing.Node);
            return existing.Value;
        }
        IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> value;
        if (skill.Length == 0) value = new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>();
        else
        {
            identities ??= new(skills.Skills, new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
            var canonical = identities.CanonicalPacketSkill(skill);
            skills.Profiles.TryGetValue(canonical, out var profile);
            value = Project(canonical, profile, profile is null ? null : buffs.Roots.GetValueOrDefault(canonical));
        }
        if (cache.Count == 4096)
        {
            cache.Remove(recency.First!.Value);
            recency.RemoveFirst();
        }
        cache[skill] = (value, recency.AddLast(skill));
        return value;
    }

    public static IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> Project(
        string canonical, OfficialDamageProfile? profile, EvidenceObject? buffRoot)
    {
        Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> result = [];
        if (canonical.Length == 0 || profile is null) return result;
        Dictionary<(BigInteger, BigInteger), List<(BigInteger Mask, string Element, string Attribute)>> masks = [];
        Stack<EvidenceValue> pending = [];
        if (buffRoot is not null) pending.Push(buffRoot);
        while (pending.TryPop(out var node))
        {
            if (node is EvidenceObject obj)
            {
                if (obj.Get("damageUnits") is EvidenceArray units && OptionalInteger(obj.Get("serverActionIndex")) is BigInteger action)
                    for (var index = 0; index < units.Items.Count; index++)
                    {
                        if (units.Items[index] is not EvidenceObject unit || unit.Get("ignoreDamageImmuneLevel") is not EvidenceText { Value: "None" }
                            || OptionalInteger(unit.Get("damageDecorateMask")) is not BigInteger mask || mask.Sign < 0) continue;
                        if (!masks.TryGetValue((action, index), out var candidates)) masks[(action, index)] = candidates = [];
                        candidates.Add((mask, Text(unit.Get("damageType")).Trim().ToLowerInvariant(),
                            Text(unit.Get("damageAttributeType")).Trim().ToLowerInvariant()));
                    }
                foreach (var child in obj.Fields.Values) pending.Push(child);
            }
            else if (node is EvidenceArray array)
                foreach (var child in array.Items) pending.Push(child);
        }
        foreach (var (rawAction, rawUnits) in profile.Actions)
        {
            if (!Regex.IsMatch(rawAction.Trim(), @"\A[+-]?\d+(?:_\d+)*\z")
                || TraceFields.OptionalInteger(rawAction) is not BigInteger action) continue;
            List<SkillDamageUnit> units = [];
            foreach (var unit in rawUnits)
            {
                var index = unit.Get("index");
                List<(BigInteger Mask, string Element, string Attribute)> candidates = [];
                if (index is EvidenceInteger integer && masks.TryGetValue((action, integer.Value), out var found)) candidates.AddRange(found);
                var element = Text(unit.Get("element"));
                var attribute = Text(unit.Get("damageAttribute"));
                if (unit.Get("damageDecorateMask") is EvidenceInteger mask
                    && unit.Get("ignoreDamageImmuneLevel") is EvidenceText { Value: "None" })
                    candidates.Add((mask.Value, element.ToLowerInvariant(), attribute.ToLowerInvariant()));
                var unique = candidates.Distinct().ToArray();
                var accepted = unique.Length == 1 && unique[0].Element == element.ToLowerInvariant()
                    && unique[0].Attribute == attribute.ToLowerInvariant();
                EvidenceObject? calculation = null;
                if (unit.Get("damageCalculation") is EvidenceObject rawCalculation)
                {
                    var proof = profile.Definition.Get("proof") as EvidenceObject;
                    var sourceProof = TypedResourceBinding.Evidence.Fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
                    sourceProof["scope"] = new EvidenceText("typed_layout_and_exact_resource_only");
                    sourceProof["resourceId"] = new EvidenceText(canonical);
                    foreach (var key in new[] { "sourceSha256", "sourceAsset", "sourceBytes", "consumedBytes" })
                        sourceProof[key] = proof?.Get(key) ?? EvidenceNull.Value;
                    sourceProof["actionId"] = new EvidenceInteger(action);
                    sourceProof["damageUnitIndex"] = index;
                    sourceProof["byteOffset"] = unit.Get("byteOffset");
                    sourceProof["byteEnd"] = unit.Get("byteEnd");
                    var fields = CopyObject(rawCalculation).Fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal);
                    fields["source"] = new EvidenceText("current_typed_damage_unit");
                    fields["sourceProof"] = new EvidenceObject(sourceProof);
                    calculation = new(fields);
                }
                units.Add(new(index, element, attribute, accepted ? unique[0].Mask : null,
                    accepted ? "current_typed_skill_or_buff_exact_unit_generation_only" : null, calculation));
            }
            if (units.Count > 0) result[action] = units;
        }
        return result;
    }

    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));
    private static BigInteger? OptionalInteger(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceText text => TraceFields.OptionalInteger(text.Value),
        EvidenceReal number => TraceFields.OptionalInteger(number.Value),
        _ => null,
    };

    public static EvidenceValue Copy(EvidenceValue value) => value switch
    {
        EvidenceObject obj => CopyObject(obj),
        EvidenceArray array => new EvidenceArray(array.Items.Select(Copy).ToArray()),
        _ => value,
    };

    public static EvidenceObject CopyObject(EvidenceObject value) => new(value.Fields.ToDictionary(pair => pair.Key, pair => Copy(pair.Value), StringComparer.Ordinal));
}
