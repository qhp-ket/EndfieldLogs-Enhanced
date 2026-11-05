using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Allocation;

/// <summary>Counterfactual zone multipliers; unexplained DPD residuals never calibrate external rates.</summary>
public static class AllocationMultipliers
{
    public static void Compute(HitAllocation state)
    {
        state.Multipliers.Clear();
        state.ExternalSums.Clear();
        double combined = 1;
        if (state.SelfByZone.Values.Concat(state.SelfFactorByZone.Values).Concat(state.CapturedByAttribute.Values).Any(value => !double.IsFinite(value)))
            state.InvalidNumericAllocation = true;
        foreach (var (zone, contributors) in state.ExternalByZone)
        {
            if (zone == "atk" && state.AttackBaselineError is not null) continue;
            var external = PythonFloatSum.Sum(contributors.Select(row => row.Rate));
            if (!double.IsFinite(external)) { state.InvalidNumericAllocation = true; break; }
            if (external <= 0) continue;
            var self = state.SelfByZone.GetValueOrDefault(zone);
            if (!double.IsFinite(self) || (zone == "arts_strength" ? 100 : 1) + self <= 0)
            { state.InvalidNumericAllocation = true; break; }
            double multiplier;
            if (zone.StartsWith("prod_", StringComparison.Ordinal))
            {
                multiplier = 1;
                foreach (var row in contributors) multiplier *= 1 + row.Rate;
            }
            else if (zone == "arts_strength")
            {
                static double Arts(double value) => 1 + Math.Max(value, 0) / 100;
                var ratio = Arts(self + external) / Arts(self);
                var exponent = state.Hit.Get("arts_strength_damage_factor_count") is EvidenceInteger integer && !integer.Value.IsZero ? (double)integer.Value : 1;
                multiplier = Math.Pow(ratio, exponent);
                if (double.IsFinite(ratio) && double.IsFinite(exponent) && double.IsInfinity(multiplier)) throw new OverflowException("Arts multiplier exponent overflow");
            }
            else if (zone == "res")
            {
                var numerator = state.ResistanceNumerator ?? throw new InvalidCastException("Unknown resistance numerator");
                var denominator = numerator - external;
                if (!double.IsFinite(denominator) || denominator <= 0)
                {
                    ((Dictionary<string, EvidenceValue>)state.Hit.Fields)["rdps_unresolved_effect_conditions"] = new EvidenceBoolean(true);
                    if (state.IncludeDebug) state.IgnoredEffects.Add(BuffEvidence.Object(("zone", new EvidenceText("res")),
                        ("reason", new EvidenceText("resistance_counterfactual_unresolved")), ("detail", new EvidenceText("nonpositive_without_external_resistance_factor"))));
                    continue;
                }
                multiplier = numerator / denominator;
            }
            else multiplier = (1 + self + external) / (1 + self);
            if (!double.IsFinite(multiplier)) { state.InvalidNumericAllocation = true; break; }
            if (multiplier <= 1) continue;
            state.ExternalSums[zone] = external;
            state.Multipliers[zone] = multiplier;
            combined *= multiplier;
            if (!double.IsFinite(combined)) { state.InvalidNumericAllocation = true; break; }
        }
        if (!state.InvalidNumericAllocation) return;
        var fields = (Dictionary<string, EvidenceValue>)state.Hit.Fields;
        fields["rdps_invalid_numeric_allocation"] = new EvidenceBoolean(true);
        fields["rdps_unresolved_effect_conditions"] = new EvidenceBoolean(true);
        state.Multipliers.Clear();
        state.ExternalSums.Clear();
        state.ExternalByZone.Clear();
        state.SelfByZone.Clear();
        state.SelfFactorByZone.Clear();
        state.ContributorsByZone.Clear();
        if (state.IncludeDebug) state.IgnoredEffects.Add(BuffEvidence.Object(("reason", new EvidenceText("invalid_numeric_allocation")),
            ("reason_group", new EvidenceText("condition_unobservable"))));
    }
}
