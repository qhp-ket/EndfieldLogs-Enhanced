using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredCharacterSkillsSpecs
{
    private static EvidenceObject E(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    private static TraceEvent Event(string data, long timestamp = 1793412000123) => Event(E(data), timestamp);
    private static TraceEvent Event(EvidenceObject data, long timestamp = 1793412000123)
    {
        var projection = TraceValueProjection.Capture(data);
        var fields = ((EvidenceObject)projection.Value).Fields.ToDictionary(); fields["legacy_layout"] = projection.Layout;
        return (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, timestamp, "character_skills", new(fields), E("{}"))), header: false);
    }
    public static void Run(Action<bool, string> check)
    {
        const string owner = "chr_0001_alpha";
        SkillIdentityCatalog identities = new(new Dictionary<string, string> { ["42"] = "canonical" },
            new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
        var rules = new WeaponRefinementRules(new Dictionary<string, EvidenceObject> { ["wpn_test"] = E("""{"mainSkillId":"wpn_main","skillLevelToRefine":{"9":5}}""") });
        LoadoutObservations Stream() => new(new(new Dictionary<string, EvidenceObject>(), new Dictionary<string, EvidenceObject>(),
            new Dictionary<string, EvidenceObject>(), rules, identities, key => key), identities);
        var state = Stream();
        var item = Event("""{"template":"chr_0001_alpha","entity_id":11,"skills":[{"skill":"42","level":3},{"skill":"canonical","level":4},{"skill":"canonical","level":3},{"skill":"keep","level":"2.0"},{"skill":"zero","level":0},{"skill":"negative","level":-1},{"skill":"bad","level":2.5},{"skill":"unknown","level":null},{"skill":"99999","level":7}]}""");
        StructuredCharacterSkills.Accept(item, 4, state);
        check(state.CharacterSkills[owner].Count == 1 && state.CharacterSkills[owner]["keep"] == 2,
            "Typed skill fields retain positive exact levels and discard conflicting canonical aliases");
        var later = Event("""{"template":"chr_0001_alpha","entity_id":11,"skills":[{"skill":"invalid","level":0}]}""");
        StructuredCharacterSkills.Accept(later, 5, state);
        check(state.CharacterSkills[owner].Count == 1 && state.CharacterSkills[owner]["keep"] == 2,
            "All-invalid skill evidence does not erase previous levels");
        foreach (var mode in new[] { "exact", "wrong_owner", "duplicate_owner", "missing_instance", "wrong_character", "wrong_weapon", "ambiguous", "conflict", "known_refine" })
        {
            var current = Stream(); current.SquadActorKeys[mode == "wrong_owner" ? "12" : "11"] = owner;
            if (mode == "duplicate_owner") current.SquadActorKeys["12"] = owner;
            var original = E("""{"character_key":"chr_0001_alpha","weapon_inst_id":"91","weapon_template":"wpn_test","weapon_refine":null,"nested":{"evidence":[1]}}""").Fields.ToDictionary();
            if (mode == "missing_instance") original["weapon_inst_id"] = EvidenceNull.Value;
            if (mode == "wrong_character") original["character_key"] = new EvidenceText("chr_other");
            if (mode == "wrong_weapon") original["weapon_template"] = new EvidenceText("unknown");
            if (mode == "known_refine") original["weapon_refine"] = new EvidenceInteger(0);
            current.Party.Loadouts[owner] = new(original);
            var before = EvidenceJsonSignature.Sorted(current.Party.Loadouts[owner]);
            var raw = E("""{"template":"chr_0001_alpha","entity_id":11,"skills":[{"skill":"wpn_main","level":9}]}""");
            var levels = ((EvidenceArray)raw.Get("skills")).Items.ToList();
            if (mode == "ambiguous") levels[0] = E("""{"skill":"wpn_main","level":8}""");
            if (mode == "conflict") levels.Add(E("""{"skill":"wpn_main","level":1}"""));
            var fields = raw.Fields.ToDictionary(); fields["skills"] = new EvidenceArray(levels);
            var observation = Event(new EvidenceObject(fields));
            StructuredCharacterSkills.Accept(observation, 7, current);
            if (mode == "exact")
            {
                var accepted = current.Party.Loadouts[owner];
                var expected = E("""{"source":"CHAR_SKILLS","owner_id":"11","weapon_inst_id":"91","skill_id":"wpn_main","level":9}""");
                check(accepted.Get("weapon_refine") is EvidenceInteger refine && refine.Value == 5
                    && EvidenceJson.PythonEquals(accepted.Get("weapon_refine_evidence"), expected)
                    && current.CurrentGroup is { Reason: "CHAR_SKILLS", LineNumber: 7, TimestampMs: 1793412000123 },
                    "Typed skill evidence completes only uniquely bound, unknown weapon refinement");
                check(!ReferenceEquals(accepted.Get("nested"), current.CurrentGroup!.Rows[owner].Get("nested")),
                    "Refinement group owns independent nested historical evidence");
            }
            else check(EvidenceJsonSignature.Sorted(current.Party.Loadouts[owner]) == before && current.Groups.Count == 0,
                "Refinement retains existing authority checks: " + mode);
        }
        var exported = Event("""{"template":"chr_0001_alpha","entity_id":9007199254740993,"skills":[{"skill":"skill_a","level":0},{"skill":"skill_a","level":2.0},{"skill":"unresolved","level":"bad"}]}""", -1);
        check(IdentityLegacyExporter.Lines(exported, 330).SequenceEqual(new[] {
            "[05:29:59.999] CHAR_SKILLS owner=chr_0001_alpha ownerId=9007199254740993 count=3 skills=[skill_a:0 skill_a:2.0 unresolved:bad]\n" }),
            "Independent skill export retains order, original numeric representation, wide owner and original timezone");
        var broken = Event("""{"template":"chr_0001_alpha","entity_id":11,"skills":[{"skill":"first","level":3},{"skill":"later"}]}""");
        var clean = StructuredDamageSpecs.Stream();
        try { clean.Accept(1, broken); throw new InvalidOperationException("Invalid skill accepted"); }
        catch (InvalidDataException) { check(clean.Loadouts.CharacterSkills.Count == 0 && clean.FirstContextMs is null, "Validate all skills before mutating stream state"); }
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Skill event leaked to text"), eventSink: events.Add);
        var origin = E("""{"type":"SC_SELF_SCENE_INFO_SKILLS","timestamp_ms":1793412000123,"owner_inst_id":11,"owner_templateid":"chr_0001_alpha","skills":[{"skill_inst_id":71,"template_str_id":"chr_0001_alpha_skill","level":3},{"skill_inst_id":72,"template_str_id":"chr_0001_alpha_ult"}]}""");
        bridge.Handle(origin); bridge.Handle(origin);
        check(events is [{ Type: "character_skills", Sequence: 1 }] && ((EvidenceArray)events[0].Data.Get("skills")).Items.Count == 1,
            "Business skill emission keeps deduplication and skips missing levels");
    }
}
