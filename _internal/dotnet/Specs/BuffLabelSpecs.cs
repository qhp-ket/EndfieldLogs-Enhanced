using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class BuffLabelSpecs
{
    public static void Run(Action<bool,string> check)
    {
        static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
        var roots=new Dictionary<string,EvidenceObject>();
        PacketBuffCatalog packets=new(new Dictionary<string,EvidenceObject>(),new Dictionary<string,IReadOnlyList<EvidenceObject>>(),new Dictionary<string,string>());
        EffectApproval approval=new(Obj("{}"),roots,new Dictionary<string,string>(),new Dictionary<string,string>());
        BuffLabelCatalog catalog=new(new(roots,new Dictionary<string,EvidenceObject> { ["NormalCalcZone"]=Obj("{}") },approval),
            new(packets,new Dictionary<string,EvidenceObject>(),new Dictionary<string,EvidenceObject>()),new(packets,new(new Dictionary<string,EvidenceObject>(),_=>null)));
        check(catalog.Collect(Obj("""{"event_key":"buff_common_fire_fire_triggered"}""")).Labels.SequenceEqual(["法术爆发","燃烧"]),
            "Anomaly labels preserve simultaneous burn and same-element burst in deterministic display order");
        check(catalog.Collect(Obj("""
            {"event_key":"buff_frozen","target_enemy_key":"enemy","source_character_key":"chr_0029_pograni","bb_values":{"physical_res_down":0.2}}
            """)).Labels.SequenceEqual(["碎甲"]),"Pograni physical reduction is shatter armour rather than a frozen status");
        check(catalog.Collect(Obj("""{"event_key":"buff_common_vfx_test","bb_keys":["atk_up"]}""")).Labels.Count==0,
            "A noise template alone cannot turn an internal blackboard key into a visible buff label");
        check(catalog.Collect(Obj("""{"event_key":"buff_common_affixes_combo_trigger"}""")).Labels.SequenceEqual(["连击增伤"]),
            "The generic combo trigger retains its explicit label without inferred rates");
        check(catalog.Collect(Obj("""{"event_key":"buff","attr_mods":[{"attr_type":65,"bb_key":"fire_dmg_up"},{"attr_type":71}]}"""))
            .Labels.SequenceEqual(["脆弱"]),"Attribute labels avoid presenting an amplification field that carries damage-increase operands");
        check(catalog.Collect(Obj("""{"event_key":"buff_wpn_sword_0016_team","bb_keys":["phy_dmg_up","crit_up"]}"""))
            .Labels.SequenceEqual(["暴击"]),"Mixed weapon owner-side keys are excluded while independent critical evidence remains visible");
        var typed=Obj("""
            {"damageModifier":[{"enableSide":"Attacker","condition":{"onlyExecuteWhenSourceIsMainChar":false,
              "onlyExecuteWhenSourceIsGuard":false,"actionData":[]},"damageProcessors":[
              {"$type":"Beyond.Gameplay.Core.DamageScaleProcessor","side":"Defender","zoneName":"NormalCalcZone",
               "addition":{"useBlackboardKey":true,"blackboardKey":"dmg_up"}}]}]}
            """);
        roots["buff_common_vfx_typed"]=typed;
        var record=Obj("""
            {"event_key":"buff_common_vfx_typed","bb_keys":["dmg_up"],"bb_values":{"dmg_up":0.2},
             "packet_mapping":{"effects":[{"zone":"amp","bb_key":"dmg_up"}]},"rdps_unresolved_semantic_condition":["old"]}
            """);
        var original=EvidenceJsonSignature.Sorted(record);
        var projection=catalog.Collect(record);
        check(projection.Labels.SequenceEqual(["承伤易伤"]),
            "A current typed defender effect survives noise filtering and supersedes the same packet blackboard hint");
        check(projection.Record.Get("rdps_unresolved_semantic_condition") is EvidenceNull && EvidenceJsonSignature.Sorted(record)==original,
            "Label evaluation refreshes quality on owned evidence without changing the caller's record");
        check(BuffLabelCatalog.ZoneFromLabel("碎甲")=="vuln_taken" && BuffLabelCatalog.ZoneFromLabel("物理脆弱")=="fragile"
            && BuffLabelCatalog.ZoneFromLabel("燃烧") is null,"Display-to-zone mapping preserves the existing distinction between labels and allocating zones");
    }
}
