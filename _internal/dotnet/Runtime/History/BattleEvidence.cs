using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Runtime.History;

public sealed record ContributionShare(string Key, string Name, double Value, double Percent);
public sealed record ContributionSummary(double Damage, double? Basis, int Covered, int Hits, double Allocated, IReadOnlyList<ContributionShare> Contributions);

/// <summary>Reads canonical per-hit allocations. Missing evidence is retained as unknown.</summary>
public static class BattleEvidence
{
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static string Text(EvidenceValue value) => SettingsData.Truth(value) ? PythonDisplay.String(value) : "";
    public static double? Number(EvidenceValue value) => value is EvidenceBoolean flag ? flag.Value ? 1 : 0 : SettingsData.Number(value, double.NaN) is var number && double.IsFinite(number) ? number : null;
    public static ContributionSummary Summary(IEnumerable<EvidenceObject> events)
    {
        var damage = events.Where(row => Text(row.Get("event_type")) == "damage").ToArray();
        Dictionary<string, double> amounts = new(StringComparer.Ordinal); Dictionary<string, string> names = new(StringComparer.Ordinal); var covered = 0;
        foreach (var row in damage)
        {
            var valid = Rows(row.Get("rdps_contributions")).Where(item => SettingsData.Truth(item.Get("character_key")) && Number(item.Get("value")) is not null).ToArray();
            if (valid.Length > 0) covered++;
            foreach (var item in valid)
            {
                var key = Text(item.Get("character_key")); amounts[key] = amounts.GetValueOrDefault(key) + Number(item.Get("value"))!.Value;
                names[key] = TimelineSkills.CharacterName(key, Text(item.Get("character_name")));
            }
        }
        var allocated = amounts.Values.Sum(); var basis = damage.Select(row => Number(row.Get("rdps_basis_value"))).ToArray();
        return new(damage.Sum(row => Number(row.Get("value")) ?? 0), basis.All(value => value is not null) ? basis.Sum(value => value!.Value) : null,
            covered, damage.Length, allocated, amounts.OrderByDescending(pair => pair.Value).Select(pair => new ContributionShare(pair.Key, names[pair.Key], pair.Value, allocated != 0 ? 100 * pair.Value / allocated : 0)).ToArray());
    }
}
