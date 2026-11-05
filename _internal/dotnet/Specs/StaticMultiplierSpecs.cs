using System.Text.Json.Nodes;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class StaticMultiplierSpecs
{
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row,params (string Key,EvidenceValue Value)[] changes)
    {
        var fields=new Dictionary<string,EvidenceValue>(row.Fields,StringComparer.Ordinal);
        foreach(var (key,value) in changes) fields[key]=value;
        return new(fields);
    }
    private static EvidenceArray Array(string json)=>(EvidenceArray)EvidenceJson.Parse(json);
    private static EvidenceArray Baseline(StaticMultiplierResult result)=>(EvidenceArray)result.Loadout.Get("equipment_baseline_attributes");
    private static bool Blocked(StaticMultiplierResult result,string reason)=>((EvidenceArray)result.Loadout.Get("rdps_unresolved_static_multiplier_sources"))
        .Items.OfType<EvidenceObject>().Any(row=>row.Get("reason") is EvidenceText text && text.Value==reason);

    public static void Run(Action<bool,string> check)
    {
        var fixture=JsonNode.Parse(File.ReadAllText(Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"../../../Fixtures/static-multipliers.json"))))!;
        var resources=(EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>());
        var equipment=((EvidenceObject)resources.Get("equipment")).Fields.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
        var weapons=((EvidenceObject)resources.Get("weapons")).Fields.ToDictionary(pair=>pair.Key,pair=>(EvidenceObject)pair.Value);
        var numbers=((EvidenceObject)resources.Get("numbers")).Fields.ToDictionary(pair=>pair.Key,pair=>((EvidenceText)pair.Value).Value);
        var catalog=(EvidenceObject)resources.Get("catalog");
        StaticMultiplierDeriver Deriver(EvidenceObject? piece=null,EvidenceObject? weapon=null,EvidenceObject? cards=null)=>new(
            piece is null ? equipment : new Dictionary<string,EvidenceObject> { ["equip_a"]=piece },
            weapon is null ? weapons : new Dictionary<string,EvidenceObject> { ["wpn_a"]=weapon },numbers,cards ?? catalog);
        var deriver=Deriver();
        var row=Obj("""{"equips":[{"item_id":"equip_a","slot":0,"enhance_levels":[{"index":0,"level":1}],"stats":[{"value":"unknown"}]}]}""");
        var exact=deriver.Derive(row);
        check(exact.Entries is [var skill] && skill.Get("rate") is EvidenceReal { Value:0.2 }
            && skill.Get("attr_type") is EvidenceInteger { Value:var type } && type==32,
            "An exact enhancement selects its skill damage rate instead of inferring from display text");
        var complete=Obj("""{"equipment_snapshot_complete":true,"equips":[{"item_id":"equip_a","slot":0,"stats":[{"value":"unknown"}]}]}""");
        var defaulted=deriver.Derive(complete);
        check(defaulted.Entries is [var first] && first.Get("rate") is EvidenceReal { Value:0.1 }
            && first.Get("enhance_level") is EvidenceInteger { Value:var level } && level==0,
            "A complete snapshot supplies level zero for a missing enhancement and retains that evidence");
        var piece=equipment["equip_a"];
        var invariant=Deriver(Change(piece,("attribute_modifiers",Array("""[{"attrIndex":0,"attrType":32,"modifierType":5,"modifyAttributeType":0,"attrValues":[0.2,0.2]}]"""))))
            .Derive(Obj("""{"equips":[{"item_id":"equip_a","slot":0}]}"""));
        check(invariant.Entries is [var independent] && independent.Get("rate") is EvidenceReal { Value:0.2 }
            && independent.Get("enhance_level") is EvidenceNull,
            "An invariant table proves a rate while the unobserved enhancement remains unknown");
        var conflict=deriver.Derive(Obj("""{"equips":[{"item_id":"equip_a","slot":0,"enhance_levels":[{"index":0,"level":0},{"index":0,"level":1}]}]}"""));
        check(conflict.Entries.Count==0 && Blocked(conflict,"missing_or_conflicting_equipment_enhancement"),
            "Conflicting enhancement observations reject that attribute and preserve an unresolved source");
        var two=deriver.Derive(Obj("""{"equipment_snapshot_complete":true,"equips":[{"item_id":"equip_a","slot":0},{"item_id":"equip_a","slot":1}]}"""));
        var duplicates=deriver.Derive(Obj("""{"equipment_snapshot_complete":true,"equips":[{"item_id":"equip_a","slot":0},{"item_id":"equip_a","slot":true}]}"""));
        var sameSlot=deriver.Derive(Obj("""{"equipment_snapshot_complete":true,"equips":[{"item_id":"equip_a","slot":1},{"item_id":"equip_a","slot":true}]}"""));
        check(two.Entries.Count==2 && duplicates.Entries.Count==1 && sameSlot.Entries.Count==0
            && Blocked(sameSlot,"missing_or_conflicting_equipment_attribute_evidence"),
            "Separate exact slots contribute separately; boolean slot aliases invalidate only the colliding integer slot");
        var mixed=Deriver(Change(piece,("attribute_modifiers",Array("""
            [{"attrIndex":0,"attrType":2,"modifierType":7,"modifyAttributeType":0,"attrValues":[25]},
             {"attrIndex":1,"attrType":2,"modifierType":6,"modifyAttributeType":0,"attrValues":[0.1]},
             {"attrIndex":2,"attrType":87,"modifierType":5,"modifyAttributeType":0,"attrValues":[30]}]
            """)))).Derive(Change(complete,("equips",Array("""[{"item_id":"equip_a","slot":0,"stats":[{"value":"unknown"},{"value":99},{"value":"unknown"}]}]"""))));
        var baseline=Baseline(mixed).Items.OfType<EvidenceObject>().ToArray();
        var display=(EvidenceArray)((EvidenceObject)((EvidenceArray)mixed.Loadout.Get("equips")).Items[0]).Get("stats");
        check(mixed.Entries is [var percent] && percent.Get("zone") is EvidenceText { Value:"atk" }
            && percent.Get("rate") is EvidenceReal { Value:0.1 } && baseline.Length==2
            && baseline[0].Get("modifier_type") is EvidenceInteger { Value:var stage } && stage==7
            && baseline[0].Get("value") is EvidenceReal { Value:25 } && baseline[1].Get("modifier_type") is EvidenceNull,
            "Flat attack, percent attack and arts points remain separate evidence with their original stage fields");
        check(((EvidenceObject)display.Items[0]).Get("value") is EvidenceReal { Value:25 }
            && ((EvidenceObject)display.Items[1]).Get("value") is EvidenceInteger { Value:var observed } && observed==99,
            "Exact enrichment fills an unknown display value without replacing an existing observation");
        var arts=new StaticArtsStrengthDeriver(Obj("{}"),weapons,numbers).Derive(mixed.Loadout);
        check(arts.Entries is [var points] && points.Get("rate") is EvidenceReal { Value:30 },
            "Equipment arts evidence produced by the multiplier stage feeds the real arts derivation stage");

        var attackMeta=Obj("""{"weapon_skill_ids":["wpn_sp_attr_atk_high"]}""");
        var attack=Deriver(weapon:attackMeta).Derive(Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":102,"bb":{"atk":0.3}}]}"""));
        check(attack.Entries is [var basic] && basic.Get("rate") is EvidenceReal { Value:0.3 }
            && basic.Get("evidence_kind") is EvidenceText { Value:"official_WeaponSkill_text_basic_atk" }
            && !Blocked(attack,"unmodeled_weapon_static_semantics"),
            "A declared canonical basic attack skill is modeled once with its exact provenance label");
        var weaponRow=Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":101,"bb":{"damage":0.2}}]}""");
        var typed=deriver.Derive(weaponRow);
        check(typed.Entries is [var card] && card.Get("attr_type") is EvidenceInteger { Value:var attr } && attr==32
            && card.Get("rate") is EvidenceReal { Value:0.2 } && !Blocked(typed,"unmodeled_weapon_static_semantics"),
            "A version-bound damage card consumes only its exact declared weapon slot and blackboard field");
        var unbound=Deriver(cards:Change(catalog,("decoder",Obj("{}")))).Derive(weaponRow);
        check(unbound.Entries.Count==0 && Blocked(unbound,"unmodeled_weapon_static_semantics"),
            "A card without the current decoder binding cannot authorize a static rate");
        var badStage=(EvidenceObject)((EvidenceObject)EvidenceJson.Parse(fixture["resources_json"]!.GetValue<string>())).Get("catalog");
        var definition=(EvidenceObject)((EvidenceArray)badStage.Get("weaponEntries")).Items[0];
        ((Dictionary<string,EvidenceValue>)definition.Fields)["modifier"]=Change((EvidenceObject)definition.Get("modifier"),("formulaItem",new EvidenceText("BaseMultiplier")));
        var unsupported=Deriver(cards:badStage).Derive(weaponRow);
        check(unsupported.Entries.Count==0 && Blocked(unsupported,"unmodeled_item_damage_attribute_stage"),
            "A known card at an unsupported damage stage is blocked rather than treated as additive damage");
        var contradicted=deriver.Derive(Change(weaponRow,("weapon_source_skills",Array("""[{"skill_id":101,"bb":{"damage":0.2}},{"skill_id":101,"bb":{"damage":0.3}},{"skill_id":101,"bb":{"damage":0.2}}]"""))));
        check(contradicted.Entries.Count==0 && Blocked(contradicted,"conflicting_static_multiplier_source"),
            "A conflicting source removes its prior candidate permanently even if the original value is observed again");
        var suit=deriver.Derive(Obj("""{"suit_effects":[{"suit_id":"suit_expend_spell01","active":true,"value":{"atk_up":0.1,"spell_dmg_up":0.2,"duration":10,"max_stack":3}}]}"""));
        check(suit.Entries.Count==0 && Baseline(suit).Items.Count==1
            && ((EvidenceObject)Baseline(suit).Items[0]).Get("field") is EvidenceText { Value:"atk_up" }
            && !Blocked(suit,"unmodeled_suit_static_semantics"),
            "Reviewed suit baseline fields remain baseline evidence while reviewed trigger values do not become static rates");
        var unknown=deriver.Derive(Obj("""{"suit_effects":[{"suit_id":"unknown","active":false,"value":{}}],"unresolved_equip_inst_ids":["7"]}"""));
        check(Blocked(unknown,"unmodeled_suit_static_semantics") && Blocked(unknown,"unresolved_equipment_slot"),
            "Unknown suit semantics and unresolved inventory slots remain explicit blockers");
        var original=EvidenceJsonSignature.Sorted(row);
        var owned=deriver.Derive(row);
        var ownedEquip=(EvidenceObject)((EvidenceArray)owned.Loadout.Get("equips")).Items[0];
        ((Dictionary<string,EvidenceValue>)ownedEquip.Fields)["item_id"]=new EvidenceText("changed");
        check(original==EvidenceJsonSignature.Sorted(row) && deriver.Derive(row).Entries.Count==1,
            "Derivation owns its nested loadout and does not retain candidates across calls");

        var root=Path.Combine(Path.GetTempPath(),"endfield-multiplier-factory-"+Guid.NewGuid().ToString("N"));
        var directory=Path.Combine(root,"data/local_tables/equip");Directory.CreateDirectory(directory);
        try
        {
            var file=Path.Combine(directory,"pieces.json");
            File.WriteAllText(file,"""{"sourceTableSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","entries":[{"itemId":"equip_a","equipAttrModifiers":[{"attrIndex":0,"attrType":32,"modifierType":5,"modifyAttributeType":0,"attrValues":[0.4]}]}]}""");
            var loaded=StaticMultiplierDeriver.Load(new(root));
            File.WriteAllText(file,"{}");
            check(loaded.Derive(complete).Entries is [var loadedEntry] && loadedEntry.Get("rate") is EvidenceReal { Value:0.4 }
                && StaticMultiplierDeriver.Load(new(root)).Derive(complete).Entries.Count==0,
                "The production factory loads actual equipment tables and holds stable evidence for its report instance");
        }
        finally { Directory.Delete(root,recursive:true); }
    }
}
