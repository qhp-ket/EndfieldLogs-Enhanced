using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Runtime.Tracing;

internal static class StructuredLoadoutSpecs
{
    private const string Owner = "chr_0001_alpha";
    private static EvidenceObject E(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    private static TraceEvent Event(string type, EvidenceObject data, long time = 1000)
    {
        var projected = TraceValueProjection.Capture(data);
        var fields = ((EvidenceObject)projected.Value).Fields.ToDictionary(); fields["legacy_layout"] = projected.Layout;
        return (TraceEvent)TraceJsonl.Parse(TraceJsonl.Serialize(new TraceEvent(1, time, type, new(fields), E("{}"))), header: false);
    }
    private static EvidenceObject Row(EvidenceObject? extra = null)
    {
        var fields = E("""{"char":"chr_0001_alpha","slot":0,"char_inst_id":11,"weapon_inst_id":91,"weapon_template":"wpn_test"}""").Fields.ToDictionary();
        foreach (var (key, value) in extra?.Fields ?? E("{}").Fields) fields[key] = value;
        return new(fields);
    }
    private static TraceEvent Snapshot(EvidenceObject? extra = null, bool stats = false, long time = 1000) =>
        Event(stats ? "loadout_stats" : "loadout_slot", LoadoutWire.Data(Row(extra), stats), time);
    private static TraceEvent Group(string reason = "SC_SELF_SCENE_INFO")
    {
        var fields = E("""{"slot_count":1,"member_count":1,"roster":[{"entity_id":11}]}""").Fields.ToDictionary();
        fields["reason"] = new EvidenceText(reason); return Event("loadout_group", new(fields));
    }
    private static LoadoutObservations Stream(bool gemRules = false)
    {
        SkillIdentityCatalog identities = new(new Dictionary<string, string>(), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
        var rules = new WeaponRefinementRules(gemRules ? new Dictionary<string, EvidenceObject> { ["wpn_test"] = E("""{"mainSkillId":"main","mainSkillNumId":"7","mainSkillGemTermNumId":66,"supportedSkillLevels":[1,2,3,4,5],"mainSkillBounds":[{"lowerBound":1,"upperBound":4}],"refineBonusBounds":{"0":{"lowerBound":0,"upperBound":0},"1":{"lowerBound":1,"upperBound":1}}}""") } : new Dictionary<string, EvidenceObject>());
        return new(new(new Dictionary<string, EvidenceObject> { ["wpn_test"] = E("""{"base_atk_values":[100,120]}""") },
            new Dictionary<string, EvidenceObject>(), new Dictionary<string, EvidenceObject>(), rules, identities, key => key), identities);
    }
    public static void Run(Action<bool, string> check)
    {
        var state = Stream(); StructuredLoadout.Accept(Group(), 1, state);
        var item = Snapshot(E("""{"weapon_inst_id":"00091","weapon_lv":0,"refine":null,"char_level":0,"equips":"{[0]=piece|lv=[0]=2}","equip_suit":"{[suit_a]=3}","skill_int_ids":"4,5","equipment_snapshot_complete":true,"unresolved_equip_inst_ids":["00123"]}"""));
        StructuredLoadout.Accept(item, 2, state);
        var current = state.Party.Loadouts[Owner];
        check(current.Get("weapon_inst_id") is EvidenceText { Value: "91" }
            && new[] { "weapon_level", "weapon_base_atk", "character_level", "weapon_refine" }.All(key => !current.Fields.ContainsKey(key)),
            "Typed equipment keeps unknown levels absent instead of manufacturing level-one attack or refinement");
        check(current.Get("equipment_snapshot_complete") is EvidenceBoolean { Value: true }
            && EvidenceJson.PythonEquals(current.Get("unresolved_equip_inst_ids"), EvidenceJson.Parse("""["123"]"""))
            && ((EvidenceObject)((EvidenceArray)current.Get("equips")).Items[0]).Get("item_id") is EvidenceText { Value: "piece" }
            && EvidenceJson.PythonEquals(current.Get("skill_int_ids"), EvidenceJson.Parse("""["4","5"]""")),
            "Typed equipment consumes native fields with canonical unresolved identities");
        check(state.Party.ActiveSuits[Owner].SetEquals(["suit_a"]) && state.SquadActorKeys.Count == 0
            && state.CurrentGroup is { LineNumber: 1, TimestampMs: 1000 },
            "Loadout activity and historical indices do not invent squad authority");
        foreach (var mode in new[] { "missing", "partial", "complete" })
        {
            var sample = Stream();
            StructuredLoadout.Accept(Snapshot(E("""{"equips":"{[0]=piece}","equipment_snapshot_complete":true}""")), 1, sample);
            var before = EvidenceJsonSignature.Sorted(sample.Groups[0].Rows[Owner]);
            var fields = E("""{"equips":"{}"}""").Fields.ToDictionary();
            if (mode != "missing") fields["equipment_snapshot_complete"] = new EvidenceBoolean(mode == "complete");
            StructuredLoadout.Accept(Snapshot(new(fields), time: 2000), 2, sample);
            check(((EvidenceArray)sample.Party.Loadouts[Owner].Get("equips")).Items.Count == (mode == "complete" ? 0 : 1)
                && EvidenceJsonSignature.Sorted(sample.Groups[0].Rows[Owner]) == before,
                "Only complete empty equipment clears earlier pieces; old groups stay unchanged: " + mode);
        }
        var swapped = Stream();
        swapped.Party.Loadouts[Owner] = E("""{"character_key":"chr_0001_alpha","weapon_inst_id":"91","weapon_template":"wpn_old","weapon_refine":5,"weapon_refine_source":"source_skill","gem_template":"old","gem_terms":{"rate":1},"weapon_source_skills":[{"skill_id":"old","bb":{"scale":0.5}}]}""");
        StructuredLoadout.Accept(Snapshot(E("""{"weapon_template":"wpn_old"}""")), 1, swapped);
        var old = EvidenceJsonSignature.Sorted(swapped.Groups[0].Rows[Owner]);
        StructuredLoadout.Accept(Snapshot(E("""{"weapon_inst_id":92,"weapon_template":"wpn_new"}"""), time: 2000), 2, swapped);
        var replacement = swapped.Party.Loadouts[Owner];
        check(replacement.Get("weapon_inst_id") is EvidenceText { Value: "92" } && replacement.Get("weapon_refine") is EvidenceNull
            && replacement.Get("gem_template") is EvidenceNull && replacement.Get("gem_terms") is EvidenceObject { Fields.Count: 0 }
            && replacement.Get("weapon_source_skills") is EvidenceArray { Items.Count: 0 }
            && EvidenceJsonSignature.Sorted(swapped.Groups[0].Rows[Owner]) == old,
            "Replacing weapon instance clears stale refinement, gem and source skills without rewriting history");
        foreach (var mode in new[] { "exact", "wrong_reason", "later_timestamp", "other_weapon", "no_gem", "no_weapon", "duplicate_term", "malformed" })
        {
            var sample = Stream(gemRules: true);
            StructuredLoadout.Accept(Group(mode == "wrong_reason" ? "packet" : "SC_SELF_SCENE_INFO"), 1, sample);
            var fields = E("""{"weapon_source_skills":"7:level=4:potentialLv=3:bb={rate=0.123456789}","attached_gem":42,"gem_weapon_id":91,"gem_template":71,"gem_terms":"66:label@cost3"}""").Fields.ToDictionary();
            if (mode == "other_weapon") fields["gem_weapon_id"] = new EvidenceInteger(92);
            if (mode == "no_gem") fields["attached_gem"] = new EvidenceInteger(0);
            if (mode == "no_weapon") fields["weapon_inst_id"] = new EvidenceInteger(0);
            if (mode == "duplicate_term") fields["gem_terms"] = new EvidenceText("66:label@cost3,66:label@cost1");
            if (mode == "malformed") fields["gem_terms"] = new EvidenceText("66:broken");
            StructuredLoadout.Accept(Snapshot(new(fields), stats: true, time: mode == "later_timestamp" ? 2000 : 1000), 2, sample);
            var row = sample.Party.Loadouts[Owner];
            check(mode == "exact" ? row.Get("weapon_refine") is EvidenceInteger { Value.IsZero: true } : !row.Fields.ContainsKey("weapon_refine"),
                "Bound gem refinement requires matching timestamp, reason, instances and unambiguous terms: " + mode);
        }
        var overridden = Stream();
        overridden.WeaponOverrides[Owner] = E("""{"weapon_template":"wpn_override","weapon_inst_id":"93"}""");
        StructuredLoadout.Accept(Snapshot(), 1, overridden);
        check(overridden.Party.ActiveWeapons[Owner] == "wpn_override" && overridden.Party.Loadouts[Owner].Get("weapon_inst_id") is EvidenceText { Value: "93" }
            && overridden.CurrentGroup!.Rows[Owner].Get("weapon_template") is EvidenceText { Value: "wpn_override" },
            "Authoritative override applies to current row, historical group and active weapon");
        var raw = Snapshot(E("""{"weapon_inst_id":9007199254740993,"weapon_base_atk":123.456789,"weapon_base_atk_lv1":0,"gem_terms":"66:label@cost3"}"""), stats: true, time: -1);
        var precision = Stream(); StructuredLoadout.Accept(raw, 1, precision);
        check(!raw.Data.Fields.ContainsKey("weapon_base_atk_max") && raw.Data.Get("weapon_base_atk") is EvidenceReal { Value: 123.456789 }
            && raw.Data.Get("weapon_base_atk_lv1") is EvidenceInteger { Value.IsZero: true }
            && !precision.Party.Loadouts[Owner].Fields.ContainsKey("weapon_base_atk"),
            "Raw decimal precision and missing/zero evidence survive while legacy analysis keeps integer-only attack projection");
        check(LoadoutLegacyExporter.Lines(raw, 330).SequenceEqual(new[] {
            "[05:29:59.999] LOADOUT_STATS slot=0 char=chr_0001_alpha weaponInstId=9007199254740993 weaponTemplate=wpn_test weaponSync=missing weaponBaseAtk=123.456789 weaponBaseAtkLv1=0 weaponBaseAtkMax=unknown weaponRefineStatsSource=unknown weaponRefineStats={} weaponSourceSkills={} gemInstId=0 gemWeaponId=0 gemTemplate=0 gemTerms={66:label@cost3}\n" }),
            "Independent loadout export preserves raw precision, wide identities, missing values, timezone and final newline");
        var clean = StructuredDamageSpecs.Stream();
        var broken = Snapshot(E("""{"unresolved_equip_inst_ids":[11,22]}"""));
        var unplaced = ((EvidenceArray)broken.Data.Get("unplaced_equipment")).Items.ToArray();
        unplaced[1] = E("""{"entity_id":22}""");
        var brokenFields = broken.Data.Fields.ToDictionary(); brokenFields["unplaced_equipment"] = new EvidenceArray(unplaced);
        broken = broken with { Data = new(brokenFields) };
        try { clean.Accept(1, broken); throw new InvalidOperationException("Invalid loadout accepted"); }
        catch (InvalidDataException) { check(clean.Loadouts.Party.Loadouts.Count == 0 && clean.Loadouts.Groups.Count == 0 && clean.FirstContextMs is null,
            "Validate later unresolved identities before mutating any equipment or stream context"); }
        List<TraceEvent> events = [];
        TraceBridge bridge = new(_ => throw new InvalidOperationException("Equipment leaked to text"), eventSink: events.Add);
        var origin = E("""{"type":"LOADOUT","timestamp_ms":1793412000123,"reason":"SC_SELF_SCENE_INFO","rows":[{"char":"chr_0001_alpha","slot":0,"char_inst_id":11,"weapon_inst_id":91,"weapon_template":"wpn_test","weapon_lv":0,"equipment_snapshot_complete":false},null,{"slot":1}]}""");
        bridge.Handle(origin);
        check(events.Select(row => row.Type).SequenceEqual(["squad","loadout_group","loadout_slot","loadout_stats","loadout_slot","loadout_stats"])
            && events.Select(row => row.Sequence).SequenceEqual(Enumerable.Range(1,6).Select(value => (long)value))
            && EvidenceJson.PythonEquals(events[1].Data.Get("slot_count"), new EvidenceInteger(3))
            && EvidenceJson.PythonEquals(events[1].Data.Get("member_count"), new EvidenceInteger(3))
            && EvidenceJson.PythonEquals(events[1].Data.Get("roster"), EvidenceJson.Parse("""[{"entity_id":"11"}]"""))
            && events[2].Data.Get("equipment_snapshot_complete") is EvidenceBoolean { Value: false } && !events[2].Data.Fields.ContainsKey("equips"),
            "Business emission preserves sparse roster count, absence and false flags with independent ordered slot/stat events");
    }
}
