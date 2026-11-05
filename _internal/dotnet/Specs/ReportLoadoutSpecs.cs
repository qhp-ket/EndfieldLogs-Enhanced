using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class ReportLoadoutSpecs
{
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Group(string rows,int time=1000,int line=10,string reason="SC_SCENE_INFO")=>new(
        new Dictionary<string,EvidenceValue> { ["rows"]=Obj(rows),["ts_ms"]=new EvidenceInteger(time),
            ["line_no"]=new EvidenceInteger(line),["reason"]=new EvidenceText(reason) });

    public static void Run(Action<bool,string> check)
    {
        BattleLoadoutResolver resolver=new(new Dictionary<string,string> { ["101"]="sk_wpn_a",["102"]="sk_wpn_b" });
        var first=Group("""{"a":{"weapon_inst_id":"a","weapon_template":"wpn_a","potential":2,"weapon_source_skills":[{"skill_id":101}],"skill_int_ids":[1,101],"equips":[{"slot":0,"item_id":"equip_a"}]},"b":{"weapon_inst_id":"b","weapon_template":"wpn_b","potential":5,"weapon_source_skills":[{"skill_id":102}],"skill_int_ids":[2,102],"equips":[{"slot":0,"item_id":"equip_b"}]}}""");
        var future=Group("""{"future":{"weapon_template":"wpn_future"}}""",2000,20);
        var fallback=new Dictionary<string,EvidenceObject> { ["future"]=Obj("""{"weapon_template":"wpn_future"}""") };
        check(resolver.Select([first,future],fallback,999).Count==0,
            "Existing groups with no eligible observation exclude the future fallback");
        check(resolver.Select([first,future],fallback,1000,9).Count==0
            && resolver.Select([first,future],fallback,1000,10).Keys.SequenceEqual(["a","b"]),
            "An equal timestamp is admitted only at or before the first-hit source line");
        check(resolver.Select([first,future],fallback,null).Keys.SequenceEqual(["future"]),
            "The last observed snapshot restricts membership rather than accumulating previous party members");
        var partial=Group("""{"a":{"weapon_base_atk":200}}""",1000,11);
        var selected=resolver.Select([first,partial],fallback,1000,11);
        check(selected.Count==1 && selected["a"].Get("weapon_template") is EvidenceText { Value:"wpn_a" }
            && selected["a"].Get("weapon_base_atk") is EvidenceInteger { Value:var attack } && attack==200,
            "Adjacent LOADOUT and LOADOUT_STATS observations retain both halves of the selected member");
        var copiedFallback=resolver.Select([],fallback,null);
        check(copiedFallback.Count==1 && !ReferenceEquals(copiedFallback["future"],fallback["future"]),
            "Absent group history uses owned fallback evidence");

        var transfer=Group("""{"a":{"weapon_inst_id":"b","weapon_template":"wpn_a","potential":2,"weapon_source_skills":[{"skill_id":101}],"skill_int_ids":[1,101],"equips":[{"slot":0,"item_id":"equip_a"}]}}""",1100,20,"SC_WEAPON_PUTON");
        var stale=Group("""{"a":{"weapon_inst_id":"b","weapon_template":"wpn_a","potential":2},"b":{"weapon_inst_id":"b","weapon_template":"wpn_b","potential":5}}""",1200,30);
        var signature=EvidenceJsonSignature.Sorted(first)+EvidenceJsonSignature.Sorted(transfer)+EvidenceJsonSignature.Sorted(stale);
        var repaired=resolver.Repair([first,transfer,stale],new Dictionary<string,EvidenceObject>());
        var after=resolver.Select(repaired.Groups,repaired.Fallback,1200);
        check(after["a"].Get("weapon_inst_id") is EvidenceText { Value:"b" }
            && after["a"].Get("weapon_template") is EvidenceText { Value:"wpn_b" }
            && after["b"].Get("weapon_inst_id") is EvidenceText { Value:"a" }
            && after["b"].Get("weapon_template") is EvidenceText { Value:"wpn_a" },
            "A partial weapon put-on swaps both corrected owners and carries correction through cached scene rows");
        var receiver=(EvidenceObject)((EvidenceObject)repaired.Groups[1].Get("rows")).Get("a");
        var receiverSkill=(EvidenceObject)((EvidenceArray)receiver.Get("weapon_source_skills")).Items.Single();
        check(receiverSkill.Get("skill_id") is EvidenceInteger { Value:var skill } && skill==102
            && receiverSkill.Get("potential_level") is EvidenceInteger { Value:var potential } && potential==2
            && ((EvidenceObject)((EvidenceArray)receiver.Get("equips")).Items.Single()).Get("item_id") is EvidenceText { Value:"equip_a" }
            && ((EvidenceArray)receiver.Get("skill_int_ids")).Items.Select(item=>((EvidenceInteger)item).Value).SequenceEqual(new System.Numerics.BigInteger[] { 1,102 }),
            "Weapon transfer changes only weapon evidence, applies destination potential and keeps character/equipment skill identity");
        var sync=Group("""{"a":{"weapon_inst_id":"b","weapon_template":"wpn_b","potential":2},"b":{"weapon_inst_id":"c","weapon_template":"wpn_c","potential":5}}""",1300,40,"SC_SYNC_CHAR_BAG_INFO");
        var authoritative=resolver.Repair([first,transfer,stale,sync],new Dictionary<string,EvidenceObject>());
        check(authoritative.Fallback["b"].Get("weapon_inst_id") is EvidenceText { Value:"c" }
            && authoritative.Fallback["b"].Get("weapon_template") is EvidenceText { Value:"wpn_c" },
            "A full bag sync supplies authoritative weapon state instead of replaying a prior correction");
        check(signature==EvidenceJsonSignature.Sorted(first)+EvidenceJsonSignature.Sorted(transfer)+EvidenceJsonSignature.Sorted(stale)
            && !ReferenceEquals(((EvidenceObject)first.Get("rows")).Get("a"),repaired.Fallback["a"])
            && resolver.Repair([first,transfer,stale],new Dictionary<string,EvidenceObject>()).Fallback["a"].Get("weapon_template") is EvidenceText { Value:"wpn_b" },
            "Repair owns nested evidence, leaves raw history unchanged and is independent across repeated calls");

        var mismatched=Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":102}],"weapon_refine_stats":[{"skill_id":102}],"weapon_refine":4,"weapon_refine_source":"source_skill","skill_int_ids":[1,102,0]}""");
        var sanitized=resolver.WithoutMismatchedWeaponSkills(mismatched);
        check(sanitized.Get("weapon_source_skills") is EvidenceArray { Items.Count:0 }
            && sanitized.Get("weapon_refine_stats") is EvidenceArray { Items.Count:0 }
            && sanitized.Get("weapon_refine") is EvidenceNull && sanitized.Get("weapon_refine_source") is EvidenceNull
            && ((EvidenceArray)sanitized.Get("skill_int_ids")).Items is [EvidenceInteger { Value:var remaining }] && remaining==1,
            "Proven mismatched weapon skills remove their derived refinement and stale numeric identities");
        var matching=Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":101},{"skill_id":102}]}""");
        check(resolver.WithoutMismatchedWeaponSkills(matching).Get("weapon_source_skills") is EvidenceArray { Items.Count:2 }
            && resolver.WithoutMismatchedWeaponSkills(Obj("""{"weapon_template":"wpn_a","weapon_source_skills":[{"skill_id":"skill_102"}]}""")).Get("weapon_source_skills") is EvidenceArray { Items.Count:1 },
            "One matching declared main skill is sufficient; runtime-looking names do not invent a numeric table binding");

        var root=Path.Combine(Path.GetTempPath(),"endfield-report-loadout-"+Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(root,"data/local_tables"));
        try
        {
            File.WriteAllText(Path.Combine(root,"data/local_tables/NumIdStrTable.json"),"""{"skill_id":{"dic":{"101":"sk_wpn_a","102":"sk_wpn_b"}}}""");
            var loaded=BattleLoadoutResolver.Load(new(root));
            check(loaded.WithoutMismatchedWeaponSkills(mismatched).Get("weapon_refine") is EvidenceNull,
                "The production resolver reads canonical source skills from the resource numeric table");
            BattleIngestionStream stream=new(BattleIngestionResources.Load(new(root)));
            stream.Accept(1,"[00:00:01.000] LOADOUT reason=SC_SCENE_INFO");
            stream.Accept(2,"[00:00:01.000] LOADOUT slot=0 char=chr_0001_alpha weaponTemplate=wpn_a weaponInstId=11 equipSuit={suit_a:3}");
            var capture=ReportLoadoutInput.Capture(stream);
            var capturedSignature=EvidenceJsonSignature.Sorted(capture.Groups.Single());
            stream.Loadouts.Groups[0].Rows.Clear();
            stream.Party.Loadouts.Clear();
            stream.Accept(3,"[00:00:02.000] LOADOUT slot=0 char=chr_0001_alpha weaponTemplate=wpn_b weaponInstId=22 equipSuit={}");
            check(capture.Fallback["chr_0001_alpha"].Get("weapon_template") is EvidenceText { Value:"wpn_a" }
                && capturedSignature==EvidenceJsonSignature.Sorted(capture.Groups.Single())
                && resolver.Select(capture.Groups,capture.Fallback,1000)["chr_0001_alpha"].Get("weapon_inst_id") is EvidenceText { Value:"11" },
                "A report captures real ingestion group/fallback evidence before later groups and party replacement");
            var next=ReportLoadoutInput.Capture(stream);
            check(next.Fallback["chr_0001_alpha"].Get("weapon_template") is EvidenceText { Value:"wpn_b" }
                && capture.Fallback["chr_0001_alpha"].Get("weapon_template") is EvidenceText { Value:"wpn_a" },
                "The next report capture receives late equipment observations without changing an existing report");
        }
        finally { Directory.Delete(root,recursive:true); }
    }
}
