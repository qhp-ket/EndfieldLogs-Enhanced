using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

internal static class PacketAllocationSpecs
{
    private static EvidenceObject Obj(string json) => (EvidenceObject)EvidenceJson.Parse(json);
    private static EvidenceObject Change(EvidenceObject row, params (string Key, EvidenceValue Value)[] values)
    {
        var fields = new Dictionary<string, EvidenceValue>(row.Fields, StringComparer.Ordinal);
        foreach (var (key, value) in values) fields[key] = value;
        return new(fields);
    }
    private static EvidenceText Text(string value) => new(value);
    private static EvidenceInteger Number(int value) => new(value);

    public static void Run(Action<bool, string> check)
    {
        check(PythonDecimalRounding.Round(2.675, 2) == 2.67 && PythonDecimalRounding.Round(1.2345, 3) == 1.234,
            "Decimal ties use the exact input binary value rather than scaling an already rounded double");
        check(BitConverter.DoubleToInt64Bits(PythonDecimalRounding.Round(-0.0000001, 6)) == long.MinValue
            && PythonDecimalRounding.Round(double.Epsilon, 323) == 0 && PythonDecimalRounding.Round(double.MaxValue, 6) == double.MaxValue,
            "Rounding preserves negative zero and handles subnormal and maximum finite magnitudes");
        check(PythonSortedJson.Serialize(Obj("""{"b":1.0,"a":["中文",true,null,"\u0001"]}""")) == "{\"a\": [\"中文\", true, null, \"\\u0001\"], \"b\": 1.0}",
            "Condition identities preserve Python sorted JSON separators, UTF-8 text and float spelling");
        var keyedA = EffectIdentity.PacketGuard(Obj("""{"zone":"vuln_taken","rate":0.1,"bb_key":"v"}"""));
        var keyedB = EffectIdentity.PacketGuard(Obj("""{"zone":"vuln_taken","rate":0.8,"bb_key":"v"}"""));
        check(keyedA.Equals(keyedB) && keyedA.GetHashCode() == keyedB.GetHashCode(),
            "The same observed parameter guard matches across rate changes");
        check(!EffectIdentity.PacketGuard(Obj("""{"zone":"vuln_taken","rate":0.1}""")).Equals(
            EffectIdentity.PacketGuard(Obj("""{"zone":"vuln_taken","rate":0.8}"""))),
            "Effects lacking parameter identity retain their numerical rate in the guard");
        check(EffectIdentity.Row(Obj("""{"rate":0.20000001,"rdps_whitelist_keys":["b","a"],"external_rdps_allowed":true}""")).Equals(
            EffectIdentity.Row(Obj("""{"rate":0.20000002,"rdps_whitelist_keys":["a","b"],"external_rdps_allowed":1}"""))),
            "Row identity rounds at six places, sorts whitelist keys and preserves Python numeric equality");
        var aliases = Obj("""{"uid":"a","uid_aliases":["a","b",null,"",false,0,1]}""");
        check(EffectIdentity.WindowUids(aliases).SetEquals(new[] { "a", "b", "1" })
            && PacketAllocationEvidence.MatchesUids(aliases, new HashSet<string> { "b" })
            && !PacketAllocationEvidence.MatchesUids(aliases, new HashSet<string> { "other" })
            && PacketAllocationEvidence.MatchesUids(Obj("{}"), new HashSet<string> { "a" }),
            "Aliases deduplicate truthy identities while absent aliases do not fabricate packet exclusion");
        check(PacketAllocationEvidence.AllowedAttributes(new EvidenceValue[] { Text("32:0.2"), Text("50:0.1"), Text("94:10"), Text("bad") })
            .SetEquals(new[] { ("dmg_inc", "all"), ("dmg_inc", "physical") }),
            "Only known attribute-to-zone mappings are admitted from packet tokens");
        var raw = Obj("""{"atk_zones":[1,1.2,1,1.3,1.4],"def_zones":[1,1.5,1,1,1,1.6]}""");
        check(PacketAllocationEvidence.Bucket("amp", raw) == 1.3 && PacketAllocationEvidence.Bucket("fragile", raw) == 1.6
            && PacketAllocationEvidence.Bucket("atk", raw) is null && PacketAllocationEvidence.Bucket("combo", Obj("""{"atk_zones":[1]}""")) is null,
            "Damage pack zones use their explicit attacker and defender slot positions");
        check(double.IsPositiveInfinity(PacketAllocationEvidence.Bucket("dmg_inc", Obj("""{"atk_zones":[0,"inf"]}"""))!.Value)
            && PacketAllocationEvidence.Bucket("dmg_inc", Obj("""{"atk_zones":[0,true]}""")) == 1,
            "Raw bucket conversion retains nonfinite values and booleans for later allocation validation");
        var hit = Obj("""{"character_key":"chr_a","source_actor_id":"a1","target_enemy_key":"enemy","target_actor_id":"e1","ts_ms":1000,"line_no":10,"skill_key":"skill","packet_modifier_uids":{"defender":[],"attacker":[]}}""");
        var record = Obj("""{"uid":"u1","target_enemy_key":"enemy","target_actor_id":"e1","ts_ms":900,"line_no":1,"event_key":"buff","raw_event_key":"123","raw_duration_ms":500}""");
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { record }).SetEquals(new[] { "buff", "123" }),
            "Explicit same-actor lifetime evidence activates both canonical and raw BUFF identities");
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { Change(record, ("target_actor_id", Text("e2"))) }).Count == 0,
            "A reused enemy template never crosses concrete actor identities");
        var unknownActor = Change(record, ("target_actor_id", EvidenceNull.Value));
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { unknownActor }).Count == 0
            && PacketAllocationEvidence.ActiveTargetBuffs(Change(hit, ("packet_modifier_uids", Obj("""{"defender":["u1"]}"""))), new[] { unknownActor }).Count == 2,
            "Unknown actor matching requires the current hit's exact packet UID");
        var ended = Change(record, ("end_ts_ms", Number(1000)), ("end_line_no", Number(10)));
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { ended }).Count == 0
            && PacketAllocationEvidence.ActiveTargetBuffs(Change(hit, ("line_no", Number(9))), new[] { ended }).Count == 2,
            "Explicit ends are exclusive at the end line while earlier same-millisecond hits remain active");
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { Change(record, ("raw_duration_ms", Number(100))) }).Count == 0
            && PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { Change(record, ("snapshot_end_ts_ms", Number(1000)), ("snapshot_end_line_no", Number(10))) }).Count == 0,
            "Nominal duration and snapshot replacement independently bound condition activation");
        var indefinite = Change(record, ("raw_duration_ms", EvidenceNull.Value));
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { indefinite }).Count == 0
            && PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { Change(indefinite, ("lifetime_mode", Text("Infinity"))) }).Count == 2,
            "Unknown lifetimes require fresh packet proof unless the current typed lifetime is Infinity");
        var attacker = Change(record, ("target_enemy_key", EvidenceNull.Value), ("target_character_key", Text("chr_a")), ("target_actor_id", Text("a1")));
        check(PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { attacker }, "attacker").Count == 2
            && PacketAllocationEvidence.ActiveTargetBuffs(hit, new[] { attacker }).Count == 0,
            "Attacker condition proof uses the source actor and stays isolated from defender proof");
        var window = Obj("""{"uid":"u1","uid_aliases":["u2"],"target_character_key":"enemy","start_ts_ms":900,"end_ts_ms":1100,"start_line_no":1,"event_key":"buff","zone_effects":[{"zone":"vuln_taken","rate":0.1,"bb_key":"v"},{"zone":"vuln_taken","rate":0.4,"bb_key":"v"},{"zone":"atk","rate":0.2}]}""");
        var original = EvidenceJsonSignature.Sorted(window);
        var matches = PacketAllocationEvidence.MatchDefender(hit, new[] { window }, new HashSet<string> { "u2" });
        check(matches.Signatures.Count == 1 && matches.Signatures.Contains(keyedA)
            && matches.Windows[0].Get("_buff_enabled_at_hit") is EvidenceBoolean { Value: true },
            "Defender matching follows aliases, evaluates observable windows and deduplicates equivalent guards");
        var sameSkill = Change(window, ("start_ts_ms", Number(1000)), ("event_key", Text("skill")));
        check(PacketAllocationEvidence.MatchDefender(hit, new[] { sameSkill }, new HashSet<string> { "u1" }).Signatures.Count == 0
            && PacketAllocationEvidence.MatchDefender(hit, new[] { Change(window, ("skill_family_key", Text("different"))) }, new HashSet<string> { "u1" }).Signatures.Count == 0,
            "Same-tick self-skill creation and mismatching skill families cannot prove a defender modifier");
        var required = Change(window, ("requires_enable_observation", new EvidenceBoolean(true)));
        var unresolved = PacketAllocationEvidence.MatchDefender(hit, new[] { required }, new HashSet<string> { "u1" });
        check(unresolved.Signatures.Count == 0 && unresolved.Windows[0].Get("rdps_unresolved_enable_evidence") is EvidenceBoolean { Value: true }
            && EvidenceJsonSignature.Sorted(window) == original && required.Get("rdps_unresolved_enable_evidence") is EvidenceNull,
            "Unobservable enable state returns owned diagnostics without mutating source windows");
    }
}
