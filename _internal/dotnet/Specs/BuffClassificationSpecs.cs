using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class BuffClassificationSpecs
{
    public static void Run(Action<bool,string> check)
    {
        static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
        PacketBuffCatalog packets=new(new Dictionary<string,EvidenceObject>(),new Dictionary<string,IReadOnlyList<EvidenceObject>>(),new Dictionary<string,string>());
        BuffDisplayClassification classification=new(packets,new Dictionary<string,EvidenceObject>
        {
            ["buff_vulnerable"]=Obj("""{"actionTypes":["VulnerableAction"]}"""),
            ["buff_dynamic"]=Obj("""{"actionTypes":["OnSpellAbnormalStartFinish"],"binaryReferencedBuffIds":["buff_effect"]}"""),
        },new Dictionary<string,EvidenceObject>
        {
            ["buff_dynamic"]=Obj("""{"classification":"wrapper","semanticFlags":{"hasDynamicBlackboard":true}}"""),
            ["buff_trigger"]=Obj("""{"classification":"wrapper","createdBuffIds":["buff_effect"]}"""),
            ["buff_resolved"]=Obj("""{"classification":"wrapper","resolvedEffectCount":1,"createdBuffIds":["buff_effect"]}"""),
        });
        check(classification.IsEffectlessWrapper(Obj("""{"event_key":"buff_vulnerable","packet_mapping":{"role":"wrapper"}}"""))==false,
            "An explicit VulnerableAction keeps its display semantics despite a packet wrapper hint");
        check(classification.IsEffectlessWrapper(Obj("""{"event_key":"buff_dynamic"}""")),
            "A dynamic abnormal-status wrapper is suppressed only with its explicit child references");
        check(classification.IsEffectlessWrapper(Obj("""{"event_key":"buff_trigger"}"""))
            && !classification.IsEffectlessWrapper(Obj("""{"event_key":"buff_resolved"}""")),
            "Known effect hints override utility wrapper suppression");
        check(!classification.IsEffectlessWrapper(Obj("""{"event_key":"buff_trigger","attr_mods":[{"attr_type":2}]}""")),
            "Observed attribute modifiers retain their display evidence");
        check(BuffDisplayClassification.IsInternalTrigger(Obj("""
            {"raw_event_key":"123","owner_raw":"eny_test","raw_source":"chr_test",
             "bb_keys":["PHY_DMG_UP","FINAL_PHY_DMG_UP","SHATTER_DMG","CONSUMED_LAYER"]}
            """)) && !BuffDisplayClassification.IsInternalTrigger(Obj("""
            {"raw_event_key":"123","owner_raw":"eny_test","raw_source":"chr_test","bb_keys":["phy_dmg_up"]}
            """)),"Internal trigger suppression requires all four numeric-helper keys and character-to-enemy direction");

        var allowed=BuffLoadoutFilter.BuildSuitBuffs(new Dictionary<string,EvidenceObject>
        { ["skill"]=Obj("""{"createdBuffIds":["buff_equipsuit_root"],"referencedBuffIds":["buff_unrelated"]}""") },
        new Dictionary<string,EvidenceObject>
        {
            ["buff_equipsuit_root"]=Obj("""{"binaryCreatedBuffIds":["buff_equipsuit_child"]}"""),
            ["buff_equipsuit_child"]=Obj("""{"referencedBuffIds":["buff_equipsuit_root","buff_child_effect"]}"""),
        },[Obj("""{"suitID":"suit","passiveSkillId":"skill"}""")]);
        check(allowed["suit"].SetEquals(["buff_equipsuit_root","buff_equipsuit_child","buff_child_effect"]),
            "Suit ancestry traverses all four semantic child fields, terminates cycles and excludes unrelated skill roots");
        BuffLoadoutFilter filter=new(packets,allowed);
        check(filter.MatchesSuit("buff_equipsuit_child","chr",new Dictionary<string,HashSet<string>> { ["chr"]=["suit"] })
            && !filter.MatchesSuit("buff_equipsuit_other","chr",new Dictionary<string,HashSet<string>> { ["chr"]=["suit"] }),
            "Known suit loadouts admit their exact child family and reject unrelated equipment BUFFs");
        check(filter.MatchesSuit("buff_equipsuit_child","other",new Dictionary<string,HashSet<string>> { ["chr"]=[] })
            && !filter.MatchesSuit("buff_equipsuit_child","chr",new Dictionary<string,HashSet<string>> { ["chr"]=[] }),
            "A missing actor loadout is unknown; an observed empty suit list explicitly excludes suit effects");
        check(filter.MatchesWeapon("buff_wpn_sword_0012_atkup","chr",new Dictionary<string,string> { ["chr"]="wpn_sword_0012" })
            && !filter.MatchesWeapon("buff_wpn_sword_0012_atkup","chr",new Dictionary<string,string> { ["chr"]="wpn_sword_0013" })
            && filter.MatchesWeapon("buff_wpn_sword_0012_atkup","other",new Dictionary<string,string> { ["chr"]="wpn_sword_0013" }),
            "Weapon filtering distinguishes exact equipment mismatch from missing actor evidence");
    }
}
