using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

public enum AttackDependence { Linear, Independent, Affine, Unknown }

public sealed record AttackDependenceResult(AttackDependence Kind, EvidenceValue Calculation)
{
    public string EvidenceKind => Kind.ToString().ToLowerInvariant();
}

/// <summary>Classify observed attack dependence; template fallback never borrows a unit's affine parameters.</summary>
public sealed class AttackDependenceClassifier(
    Func<string, IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>> damageUnits)
{
    public AttackDependenceClassifier(SkillDamageUnits damageUnits) : this(damageUnits.For) { }

    // The caller owns the hit and commits EvidenceKind to attack_damage_dependency during allocation.
    public AttackDependenceResult Classify(EvidenceObject hit)
    {
        var calculation = hit.Get("damage_calculation");
        var present = hit.Fields.ContainsKey("damage_calculation");
        IEnumerable<EvidenceObject> candidates = calculation is EvidenceObject exact ? [exact] : [];
        if (calculation is not EvidenceObject && present)
        {
            var skill = CatalogValues.Text(CatalogValues.Or(hit.Get("skill_key"), new EvidenceText("")));
            candidates = damageUnits(skill).Values.SelectMany(units => units)
                .Where(unit => unit.Attribute == "hp" && unit.Calculation is not null)
                .Select(unit => unit.Calculation!);
        }
        var kinds = candidates.Select(ClassifyCandidate).Distinct().ToArray();
        var kind = kinds.Length == 1 ? kinds[0] : present ? AttackDependence.Unknown : AttackDependence.Linear;
        if (kind == AttackDependence.Affine && calculation is not EvidenceObject) kind = AttackDependence.Unknown;
        return new(kind, calculation);
    }

    private static EvidenceObject ObjectOrEmpty(EvidenceValue value) =>
        CatalogValues.Or(value, BuffEvidence.Object()) as EvidenceObject
        ?? throw new InvalidDataException("Attack calculation evidence is not an object");

    private static AttackDependence ClassifyCandidate(EvidenceObject candidate)
    {
        if (candidate.Get("source") is not EvidenceText { Value: "current_typed_damage_unit" }) return AttackDependence.Unknown;
        // Read custom evidence before the simple flag, including malformed dormant custom evidence.
        var custom = ObjectOrEmpty(candidate.Get("atkCalculation"));
        var type = custom.Get("$type");
        if (candidate.Get("simpleCalculation") is EvidenceBoolean { Value: true }) return AttackDependence.Linear;
        if (candidate.Get("simpleCalculation") is not EvidenceBoolean { Value: false }) return AttackDependence.Unknown;
        if (type is EvidenceObject or EvidenceArray) throw new InvalidCastException("Unhashable calculation type");
        switch ((type as EvidenceText)?.Value)
        {
            case "Beyond.Gameplay.Core.AtkScaleCalculation":
            case "Beyond.Gameplay.Core.BreakingAttackCalculation": return AttackDependence.Linear;
            case "Beyond.Gameplay.Core.DefiniteValueCalculation":
            case "Beyond.Gameplay.Core.PrimaryAttrCalculation": return AttackDependence.Independent;
            case "Beyond.Gameplay.Core.MultiplyAttributeCalculation":
                if (custom.Get("attributeType") is not EvidenceText { Value: "Atk" }
                    || custom.Get("valueSource") is not EvidenceText { Value: "AttackerOrHealer" }) return AttackDependence.Independent;
                var addition = ObjectOrEmpty(custom.Get("addition"));
                return addition.Get("useBlackboardKey") is EvidenceBoolean { Value: false }
                    && BuffEvidence.OptionalFloat(addition.Get("value")) == 0
                    ? AttackDependence.Linear : AttackDependence.Affine;
            default: return AttackDependence.Unknown;
        }
    }
}
