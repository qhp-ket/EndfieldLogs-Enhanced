using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;

internal static class BattleEvidenceSpecs
{
    public static void Run(Action<bool, string> check)
    {
        var events = (EvidenceArray)EvidenceJson.Parse("""[{"event_type":"damage","value":100,"rdps_basis_value":80,"rdps_contributions":[{"character_key":"support","value":20}]},{"event_type":"damage","value":50},{"event_type":"cast","value":1000}]""");
        var before = PythonSortedJson.Serialize(events); var result = BattleEvidence.Summary(events.Items.OfType<EvidenceObject>());
        check(result.Damage == 150 && result.Hits == 2 && result.Covered == 1 && result.Basis is null, "Missing basis remains unknown and casts never enter hit totals");
        check(result.Allocated == 20 && result.Contributions.Single().Percent == 100 && result.Contributions[0].Key == "support", "Allocation percentages use allocated rDMG; missing shares are never assigned to attacker");
        var invalid = (EvidenceArray)EvidenceJson.Parse("""[{"event_type":"damage","value":10,"rdps_contributions":[{"character_key":"a","value":"invalid"},{"character_key":"","value":100},{"character_key":"a","value":0}]}]""");
        var zero = BattleEvidence.Summary(invalid.Items.OfType<EvidenceObject>());
        check(zero.Covered == 1 && zero.Contributions.Single().Value == 0 && zero.Contributions[0].Percent == 0, "A known zero is evidence; invalid numeric values and absent identities are excluded");
        check(before == PythonSortedJson.Serialize(events), "Inspector projections never alter canonical evidence");
    }
}
