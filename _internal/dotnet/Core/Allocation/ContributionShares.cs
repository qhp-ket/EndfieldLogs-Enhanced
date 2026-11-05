using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Allocation;

public sealed record ContributionShares(double ProductExternal, double AttackerShare, double ExternalPool,
    IReadOnlyDictionary<string, double> Contributions);

/// <summary>Log-marginal accounting in recorded zone/provider order; computation stays at full precision.</summary>
public static class LogMarginalAllocation
{
    public static ContributionShares Allocate(HitAllocation state) => Allocate(state.Attacker, state.HitValue, state.Multipliers,
        state.ExternalByZone.ToDictionary(pair => pair.Key, pair => (IReadOnlyList<ExternalEffectContribution>)pair.Value, StringComparer.Ordinal),
        state.ExternalSums, state.IncludeDebug);

    public static ContributionShares Allocate(string attacker, double hitValue, IReadOnlyDictionary<string, double> multipliers,
        IReadOnlyDictionary<string, IReadOnlyList<ExternalEffectContribution>> external, IReadOnlyDictionary<string, double> sums, bool includeDebug)
    {
        Dictionary<string, double> credits = new(StringComparer.Ordinal);
        void Add(string key, double value) => credits[key] = credits.GetValueOrDefault(key) + value;
        double product = 1, attackerShare, pool;
        foreach (var value in multipliers.Values) product *= value;
        if (multipliers.Count == 0 || product <= 1)
        {
            attackerShare = hitValue;
            pool = 0;
            Add(attacker, hitValue);
        }
        else
        {
            attackerShare = hitValue / product;
            pool = hitValue - attackerShare;
            Add(attacker, attackerShare);
            var logTotal = PythonFloatSum.Sum(multipliers.Values.Select(value => Math.Log(value)));
            if (logTotal <= 0) Add(attacker, pool);
            else
                foreach (var (zone, contributors) in external)
                {
                    if (!multipliers.TryGetValue(zone, out var multiplier)) continue;
                    var share = pool * (Math.Log(multiplier) / logTotal);
                    var sum = sums[zone];
                    if (sum <= 0) { Add(attacker, share); continue; }
                    foreach (var row in contributors)
                    {
                        var credit = share * (row.Rate / sum);
                        if (includeDebug && row.Evidence is not null)
                            ((Dictionary<string, EvidenceValue>)row.Evidence.Fields)["rdps_credit"] = AllocationDebug.Round4(new EvidenceReal(credit));
                        Add(row.Provider, credit);
                    }
                }
        }
        return new(product, attackerShare, pool, credits.Where(pair => pair.Value > 0).ToDictionary(StringComparer.Ordinal));
    }
}
