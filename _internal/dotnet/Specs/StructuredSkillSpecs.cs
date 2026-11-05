using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredSkillSpecs
{
    private const string Owner = "chr_0001_alpha";
    private static EvidenceObject E(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    private static TraceEvent Event(string kind, EvidenceObject data, long time = 1000)
    {
        var projected = TraceValueProjection.Capture(data);
        var fields = ((EvidenceObject)projected.Value).Fields.ToDictionary(); fields["legacy_layout"] = projected.Layout;
        return (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, time, kind, new(fields), E("{}"))), header: false);
    }
    private static TraceEvent Cast(string phase = "start", long time = 1000, EvidenceObject? extra = null)
    {
        var fields = E("""{"skill_inst_id":71,"owner_id":11,"owner":"chr_0001_alpha","skill":"chr_0001_alpha_skill","skill_source":"CharacterSkill"}""").Fields.ToDictionary();
        fields["phase"] = new EvidenceText(phase);
        foreach (var (key, value) in extra?.Fields ?? E("{}").Fields) fields[key] = value;
        return Event("skill_cast", new(fields), time);
    }
    public static void Run(Action<bool, string> check)
    {
        SkillObservationState skills = new(); PacketObservationState packets = new();
        StructuredSkill.Accept(Cast(extra: E("""{"skill":"skill_7"}""")), 1, skills, packets);
        check(skills.FirstPartyActionMs is null, "Unresolved generic runtime casts do not start the party action clock");
        var first = skills.Casts[0];
        StructuredSkill.Accept(Cast(time: 2000), 2, skills, packets);
        var replacement = skills.Casts[1];
        StructuredSkill.Accept(Cast("end", 1500, E("""{"client_tick_ms":999999}""")), 3, skills, packets);
        check(first.EndTimestampMs is null && replacement.EndTimestampMs == 1500 && replacement.EndLineNumber == 3
            && skills.ActiveCastsByInstance.Count == 0 && skills.FirstPartyActionMs == 2000,
            "A repeated instance ends the latest cast with the observed capture time, including late timestamps");
        StructuredSkill.Accept(Cast("end", 3000, E("""{"skill_inst_id":72}""")), 4, skills, packets);
        check(skills.Casts.Count == 2, "An unmatched end does not manufacture a cast");
        SkillObservationState recent = new();
        for (var index = 0; index < 20; index++)
        {
            var fields = E("""{"owner":null}""").Fields.ToDictionary(); fields["skill_inst_id"] = new EvidenceInteger(index + 1);
            StructuredSkill.Accept(Cast(time: 1000 + index, extra: new(fields)), index + 1, recent, packets);
        }
        check(recent.Casts.Count == 20 && recent.ActiveCastsByInstance.Count == 20 && recent.RecentCastsByCharacter[Owner].Count == 16
            && recent.RecentCastsByCharacter[Owner][0].TimestampMs == 1004 && recent.FirstPartyActionMs == 1000,
            "Recent cast retention stays bounded and owner fallback uses explicit character skill identity");
        foreach (var (reason, delta, gain) in new (string, EvidenceValue, bool)[] {
            ("AddValue",new EvidenceReal(1.23456789),true),("AddValue",new EvidenceInteger(0),false),
            ("AddValue",new EvidenceInteger(-1),false),("Consume",new EvidenceInteger(1),false),
            ("AddValue",new EvidenceReal(double.PositiveInfinity),false),("AddValue",EvidenceNull.Value,false) })
        {
            var fields = E("""{"owner":"chr_0001_alpha","owner_id":9007199254740993,"value":12.3456789,"recovery_speed":null,"client_tick_ms":0}""").Fields.ToDictionary();
            fields["reason"] = new EvidenceText(reason); fields["delta"] = delta;
            SkillObservationState current = new(); var item = Event("atb", new(fields));
            StructuredSkill.Accept(item, 7, current, packets); var row = current.AtbObservations.Single();
            check(item.Data.Get("value") is EvidenceReal { Value: 12.3456789 } && row.Value == 12.3457
                && row.OwnerActorId == "9007199254740993" && row.RecoverySpeed is null && row.ClientTickMs == 0
                && (current.AtbGainMsByCharacter.Count > 0) == gain,
                "ATB retains raw precision, observed-only values and positive finite AddValue attribution: " + reason + "/" + PythonDisplay.String(delta));
        }
        foreach (var (type, source, original, accepted) in new (string, string?, string?, bool)[] {
            ("PoiseDamage",null,"skill_a",true),("PoiseDamage","skill_b","skill_a",true),
            ("PoiseDamage",null,null,false),("Recover","skill_a",null,false) })
        {
            var fields = E("""{"source_int":0,"original_source_int":42,"value":1.23456789,"current_value":0}""").Fields.ToDictionary();
            fields["modify_type"] = new EvidenceText(type); fields["source"] = source is null ? EvidenceNull.Value : new EvidenceText(source);
            fields["original_source"] = original is null ? EvidenceNull.Value : new EvidenceText(original);
            PacketObservationState current = new(); StructuredSkill.Accept(Event("poise", new(fields)), 9, skills, current);
            check((current.PoiseDamage.Count > 0) == accepted && (!accepted || current.PoiseDamage[0] is {
                SourceInteger: null, OriginalSourceInteger: not null, Value: 1.23457, CurrentValue: 0 } row
                && row.OriginalSourceInteger == 42 && row.Source == (source ?? original)),
                "Poise uses explicit or original source without inventing target identity: " + type + "/" + source);
        }
        foreach (var field in new[] { "phase", "skill_inst_id", "skill_source" })
        {
            var clean = StructuredDamageSpecs.Stream(); var original = Cast(); var fields = original.Data.Fields.ToDictionary();
            fields[field] = field == "phase" ? new EvidenceText("invalid") : new EvidenceInteger(71);
            try { clean.Accept(1, original with { Data = new(fields) }); throw new InvalidOperationException("Invalid skill accepted"); }
            catch (InvalidDataException) { check(clean.Skills.Casts.Count == 0 && clean.FirstContextMs is null, "Reject invalid skill fields before state mutation: " + field); }
        }
        var exported = Cast("end", -1, E("""{"skill_inst_id":9007199254740993,"owner_id":"0011","operation_seq":0,"client_tick_ms":0}"""));
        check(exported.Data.Get("owner_id") is EvidenceText { Value: "11" } && exported.Data.Get("skill_inst_id") is EvidenceText { Value: "9007199254740993" }
            && SkillLegacyExporter.Lines(exported, 330).SequenceEqual(new[] {
                "[05:29:59.999] SKILL_CAST_END seq=0 endMs=0 inst=9007199254740993 owner=chr_0001_alpha ownerId=0011 skill=chr_0001_alpha_skill skillSource=CharacterSkill\n" }),
            "Independent cast export preserves original end-owner spelling, wide identities, timezone and newline");
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Skill/resource leaked to text"), eventSink: events.Add);
        bridge.Handle(E("""{"type":"BattleOpSkillAttach","timestamp_ms":1000,"skill_inst_id":71,"src_inst_id":11,"template_str_id":"chr_0001_alpha_skill"}"""));
        bridge.Handle(E("""{"type":"BattleOpSkillStartCast","timestamp_ms":1100,"skill_inst_id":71,"owner_id":11}"""));
        bridge.Handle(E("""{"type":"BattleOpUpdateAtbInfo","timestamp_ms":1200,"owner_id":11,"reason":"AddValue","atb_value":12.3456789,"delta_value":0}"""));
        bridge.Handle(E("""{"type":"BattleOpModifyPoiseValue","timestamp_ms":1300,"modify_type":"PoiseDamage","value":0.123456789,"cur_poise_value":0}"""));
        check(events.Select(item => item.Type).SequenceEqual(["actor_mapping","skill_cast","atb","poise"])
            && events.Select(item => item.Sequence).SequenceEqual(new long[] {1,2,3,4})
            && events[2].Data.Get("value") is EvidenceReal { Value: 12.3456789 } && !events[2].Data.Fields.ContainsKey("recovery_speed")
            && events[3].Data.Get("current_value") is EvidenceInteger { Value.IsZero: true } && !events[3].Data.Fields.ContainsKey("attacker_id"),
            "Business skill/resource emission shares sequence while preserving original precision, zero and missing fields");
    }
}
