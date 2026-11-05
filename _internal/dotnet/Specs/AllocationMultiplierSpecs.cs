using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

internal static class AllocationMultiplierSpecs
{
    private static HitAllocation State(string extra = "")
    {
        var hit = (EvidenceObject)EvidenceJson.Parse("""{"character_key":"a","target_enemy_key":"enemy","hit_value":225,"ts_ms":1000,"line_no":10""" + extra + "}");
        AllocationContextBuilder builder = new(new AttackDependenceClassifier(_ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>()));
        return builder.Prepare(new(new(hit, new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>(), new Dictionary<BigInteger, EvidenceValue>()), [], IncludeDebug: true));
    }
    private static EvidenceObject Row() => new(new Dictionary<string, EvidenceValue>());
    public static void Run(Action<bool, string> check)
    {
        var state = State();
        var first = Row();
        var second = Row();
        var third = Row();
        state.ExternalByZone["atk"] = [new("b", .25, first), new("c", .25, second)];
        state.ExternalByZone["amp"] = [new("b", .5, third)];
        AllocationMultipliers.Compute(state);
        var shares = LogMarginalAllocation.Allocate(state);
        check(state.Multipliers["atk"] == 1.5 && state.Multipliers["amp"] == 1.5 && shares.ProductExternal == 2.25,
            "Independent attack and amplification factors multiply to 2.25");
        check(shares.AttackerShare == 100 && shares.ExternalPool == 125 && shares.Contributions["a"] == 100
            && shares.Contributions["b"] == 93.75 && shares.Contributions["c"] == 31.25,
            "Two equal log zones split 125 equally; equal attack providers split their zone and a repeated provider merges across zones");
        check(shares.Contributions.Values.Sum() == 225 && first.Get("rdps_credit") is EvidenceReal { Value: 31.25 }
            && third.Get("rdps_credit") is EvidenceReal { Value: 62.5 }, "Allocation conserves observed damage and annotates the actual contributor records");
        var self = State();
        self.SelfByZone["atk"] = .5;
        self.ExternalByZone["atk"] = [new("b", .3, null)];
        AllocationMultipliers.Compute(self);
        check(Math.Abs(self.Multipliers["atk"] - 1.2) < 1e-15, "External attack removes only its 0.3 over the existing 1.5 self baseline");
        var resistance = State();
        resistance.ResistanceNumerator = 90;
        resistance.ExternalByZone["res"] = [new("b", 10, null)];
        AllocationMultipliers.Compute(resistance);
        check(resistance.Multipliers["res"] == 1.125, "Resistance counterfactual is 90/(90-10), in points rather than percentage rate");
        var blocked = State();
        blocked.ResistanceNumerator = 10;
        blocked.ExternalByZone["res"] = [new("b", 10, null)];
        AllocationMultipliers.Compute(blocked);
        check(blocked.Multipliers.Count == 0 && blocked.Hit.Get("rdps_unresolved_effect_conditions") is EvidenceBoolean { Value: true }
            && blocked.IgnoredEffects.Single().Get("reason") is EvidenceText { Value: "resistance_counterfactual_unresolved" },
            "A nonpositive resistance counterfactual stays unresolved and cannot receive credit");
        var arts = State(",\"damage_decorate_mask\":1073741832");
        arts.SelfByZone["arts_strength"] = 100;
        arts.ExternalByZone["arts_strength"] = [new("b", 100, null)];
        AllocationMultipliers.Compute(arts);
        check(arts.ArtsStrength.FactorCount == 2 && arts.Multipliers["arts_strength"] == 2.25,
            "A proven physical plus spell anomaly applies both (3/2) arts-strength factors");
        var product = State();
        product.ExternalByZone["prod_dmg_inc"] = [new("b", .2, null), new("c", .3, null)];
        AllocationMultipliers.Compute(product);
        check(product.Multipliers["prod_dmg_inc"] == 1.2 * 1.3, "Product lanes multiply each observed external factor independently");
        var invalid = State();
        invalid.SelfByZone["atk"] = .2;
        invalid.ExternalByZone["atk"] = [new("b", double.PositiveInfinity, Row())];
        AllocationMultipliers.Compute(invalid);
        var fallback = LogMarginalAllocation.Allocate(invalid);
        check(invalid.InvalidNumericAllocation && invalid.Multipliers.Count == 0 && invalid.ExternalByZone.Count == 0
            && invalid.SelfByZone.Count == 0 && fallback.Contributions.Count == 1 && fallback.Contributions["a"] == 225,
            "Invalid arithmetic clears untrustworthy attribution while preserving the full hit for its attacker");
        check(invalid.Hit.Get("rdps_invalid_numeric_allocation") is EvidenceBoolean { Value: true }
            && invalid.IgnoredEffects.Single().Get("reason") is EvidenceText { Value: "invalid_numeric_allocation" },
            "Fallback keeps explicit failed-allocation quality and diagnostic evidence");
        var attackError = State();
        attackError.AttackBaselineError = "missing_damage_base_addition";
        attackError.ExternalByZone["atk"] = [new("b", .2, null)];
        attackError.ExternalByZone["amp"] = [new("c", .5, null)];
        AllocationMultipliers.Compute(attackError);
        check(!attackError.Multipliers.ContainsKey("atk") && attackError.Multipliers["amp"] == 1.5,
            "A missing attack baseline blocks its attack credit while preserving a proven unrelated zone");
        var clean = State();
        var cleanShares = LogMarginalAllocation.Allocate(clean);
        check(cleanShares.ProductExternal == 1 && cleanShares.ExternalPool == 0 && cleanShares.AttackerShare == 225,
            "A hit without external zones is wholly assigned to the attacker");
    }
}
