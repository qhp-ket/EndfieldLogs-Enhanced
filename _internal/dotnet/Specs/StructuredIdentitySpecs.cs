using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredIdentitySpecs
{
    private static EvidenceObject E(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    private static TraceEvent Event(string type, string data, long time = 1793412000123)
    {
        var captured = TraceValueProjection.Capture(E(data));
        var fields = ((EvidenceObject)captured.Value).Fields.ToDictionary(); fields["legacy_layout"] = captured.Layout;
        return (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, time, type, new(fields), E("{}"))), header: false);
    }

    public static void Run(Action<bool, string> check)
    {
        var stream = StructuredDamageSpecs.Stream();
        stream.Accept(1, Event("squad", """{"members":[{"template":"chr_0002_beta","entity_id":22},{"template":"chr_0001_alpha","entity_id":"0011"},{"template":"sample","entity_id":33},{"template":"chr_0003_gamma","entity_id":null}]}"""));
        check(stream.Loadouts.SquadActorKeys.Keys.SequenceEqual(new[] { "22", "11" }) && stream.PartyActorIds.SetEquals(["22", "11"]),
            "Squad preserves member order with canonical instance IDs while excluding unresolved templates");
        stream.Accept(2, Event("squad", """{"members":[{"template":"chr_0002_beta","entity_id":22},{"template":"chr_0001_alpha","entity_id":22}]}"""));
        check(stream.Loadouts.SquadActorKeys.Count == 0 && stream.PartyActorIds.SetEquals(["22", "11"]),
            "Duplicate squad member clears current binding but preserves observed party IDs");
        stream.Accept(3, Event("squad", """{"members":[]}"""));
        check(stream.Loadouts.SquadActorKeys.Count == 0 && stream.PartyActorIds.Count == 2, "Empty squad does not discard observed party evidence");
        foreach (var template in new[] { "chr_0001_alpha", "sample", "chr_0001_alpha_123", "chr_0001_alpha_chr_0002_beta", "chr_0001_alpha_1chr_0002_beta", "prefix chr_0001_alpha" })
            foreach (var identity in new[] { "None", "-11", "0", "11", "0011", "11x", "bad chr_0003_gamma_33" })
            {
                var legacy = Regex.Matches(template + "_" + identity, @"(chr_\d{4}_[a-z0-9]+)_(\d+)")
                    .Select(match => (match.Groups[2].Value, match.Groups[1].Value)).ToArray();
                check(ActorIdentity.SquadBindings(new[] { (template, identity) }).SequenceEqual(legacy), "Separate squad fields retain existing member extraction policy");
            }
        var diagnostic = Event("actor_mapping", """{"entity_id":9007199254740993,"template":"chr_0001_alpha","mapping_source":"skill_attach","skill":null}""", -1);
        var clean = StructuredDamageSpecs.Stream(); clean.Accept(1, diagnostic);
        check(clean.PartyActorIds.Count == 0 && clean.Loadouts.SquadActorKeys.Count == 0 && clean.FirstContextMs == -1,
            "Actor mapping diagnostic does not become new ingestion identity authority");
        check(IdentityLegacyExporter.Lines(diagnostic, 330).SequenceEqual(new[] {
            "[05:29:59.999] ACTOR_MAP id=9007199254740993 template=chr_0001_alpha source=skill_attach skill=None\n" }),
            "Independent mapping export preserves wide identity, null skill, time and newline");
        var originalIds = Event("squad", """{"members":[{"entity_id":"0011","template":"chr_0001_alpha"},{"entity_id":null,"template":"chr_0002_beta"}]}""", -1);
        check(IdentityLegacyExporter.Lines(originalIds, 330).SequenceEqual(new[] {
            "[05:29:59.999] SQUAD size=2 members=[chr_0001_alpha_0011 chr_0002_beta_None]\n" }),
            "Squad export restores original identity representation and unresolved member");
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Identity leaked to text"), eventSink: events.Add);
        var attach = E("""{"type":"BattleOpSkillAttach","timestamp_ms":1793412000123,"skill_inst_id":100,"src_inst_id":11,"template_str_id":"chr_0001_alpha_skill"}""");
        bridge.Handle(attach); bridge.Handle(attach);
        bridge.Handle(E("""{"type":"SC_SELF_SCENE_INFO","timestamp_ms":1793412000123,"char_list":[{"battle_inst_id":11,"id":111,"templateid":"chr_0001_alpha"}]}"""));
        check(events.Select(item => item.Type).SequenceEqual(new[] { "actor_mapping", "squad" })
            && events.Select(item => item.Sequence).SequenceEqual(new long[] { 1, 2 }), "Business identity production keeps existing mapping deduplication and shared sequence");
        var malformed = Event("squad", """{"members":[{"entity_id":11,"template":"chr_0001_alpha"},{"entity_id":22,"template":"chr_0002_beta"}]}""");
        var members = ((EvidenceArray)malformed.Data.Get("members")).Items.ToArray();
        var bad = ((EvidenceObject)members[1]).Fields.ToDictionary(); bad["entity_id"] = new EvidenceInteger(22); members[1] = new EvidenceObject(bad);
        var fields = malformed.Data.Fields.ToDictionary(); fields["members"] = new EvidenceArray(members); malformed = malformed with { Data = new(fields) };
        var untouched = StructuredDamageSpecs.Stream();
        try { untouched.Accept(1, malformed); throw new InvalidOperationException("Malformed member accepted"); }
        catch (InvalidDataException) { check(untouched.PartyActorIds.Count == 0 && untouched.Loadouts.SquadActorKeys.Count == 0 && untouched.FirstContextMs is null, "All squad members validate before any state mutation"); }
    }
}
