using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

public sealed record ArtsStrengthDamage(bool Observed, string? Kind, string? Source, int FactorCount);

public static class HitDamageClassification
{
    public static string? Element(IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>> units,
        BigInteger? action, BigInteger? index)
    {
        if (action is not BigInteger a || index is not BigInteger i || a.Sign < 0 || i.Sign < 0
            || !units.TryGetValue(a, out var candidates)) return null;
        var matches = candidates.Where(unit => unit.Index is EvidenceInteger value && value.Value == i).ToArray();
        return matches.Length == 1 && matches[0].Attribute == "hp"
            && matches[0].Element is "physical" or "fire" or "pulse" or "cryst" or "natural" ? matches[0].Element : null;
    }

    public static string? School(string? element) => element switch
    {
        "physical" => "physical",
        "fire" or "pulse" or "cryst" or "natural" or "ether" => "spell",
        _ => null,
    };

    public static ArtsStrengthDamage ArtsStrength(EvidenceValue? observedMask, BigInteger? staticMask = null,
        string? staticSource = null, bool previousObserved = false, string? previousSource = null)
    {
        var present = observedMask is not (null or EvidenceNull);
        var mask = present ? (observedMask as EvidenceInteger)?.Value
            : staticSource == "current_typed_skill_or_buff_exact_unit_generation_only" ? staticMask : null;
        var source = present ? "observed_damage_decorate_mask" : staticSource;
        if (mask is BigInteger bits && bits.Sign >= 0 && bits < BigInteger.One << 64)
        {
            List<string> kinds = [];
            if ((bits & 0x4001C000) != 0) kinds.Add("physical_anomaly");
            if ((bits & 0x0C100038) != 0) kinds.Add("spell_anomaly");
            if ((bits & 0x03C00000) != 0) kinds.Add("spell_burst");
            return new(kinds.Count > 0, kinds.Count == 1 ? kinds[0] : kinds.Count > 1 ? "mixed_anomaly" : null,
                source, ((bits & 0x4001C000) != 0 ? 1 : 0) + ((bits & 0x0FD00038) != 0 ? 1 : 0));
        }
        var explicitClassification = !present && previousObserved && previousSource is null or "caller_supplied_classification";
        return new(explicitClassification, explicitClassification ? "caller_classified_anomaly" : null,
            explicitClassification ? "caller_supplied_classification" : null, explicitClassification ? 1 : 0);
    }
}
