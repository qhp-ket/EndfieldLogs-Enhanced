using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

internal static class StaticBaselineSpecs
{
    private const string Character="chr_0001_alpha";
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row,params (string Key,EvidenceValue Value)[] changes)
    {
        var fields=new Dictionary<string,EvidenceValue>(row.Fields,StringComparer.Ordinal);
        foreach(var (key,value) in changes) fields[key]=value;
        return new(fields);
    }
    public static void Run(Action<bool,string> check)
    {
        var root=Path.Combine(Path.GetTempPath(),"endfield-static-baseline-spec-"+Guid.NewGuid().ToString("N"));
        void Write(string relative,string text)
        {
            var path=Path.Combine(root,relative);Directory.CreateDirectory(Path.GetDirectoryName(path)!);File.WriteAllText(path,text);
        }
        try
        {
            Write("data/local_tables/equip/pieces.json","""
                {"sourceTableSha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","entries":[{"itemId":"equip_a","equipAttrModifiers":[
                 {"attrIndex":0,"attrType":2,"modifierType":7,"modifyAttributeType":0,"attrValues":[25]},
                 {"attrIndex":1,"attrType":32,"modifierType":5,"modifyAttributeType":0,"attrValues":[0.2]},
                 {"attrIndex":2,"attrType":87,"modifierType":5,"modifyAttributeType":0,"attrValues":[30]}]}]}
                """);
            Write("data/local_tables/character/items/"+Character+".json","""
                {"raw":{"mainAttrType":39,"subAttrType":40,"attributes":[{"Attribute":{"attrs":[{"attrType":0,"attrValue":1},{"attrType":2,"attrValue":100}]}}]}}
                """);
            var row=Obj("""{"weapon_template":"wpn_a","weapon_base_atk":50,"character_level":1,"equipment_snapshot_complete":true,"equips":[{"item_id":"equip_a","slot":0}]}""");
            var evidence=Obj("""{"character_key":"chr_0001_alpha","ts_ms":1000,"line_no":10,"target_enemy_key":"eny_test","target_actor_id":"7","enemy_hp_after":900,"hit_value":100,"target_enemy_max_hp":1200,"damage_decorate_mask":256}""");
            IReadOnlyDictionary<BigInteger,EvidenceValue> empty=new Dictionary<BigInteger,EvidenceValue>();
            var attributes=new Dictionary<BigInteger,EvidenceValue>
            { [39]=new EvidenceReal(10.9),[40]=new EvidenceReal(5.9),[78]=new EvidenceReal(.01),[79]=new EvidenceReal(.02) };
            ReportHitInput hit=new(evidence,empty,new Dictionary<BigInteger,EvidenceValue> { [2]=new EvidenceReal(110) },attributes);
            ReportBaselineInput Input(IReadOnlyList<ReportHitInput>? hits=null,EvidenceObject? loadout=null,IReadOnlyList<EvidenceObject>? groups=null)=>new(
                new(groups ?? [],new Dictionary<string,EvidenceObject> { [Character]=loadout ?? row }),hits ?? [hit],
                new Dictionary<string,HashSet<string>> { [Character]=["suit_known"] });
            var builder=StaticBaselineBuilder.Load(new(root));var input=Input();
            var signature=EvidenceJsonSignature.Sorted(row)+EvidenceJsonSignature.Sorted(evidence);
            var baseline=builder.Prepare(input,9999);var produced=baseline.Hits.Single().Evidence;
            check(!baseline.LoadoutStale && baseline.ActiveSuits[Character].SetEquals(["suit_known"])
                && baseline.ActiveWeapons[Character]=="wpn_a" && baseline.Hits.Count==1,
                "The resource-backed baseline retains the current party and rebuilds active weapon identity");
            check(produced.Get("static_flat_attack") is EvidenceReal { Value:25 }
                && produced.Get("static_multiplier_entries") is EvidenceArray { Items.Count:1 }
                && produced.Get("static_arts_strength_entries") is EvidenceArray { Items.Count:1 }
                && baseline.StaticArtsStrength[Character]==30,
                "The full baseline joins exact flat attack, skill damage and arts evidence from production resource files");
            check(produced.Get("base_attack_for_percent") is EvidenceReal { Value:160 },
                "Observed basic attack 110 and weapon attack 50 form the percent-attack baseline 160");
            check(produced.Get("attack_ability_factor") is EvidenceReal factor && Math.Abs(factor.Value-1.2)<1e-14,
                "Ability scaling truncates 10.9 and 5.9 before multiplying their observed 0.01 and 0.02 scales");
            check(produced.Get("enemy_hp_before") is EvidenceInteger { Value:var before } && before==1000
                && produced.Get("target_enemy_observed_max_hp") is EvidenceInteger { Value:var maximum } && maximum==1000
                && produced.Get("target_enemy_hp_ratio_before") is EvidenceReal ratio && ratio.Value==1000.0/1200,
                "Baseline assembly finishes with observed enemy HP while a ratio requires an explicit maximum");
            var fallback=builder.Prepare(Input([hit with { BasicAttributes=empty }]),1000).Hits.Single().Evidence;
            check(fallback.Get("base_attack_for_percent") is EvidenceReal { Value:150 },
                "Absent observed basic attack falls back to the exact level's official 100 plus weapon 50");
            var textOnly=builder.Prepare(Input([hit with { Evidence=Change(evidence,("attacker_stats_basic_attrs",Obj("""{"2":999}"""))),BasicAttributes=empty }]),1000);
            check(textOnly.Hits.Single().Evidence.Get("base_attack_for_percent") is EvidenceReal { Value:150 },
                "A textual attribute key cannot substitute for the integer-key basic attack observation");
            var unknown=builder.Prepare(Input([hit with { BasicAttributes=empty }],Change(row,("character_level",new EvidenceInteger(90)))),1000);
            check(unknown.Hits.Single().Evidence.Get("base_attack_for_percent") is EvidenceNull
                && unknown.Hits.Single().Evidence.Get("attack_ability_factor") is EvidenceNull,
                "An unsupported character level does not interpolate an attack or invent ability attribute types");
            var absent=builder.Prepare(Input([hit with { Evidence=Change(evidence,("character_key",new EvidenceText("chr_missing"))) }]),1000);
            check(absent.LoadoutStale && absent.Loadouts.Count==0 && absent.ActiveSuits.Count==0 && absent.ActiveWeapons.Count==0
                && absent.Hits.Single().Evidence.Get("static_flat_attack") is EvidenceInteger { Value:var zero } && zero==0,
                "One observed party member missing from the selected loadout invalidates the whole party equipment view");
            var preserved=builder.Prepare(Input(loadout:Change(row,("unresolved_equip_inst_ids",(EvidenceArray)EvidenceJson.Parse("""["7"]""")))),1000);
            check(preserved.Hits.Single().Evidence.Get("rdps_unresolved_static_multiplier_sources") is EvidenceArray { Items.Count:1 },
                "A complete table and valid hit attributes cannot retire an unresolved equipment source blocker");
            var firstGroup=Obj("""{"ts_ms":900,"line_no":1,"rows":{}}""");
            var laterGroup=Obj("""{"ts_ms":1000,"line_no":11,"rows":{}}""");
            EvidenceObject Group(EvidenceObject group,int attack)=>Change(group,("rows",new EvidenceObject(new Dictionary<string,EvidenceValue>
            { [Character]=Change(row,("weapon_base_atk",new EvidenceInteger(attack))) })));
            var groups=new[] { Group(firstGroup,40),Group(laterGroup,80) };
            check(builder.Prepare(Input(groups:groups),9999).Hits.Single().Evidence.Get("base_attack_for_percent") is EvidenceReal { Value:150 }
                && builder.Prepare(Input([hit with { Evidence=Change(evidence,("line_no",new EvidenceInteger(12))) }],groups:groups),1)
                    .Hits.Single().Evidence.Get("base_attack_for_percent") is EvidenceReal { Value:190 },
                "The first hit's timestamp and line boundary select equipment rather than the caller's fallback clock");
            check(builder.Prepare(Input([],groups:groups),950).Loadouts[Character].Get("weapon_base_atk") is EvidenceInteger { Value:var earlier } && earlier==40
                && builder.Prepare(Input([],groups:groups),800).Loadouts.Count==0,
                "An empty hit list uses the explicit first-hit clock and never selects a future loadout");
            var repeated=builder.Prepare(input,1000);
            ReportHitInput Frozen(ReportHitInput value)=>value with
            {
                Evidence=(EvidenceObject)FrozenEvidence.Capture(value.Evidence), Baseline=FrozenEvidence.CaptureNumbers(value.Baseline),
                BasicAttributes=FrozenEvidence.CaptureNumbers(value.BasicAttributes), Attributes=FrozenEvidence.CaptureNumbers(value.Attributes),
            };
            var frozenHit=Frozen(hit);
            LiveHitPreparationCache preparation=new();
            var coldPrepared=builder.PrepareOwned(Input([frozenHit]),1000,preparation);
            var hotPrepared=builder.PrepareOwned(Input([frozenHit]),1000,preparation);
            check(preparation.PreparedHits==1 && preparation.ReusedHits==1 && preparation.ProjectedHpHits==1
                && ReferenceEquals(coldPrepared.Hits[0].Evidence,hotPrepared.Hits[0].Evidence)
                && EvidenceJson.PythonEquals(hotPrepared.Hits[0].Evidence,produced),
                "Unchanged immutable hits reuse their static preparation and HP projection without rebuilding writable roots");
            var lateHit=Frozen(hit with { BasicAttributes=new Dictionary<BigInteger,EvidenceValue> { [2]=new EvidenceReal(120) } });
            var latePrepared=builder.PrepareOwned(Input([lateHit]),1000,preparation);
            check(preparation.PreparedHits==2 && preparation.RetractedHpHits==1
                && EvidenceJson.PythonEquals(latePrepared.Hits[0].Evidence,builder.Prepare(Input([lateHit]),1000).Hits[0].Evidence)
                && hotPrepared.Hits[0].Evidence.Get("base_attack_for_percent") is EvidenceReal { Value:160 },
                "Late numeric hit evidence replaces preparation and HP suffix state without modifying an earlier result");
            var weaponChanged=builder.PrepareOwned(Input([lateHit],Change(row,("weapon_base_atk",new EvidenceInteger(90)))),1000,preparation);
            check(preparation.ContextChanges==2 && weaponChanged.Hits[0].Evidence.Get("base_attack_for_percent") is EvidenceReal { Value:210 }
                && latePrepared.Hits[0].Evidence.Get("base_attack_for_percent") is EvidenceReal { Value:170 },
                "A changed selected weapon invalidates static preparation and preserves previously published evidence");
            check(signature==EvidenceJsonSignature.Sorted(row)+EvidenceJsonSignature.Sorted(evidence)
                && EvidenceJsonSignature.Sorted(repeated.Hits.Single().Evidence)==EvidenceJsonSignature.Sorted(produced)
                && !ReferenceEquals(produced.Get("static_flat_attack_entries"),baseline.Loadouts[Character].Get("equipment_baseline_attributes")),
                "Preparation owns its output, keeps raw inputs unchanged and produces independent results across calls");

            BattleIngestionStream stream=new(BattleIngestionResources.Load(new(root)));
            stream.Accept(1,"[00:00:00.900] LOADOUT reason=SC_SCENE_INFO");
            stream.Accept(2,"[00:00:00.950] LOADOUT slot=0 char=chr_0001_alpha weaponTemplate=wpn_a weaponInstId=11 equipSuit={}");
            stream.Accept(3,"[00:00:00.975] ENTITY_STATS id=11 template=chr_0001_alpha kind=character level=1 attrs=[2:150/100 39:10.9 40:5.9 78:0.01 79:0.02]");
            stream.Accept(4,"[00:00:01.000] HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha atkId=11 tgt=eny_0001_target tgtId=22 hit=100 eHP=900");
            stream.Accept(5,"[00:00:01.010] BASELINE #1 32=0.4");
            stream.Party.ActiveSuits[Character]=["suit_a"];
            var captured=ReportBaselineInput.Capture(stream);
            check(captured.Hits is [var capturedHit] && capturedHit.BasicAttributes[2] is EvidenceReal { Value:100 }
                && capturedHit.Attributes[39] is EvidenceReal { Value:10.9 } && capturedHit.Baseline[32] is EvidenceReal { Value:0.4 },
                "Real trace ingestion captures distinct integer-key packet, basic and final attributes for a report");
            stream.Accept(6,"[00:00:01.020] BASELINE #1 32=0.9");
            stream.Party.ActiveSuits[Character].Clear();stream.Party.Loadouts.Clear();stream.Loadouts.Groups[0].Rows.Clear();
            var capturedBaseline=builder.Prepare(captured,1000);
            check(captured.Hits.Single().Baseline[32] is EvidenceReal { Value:0.4 }
                && capturedBaseline.ActiveSuits[Character].SetEquals(["suit_a"]) && capturedBaseline.ActiveWeapons[Character]=="wpn_a"
                && ReportBaselineInput.Capture(stream).Hits.Single().Baseline[32] is EvidenceReal { Value:0.9 },
                "Late packet and loadout changes enter the next capture without changing a dispatched baseline input");
        }
        finally { if(Directory.Exists(root)) Directory.Delete(root,recursive:true); }
    }
}
