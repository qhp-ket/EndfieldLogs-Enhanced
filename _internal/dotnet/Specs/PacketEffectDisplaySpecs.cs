using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class PacketEffectDisplaySpecs
{
    public static void Run(Action<bool,string> check)
    {
        static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
        var hint=Obj("""{"effects":[{"zone":"amp","bb_key":"physical_res_down","prefer_runtime_rate_key":"rate","rate":0.5}]}""");
        PacketEffectDisplayCatalog catalog=new(new(new Dictionary<string,EvidenceObject> { ["10"]=hint },
            new Dictionary<string,IReadOnlyList<EvidenceObject>>(),new Dictionary<string,string>()),new(new Dictionary<string,EvidenceObject>(),_=>null));
        var record=Obj("""{"event_key":"10","bb_values":{"rate":0.25}}""");
        var original=EvidenceJsonSignature.Sorted(record);
        var projected=catalog.Static(record);
        check(projected is [var effect] && effect.Get("rate") is EvidenceReal { Value:0.25 }
            && effect.Get("condition") is EvidenceObject condition
            && condition.Get("elements") is EvidenceArray { Items:[EvidenceText { Value:"physical" }] },
            "The runtime fallback rate keeps its declared physical damage applicability");
        check(catalog.Static(Obj("""{"event_key":"10"}""")).Count==0,
            "A literal rate is ignored unless the mapping explicitly allows constants");
        check(catalog.Static(Obj("""{"event_key":"10","packet_mapping":{},"bb_values":{"rate":0.25}}""")).Count==0,
            "An explicit empty packet mapping supersedes numeric lookup");
        check(catalog.Static(Obj("""{"packet_mapping":{"allow_static_rate":true,"effects":[{"zone":"res","rate":20},{"zone":"crit","rate":0.2}]}}"""))
            is [var crit] && crit.Get("zone") is EvidenceText { Value:"crit" },
            "Display projections retain critical hints and exclude unsupported resistance allocation");
        var dynamic=Obj("""
            {"packet_mapping":{"dynamic_effects":[{"zone":"amp","base_bb_keys":["alias","base"],"base_bb_key":"base",
              "tick_bb_keys":["tick"],"tick_multiplier":2,"add_bb_key":"add","delay_bb_key":"delay","max_bb_key":"max"}]},
             "bb_values":{"alias":0.2,"base":0.4,"tick":0.03,"add":0.5,"delay":2,"max":0.9}}
            """);
        var value=catalog.Dynamic(dynamic).Single();
        check(value.Get("base_rate") is EvidenceReal { Value:0.2 } && value.Get("bb_key") is EvidenceText { Value:"alias" }
            && value.Get("tick_rate") is EvidenceReal { Value:0.06 } && value.Get("delayed_add_rate") is EvidenceReal { Value:0.5 }
            && value.Get("delay_sec") is EvidenceReal { Value:2 } && value.Get("max_rate") is EvidenceReal { Value:0.9 },
            "Display-only dynamics preserve first positive alias, tick scaling, delayed addition and cap");
        check(catalog.StackLimit(Obj("""{"bb_values":{"max_stack":-1,"stack_limit":3,"maxStack":4},"packet_mapping":{"stack_limit":7}}"""))==3,
            "Stack limits use the first positive observed field before a mapping constant");
        check(catalog.StackLimit(Obj("""{"packet_mapping":{"stack_limit":7}}"""))==7,
            "A mapping stack limit remains available without observed stack fields");
        check(EvidenceJsonSignature.Sorted(record)==original && !record.Fields.ContainsKey("zone_effects"),
            "Display projection leaves caller evidence independent and grants no allocation authorization");

        var root=Obj("""
            {"nested":[{"$type":"Beyond.Gameplay.Core.EnhancedAction+Data","asChildBuff":true,
              "childBuffId":{"value":"child"},"subType":"Crystal","rate":{"blackboardKey":"enhance"}}]}
            """);
        int reads=0;
        EnhancedChildEffectCatalog enhanced=new(new Dictionary<string,EvidenceObject>
            { ["parent"]=Obj("""{"referencedBuffIds":["child"]}""") },_=> { reads++; return root; });
        var first=enhanced.For("child");
        ((Dictionary<string,EvidenceValue>)first[0].Fields)["element"]=new EvidenceText("wrong");
        check(enhanced.For("child") is [var child] && child.Get("element") is EvidenceText { Value:"cryst" } && reads==1,
            "Enhanced child lookup caches traversal while returning independently owned declarations");
        check(enhanced.For("other").Count==0,
            "Enhanced actions cannot label a child absent from the explicit semantic reverse references");

        var folder=Path.Combine(Path.GetTempPath(),"endfield-display-"+Guid.NewGuid().ToString("N"));
        try
        {
            Directory.CreateDirectory(Path.Combine(folder,"data/local_semantics/buff"));
            Directory.CreateDirectory(Path.Combine(folder,"data/akedata/buff/items"));
            Directory.CreateDirectory(Path.Combine(folder,"custom"));
            File.WriteAllText(Path.Combine(folder,"data/local_semantics/buff/details.json"),"""
                {"entries":{"parent":{"referencedBuffIds":["child"],"source":{"decodedDetailPath":"custom/parent.json"}}}}
                """);
            File.WriteAllText(Path.Combine(folder,"custom/parent.json"),"""
                {"$type":"EnhancedAction+Data","asChildBuff":true,"childBuffId":{"value":"child"},"subType":"fire"}
                """);
            File.WriteAllText(Path.Combine(folder,"data/akedata/buff/items/parent.json"),"""
                {"$type":"EnhancedAction+Data","asChildBuff":true,"childBuffId":{"value":"child"},"subType":"pulse"}
                """);
            check(EnhancedChildEffectCatalog.Load(new(folder)).For("child") is [var direct] && direct.Get("element") is EvidenceText { Value:"fire" },
                "Resource-backed child lookup prefers the declared decoded detail path");
            File.Delete(Path.Combine(folder,"custom/parent.json"));
            check(EnhancedChildEffectCatalog.Load(new(folder)).For("child") is [var fallback] && fallback.Get("element") is EvidenceText { Value:"pulse" },
                "Missing declared detail falls back to the bundled decoded item");
        }
        finally { if(Directory.Exists(folder)) Directory.Delete(folder,true); }
    }
}
