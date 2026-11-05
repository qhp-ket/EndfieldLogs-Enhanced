using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class StaticArtsStrengthSpecs
{
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row,params (string Key,EvidenceValue Value)[] changes)
    {
        var fields=new Dictionary<string,EvidenceValue>(row.Fields,StringComparer.Ordinal);
        foreach(var (key,value) in changes) fields[key]=value;
        return new(fields);
    }
    public static void Run(Action<bool,string> check)
    {
        var fixture=JsonNode.Parse(File.ReadAllText(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../../../Fixtures/static-arts-strength.json"))))!;
        var shared=(EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        var catalog=(EvidenceObject)shared.Get("catalog");
        var weapons=((EvidenceObject)shared.Get("weapons")).Fields.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
        var numbers=((EvidenceObject)shared.Get("numbers")).Fields.ToDictionary(pair=>pair.Key,pair=>((EvidenceText)pair.Value).Value);
        StaticArtsStrengthDeriver deriver=new(catalog,weapons,numbers);
        var equipment=Obj("""
            {"source_type":"equip_baseline","source_id":"equip_a","source_slot":0,"attr_index":0,"enhance_level":0,
             "attr_type":87,"value":20,"evidence_kind":"official_EquipTable_attribute_zero_or_exact",
             "source_table_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
            """);
        var weapon=Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":101,"bb":{"arts":30}}]}""");
        var suit=Obj("""{"suit_id":"suit_a","suit_name":"suit name","active":true,"value":{"arts":40}}""");
        var all=Change(weapon,("suit_effects",new EvidenceArray([suit])),("equipment_baseline_attributes",new EvidenceArray([equipment])));
        var signature=EvidenceJsonSignature.Sorted(all);
        var result=deriver.Derive(all);
        check(result.Entries.Count==3 && result.Entries.Sum(entry=>((EvidenceReal)entry.Get("rate")).Value)==90
            && result.Entries.Select(entry=>((EvidenceText)entry.Get("source_type")).Value).SequenceEqual(["equip","equip_suit","weapon_skill"]),
            "Exact equipment, suit card and weapon card each contribute once in source processing order");
        check(result.Entries.All(entry=>entry.Get("attr_type") is EvidenceInteger { Value:var type } && type==87
            && entry.Get("zone") is EvidenceText { Value:"arts_strength" } && entry.Get("element") is EvidenceText { Value:"all" })
            && result.Entries[0].Get("source_slot") is EvidenceInteger { Value:var slot } && slot==0,
            "Arts entries carry their exact attribute, category, slot and declared provenance");
        var duplicate=deriver.Derive(Change(all,("equipment_baseline_attributes",new EvidenceArray([equipment,equipment]))));
        check(duplicate.Entries.Count==3 && duplicate.Loadout.Get("rdps_unresolved_static_multiplier_sources") is EvidenceNull,
            "Repeated identical source observations do not add another static contribution");
        var split=deriver.Derive(Change(all,("equipment_baseline_attributes",new EvidenceArray([equipment,Change(equipment,("source_slot",new EvidenceInteger(1)))]))));
        check(split.Entries.Count==4 && split.Entries.Sum(entry=>((EvidenceReal)entry.Get("rate")).Value)==110,
            "Equal values from separate proven equipment slots remain independent sources");
        var conflicted=deriver.Derive(Change(all,("equipment_baseline_attributes",new EvidenceArray([equipment,Change(equipment,("value",new EvidenceInteger(21)))])),
            ("rdps_unresolved_static_multiplier_sources",(EvidenceArray)EvidenceJson.Parse("""[{"reason":"existing"}]"""))));
        var blockers=(EvidenceArray)conflicted.Loadout.Get("rdps_unresolved_static_multiplier_sources");
        check(conflicted.Entries.Count==2 && blockers.Items.Count==2
            && ((EvidenceObject)blockers.Items[1]).Get("reason") is EvidenceText { Value:"conflicting_static_arts_strength_source" },
            "Conflicting values invalidate their entire source and append a blocker while preserving existing blockers");
        var renamed=deriver.Derive(Obj("""{"suit_effects":[{"suit_id":"suit_a","suit_name":"first","active":true,"value":{"arts":40}},{"suit_id":"suit_a","suit_name":"second","active":true,"value":{"arts":40}}]}"""));
        check(renamed.Entries is [var entry] && entry.Get("source_name") is EvidenceText { Value:"suit_a" },
            "A label-only disagreement deduplicates by exact provenance and falls back to the item identifier");
        var zero=deriver.Derive(Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":"101","bb":{"arts":0}}]}"""));
        check(zero.Entries.Count==0 && zero.Loadout.Get("rdps_unresolved_static_multiplier_sources") is EvidenceNull,
            "A proven zero is valid evidence without a positive contribution or a conflict blocker");
        check(deriver.Derive(Change(weapon,("weapon_source_skills",(EvidenceArray)EvidenceJson.Parse("""[{"skill_id":"skill_101","bb":{"arts":30}}]""")))).Entries.Count==0
            && deriver.Derive(Change(weapon,("weapon_template",new EvidenceText("wpn_other")))).Entries.Count==0,
            "Runtime-looking identities and a different weapon cannot replace the exact numeric and slot binding");
        var untrusted=new StaticArtsStrengthDeriver(Change(catalog,("decoder",Obj("{}"))),weapons,numbers).Derive(all);
        check(untrusted.Entries.Count==1 && untrusted.Entries[0].Get("source_type") is EvidenceText { Value:"equip" },
            "An unbound card catalog contributes no card points while independently proven equipment remains usable");
        var inactive=Change(all,("suit_effects",new EvidenceArray([Change(suit,("active",new EvidenceInteger(1)))])),
            ("equipment_baseline_attributes",new EvidenceArray([Change(equipment,("enhance_level",new EvidenceBoolean(true)))])));
        check(deriver.Derive(inactive).Entries is [var only] && only.Get("source_type") is EvidenceText { Value:"weapon_skill" },
            "Suit activation requires true and slot enhancement requires an exact integer rather than a boolean");
        check(signature==EvidenceJsonSignature.Sorted(all) && !ReferenceEquals(result.Loadout.Get("suit_effects"),all.Get("suit_effects"))
            && deriver.Derive(all).Entries.Count==3,
            "Enrichment owns the loadout and repeated calls neither alter input evidence nor retain prior candidates");

        var root=Path.Combine(Path.GetTempPath(),"endfield-arts-factory-"+Guid.NewGuid().ToString("N"));
        var directory=Path.Combine(root,"data/local_static/skill");
        Directory.CreateDirectory(directory);
        try
        {
            var path=Path.Combine(directory,"item_arts_strength_catalog.json");
            File.WriteAllText(path,JsonNode.Parse(fixture["resources_json"]!.GetValue<string>())!["catalog"]!.ToJsonString());
            var loaded=StaticArtsStrengthDeriver.Load(new(root));
            File.WriteAllText(path,"{}");
            var produced=loaded.Derive(Change(Obj("{}"),("suit_effects",new EvidenceArray([suit]))));
            check(produced.Entries is [var observed] && observed.Get("rate") is EvidenceReal { Value:40 }
                && StaticArtsStrengthDeriver.Load(new(root)).Derive(all).Entries.Count==1,
                "Production construction loads the reviewed card catalog and keeps a stable resource view for a report");
        }
        finally { Directory.Delete(root,recursive:true); }
    }
}
