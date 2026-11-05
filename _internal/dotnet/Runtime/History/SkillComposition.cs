using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Runtime.History;

/// <summary>Display-only skill rows; merged-cast statistics remain supplied by Core.</summary>
public static class SkillComposition
{
    private static IEnumerable<EvidenceObject> Rows(EvidenceValue value) => value is EvidenceArray array ? array.Items.OfType<EvidenceObject>() : [];
    private static string Text(EvidenceValue value) => value is EvidenceText text ? text.Value : "";
    public static IReadOnlyList<EvidenceObject> Build(EvidenceObject snapshot, string character = "")
    {
        var totals = Rows(snapshot.Get("participants")).ToDictionary(row => Text(row.Get("character_key")), row => BattleEvidence.Number(row.Get("total_damage")) ?? 0, StringComparer.Ordinal);
        List<EvidenceObject> result = [];
        foreach (var row in Rows(snapshot.Get("role_skill_stats")))
        {
            var owner = Text(row.Get("character_key")); if (character.Length > 0 && owner != character) continue;
            var label = TimelineSkills.Label(Text(row.Get("skill_key")), Text(row.Get("skill_name"))); var fields = row.Fields.ToDictionary();
            fields["display_character"] = new EvidenceText(TimelineSkills.CharacterName(owner, Text(row.Get("character_name"))));
            fields["display_skill"] = new EvidenceText(label.Name); fields["category"] = new EvidenceText(label.Category);
            fields["damage_percent"] = totals.GetValueOrDefault(owner) is > 0 and var total ? new EvidenceReal(100 * (BattleEvidence.Number(row.Get("total_damage")) ?? 0) / total) : new EvidenceInteger(0);
            result.Add(new(fields));
        }
        return result;
    }
}
