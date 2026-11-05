using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Reporting;

internal static class BaselineEvidenceSpecs
{
    private static EvidenceObject Obj(string json)=>(EvidenceObject)EvidenceJson.Parse(json);
    public static void Run(Action<bool,string> check)
    {
        var root=Path.Combine(Path.GetTempPath(),"endfield-base-stat-"+Guid.NewGuid().ToString("N"));
        var directory=Path.Combine(root,"data/local_tables/character/items");
        Directory.CreateDirectory(directory);
        try
        {
            File.WriteAllText(Path.Combine(directory,"chr_test.json"),"""
                {"raw":{"mainAttrType":39,"subAttrType":40,"attributes":[
                  {"breakStage":"2.0","Attribute":{"attrs":[{"attrType":0,"attrValue":1},{"attrType":0,"attrValue":1.5},{"attrType":2,"attrValue":100},{"attrType":2,"attrValue":120}]}},
                  {"Attribute":{"attrs":[{"attrType":0,"attrValue":2},{"attrType":2,"attrValue":130}]}},
                  {"Attribute":{"attrs":[{"attrType":0,"attrValue":2},{"attrType":2,"attrValue":140}]}},
                  {"Attribute":{"attrs":[{"attrType":0,"attrValue":2},{"attrType":2,"attrValue":130}]}},
                  {"Attribute":{"attrs":[{"attrType":0,"attrValue":90},{"attrType":2,"attrValue":200}]}}
                ]}}
                """);
            CharacterBaseStatCatalog catalog=new(new(root));
            var exact=catalog.Get("chr_test",1)!;
            check(exact.Get("atk") is EvidenceReal { Value:120 } && exact.Get("level") is EvidenceInteger { Value:var level } && level==1
                && exact.Get("break_stage") is EvidenceInteger { Value:var stage } && stage==2,
                "The last valid integral level marker survives a later fractional marker; attributes use last-write values");
            check(catalog.Get("chr_test",2) is null && catalog.Entries["chr_test"].Keys.SequenceEqual(new BigInteger[] { 1,90 }),
                "Conflicting rows permanently remove that exact level, including a later repeated earlier row");
            check(catalog.Get("chr_test",0) is null && catalog.Get("chr_test",89) is null && catalog.Get("missing",1) is null
                && catalog.Get("chr_test",90)!.Get("atk") is EvidenceReal { Value:200 },
                "Only an exact positive observed level supplies base stats, without interpolation or nearest-level fallback");
            check(exact.Get("hp") is EvidenceNull && exact.Get("level_source") is EvidenceText { Value:"loadout" }
                && catalog.Entries["chr_test"][1].Get("level_source") is EvidenceNull
                && !ReferenceEquals(exact,catalog.Get("chr_test",1)),
                "Missing attributes remain unknown and each lookup adds provenance to an owned row");
        }
        finally { Directory.Delete(root,recursive:true); }

        var hits=new[]
        {
            Obj("""{"target_enemy_key":"enemy","target_actor_id":"11","enemy_hp_after":90,"hit_value":10}"""),
            Obj("""{"target_enemy_key":"enemy","target_actor_id":"22","enemy_hp_after":200,"hit_value":20}"""),
            Obj("""{"target_enemy_key":"enemy","target_actor_id":"11","enemy_hp_after":80,"hit_value":25,"target_enemy_max_hp":200}"""),
            Obj("""{"target_enemy_key":"enemy","target_actor_id":"11","enemy_hp_after":150,"hit_value":10}"""),
        };
        var signature=string.Join(";",hits.Select(EvidenceJsonSignature.Sorted));
        var annotated=EnemyHpEvidence.Annotate(hits);
        check(annotated[0].Get("enemy_hp_before") is EvidenceInteger { Value:var first } && first==100
            && annotated[2].Get("enemy_hp_before") is EvidenceInteger { Value:var third } && third==90
            && annotated[2].Get("enemy_hp_before_source") is EvidenceText { Value:"previous_enemy_hp" },
            "A target starts from after-HP plus hit, then uses its prior observed after-HP instead of reported damage");
        check(annotated[0].Get("target_enemy_observed_max_hp") is EvidenceInteger { Value:var a } && a==160
            && annotated[1].Get("target_enemy_observed_max_hp") is EvidenceInteger { Value:var b } && b==220,
            "Identical templates keep separate actor HP histories and retrospectively attach only their own observed maximum");
        check(annotated[3].Get("enemy_hp_before") is EvidenceInteger { Value:var healed } && healed==160
            && annotated[3].Get("enemy_hp_before_source") is EvidenceText { Value:"enemy_hp_after_plus_hit" },
            "An HP increase resumes from current after-HP plus damage instead of inventing a monotone health history");
        check(annotated[0].Get("target_enemy_hp_ratio_before") is EvidenceNull
            && annotated[2].Get("target_enemy_hp_ratio_before") is EvidenceReal { Value:.45 },
            "An observed maximum cannot establish CheckHp; a positive explicit maximum supplies the ratio");
        check(signature==string.Join(";",hits.Select(EvidenceJsonSignature.Sorted)) && !ReferenceEquals(annotated[0],hits[0])
            && EnemyHpEvidence.Annotate([hits[2]])[0].Get("enemy_hp_before") is EvidenceInteger { Value:var independent } && independent==105,
            "HP annotations own their input and histories are independent between report calls");
        check(EnemyHpEvidence.StateKey(new EvidenceText("enemy"),new EvidenceText("01"))=="template:enemy"
            && EnemyHpEvidence.StateKey(new EvidenceText("enemy"),new EvidenceText("11"))=="actor:11"
            && EnemyHpEvidence.StateKey(new EvidenceText("enemy"),new EvidenceInteger(0))=="template:enemy",
            "Only a canonical positive decimal actor identity replaces the template fallback");
        var large=BigInteger.One<<4096;
        check(PythonIntegerDivision.Divide(large,large+1)==1 && PythonIntegerDivision.Divide((BigInteger.One<<53)+1,BigInteger.One<<53)==1,
            "Large exact ratios and a halfway tie are rounded once without converting each operand to double");
        check(BitConverter.DoubleToUInt64Bits(PythonIntegerDivision.Divide(0,-1))==0x8000000000000000UL
            && PythonIntegerDivision.Divide(1,BigInteger.One<<1074)==double.Epsilon
            && PythonIntegerDivision.Divide(1,BigInteger.One<<1075)==0
            && PythonIntegerDivision.Divide(3,BigInteger.One<<1075)==2*double.Epsilon,
            "Integer division retains signed zero and ties-to-even rounding at the subnormal boundary");
    }
}
