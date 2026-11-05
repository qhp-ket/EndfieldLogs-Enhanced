using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

internal static class HitSpecs
{
    public static void Run(Action<bool, string> check)
    {
        static (HitObservationState Hits, EntityObservationState Entities, PacketObservationState Packets) Stream(PartyObservationState? party = null)
        {
            EntityObservationState entities = new();
            PacketObservationState packets = new();
            SkillIdentityCatalog identities = new(new Dictionary<string, string>(), new Dictionary<string, string>(), new Dictionary<string, RuntimeBuffDamageProfile>());
            HitObservationState hits = new(identities, _ => new Dictionary<System.Numerics.BigInteger, IReadOnlyList<SkillDamageUnit>>(),
                _ => null, key => key, key => key, key => key, entities, packets, party);
            return (hits, entities, packets);
        }
        const string hitLine = " HP_V2 #1 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_target atkId=11 tgtId=22 skill=skill_test hit=100 eHP=1000";
        var first = Stream();
        var second = Stream();
        first.Entities.Observe(" ENTITY_STATS id=11 template=chr_0001_alpha kind=character attrs=[9:0.2 10:0.5]", 1, 10);
        first.Hits.Observe(hitLine, 2, 20);
        var hit = first.Hits.Hits.Single();
        check(second.Hits.Hits.Count == 0 && second.Packets.HitsBySequence.Count == 0
            && second.Hits.LastEnemyHp.Count == 0, "HP streams isolate hits, evidence and enemy HP state");
        check(ReferenceEquals(first.Packets.HitsBySequence[1], hit.Packet), "A real hit owns the registered packet-evidence object");
        first.Packets.Observe(" BASELINE #1 1=5", 3, 30);
        check(hit.Packet.Baseline?[1] == 5, "Late baseline evidence updates the actual hit");
        first.Hits.Observe(hitLine.Replace("#1", "#2", StringComparison.Ordinal), 4, 40);
        var next = first.Hits.Hits[1];
        check(ReferenceEquals(hit.Packet.Baseline, next.Packet.Baseline), "Subsequent hits inherit the current character baseline");
        first.Packets.Observe(" BASELINE #2 1=7", 5, 50);
        check(hit.Packet.Baseline?[1] == 5 && next.Packet.Baseline?[1] == 7, "A new baseline preserves prior-hit evidence");
        first.Entities.Observe(" ENTITY_ATTR_UPDATE id=11 template=chr_0001_alpha kind=character attrs=[9:0.4]", 6, 60);
        check(hit.Critical?.Values[9] == 0.2 && first.Entities.CriticalAttributesByActor["11"].Values[9] == 0.4,
            "Partial critical updates preserve the recorded hit snapshot");

        var typed = Stream();
        var typedDynamic = new Dictionary<System.Numerics.BigInteger, double> { [14] = 0.5 };
        var typedCalculation = new Dictionary<System.Numerics.BigInteger, Dictionary<string, EvidenceValue>>
        { [14] = new() { ["scale"] = new EvidenceReal(2) } };
        DamageObservation observation = new()
        {
            Sequence = 1, Source = "chr_0001_alpha", Attacker = "chr_0001_alpha", Target = "eny_0001_target",
            SourceActor = "11", TargetActor = "22", Skill = "skill_test", Hit = 100, HitObserved = true,
            EnemyHp = 1000, EnemyHpObserved = true, Critical = 1, CriticalObserved = true,
            PacketSequence = 7, PacketSession = "session", Action = 14, UnitIndex = 0,
            Blackboards = new(null, typedDynamic, null, typedCalculation),
        };
        typed.Hits.Observe(observation, 2, 20);
        var typedHit = typed.Hits.Hits.Single();
        check(typedHit.Amounts.Value == 100 && typedHit.Action.UnitIndex == 0 && typedHit.Packet.PacketSequence == 7
            && typedHit.Packet.PacketSession == "session" && typed.Hits.Participants["chr_0001_alpha"].CriticalHits == 1,
            "Structured damage updates the existing counters, action and packet owner without trace text");
        typedDynamic[14] = 99; typedCalculation[14]["scale"] = new EvidenceReal(99);
        check(typedHit.Blackboards.Dynamic[14] == 0.5 && typedHit.Blackboards.Calculation[14]["scale"] is EvidenceReal { Value: 2 },
            "A caller can reuse structured blackboard containers without changing accepted hit evidence");
        typed.Hits.Observe(observation with { Sequence = 2, Hit = 2000, EnemyHp = 0 }, 3, 30);
        check(typed.Hits.Hits[^1].Amounts.Value == 1000 && typed.Hits.Hits[^1].Amounts.Overkill == 1000,
            "Structured damage preserves per-target overkill clipping");
        typed.Hits.Observe(observation with { Sequence = 3, Hit = 0, HitObserved = false, EnemyHpObserved = false }, 4, 40);
        check(typed.Hits.Hits[^1].Amounts.PacketHit is null && !typed.Hits.Hits[^1].Amounts.EnemyHpObserved
            && typed.Hits.Hits[^1].Amounts.Source == "missing_packet_hit",
            "Structured missing values stay distinct from observed zero");
        typed.Hits.Observe(observation with { Source = "chr_0002_beta" }, 5, 50);
        check(typed.Hits.Hits.Count == 3 && typed.Hits.Unresolved.Single().Reason == "conflicting_damage_actor",
            "Structured conflicting actor evidence remains unresolved");
        first.Hits.Observe(hitLine, 7, 70);
        first.Packets.Observe(" BASELINE #1 1=9", 8, 80);
        check(hit.Packet.Baseline?[1] == 5 && first.Hits.Hits[2].Packet.Baseline?[1] == 9,
            "Repeated sequence numbers route late evidence to the newest hit only");

        Dictionary<string, string> numbers = [];
        Dictionary<string, EvidenceObject> roots = [];
        PacketBuffCatalog buffsCatalog = new(new Dictionary<string, EvidenceObject>(), new Dictionary<string, IReadOnlyList<EvidenceObject>>(), numbers);
        PartyObservationState party = new();
        var shared = Stream(party);
        BuffInstanceState buffs = new(buffsCatalog, roots, numbers, key => key, key => key, party);
        try
        {
            _ = new HitBuffLifecycleObservations(first.Hits, buffs);
            throw new InvalidOperationException("Mismatched party owners were accepted");
        }
        catch (ArgumentException) { check(true, "Lifecycle assembly rejects different party owners"); }
        HitBuffLifecycleObservations lifecycle = new(shared.Hits, buffs);
        var loadout = (EvidenceObject)EvidenceJson.Parse("{}");
        party.Loadouts["chr_0001_alpha"] = loadout;
        party.ActiveWeapons["chr_0001_alpha"] = "wpn_test";
        party.ActiveSuits["chr_0001_alpha"] = ["suit_test"];
        first.Hits.Loadouts["chr_0001_alpha"] = loadout;
        lifecycle.Observe(" BUFF_START uid=7 id=buff_test owner=eny_0001_target ownerId=22 src=chr_0001_alpha srcId=11", 1, 100);
        var previousBuff = buffs.ActiveByUid["7"];
        check(ReferenceEquals(buffs.Party.Participants, shared.Hits.Participants)
            && shared.Hits.Participants["chr_0001_alpha"].Count == 0, "BUFF-only characters share zero-damage participant counters");
        lifecycle.Observe(" HP_V2 #9 src=eny_0001_target atk=eny_0001_target tgt=chr_0001_alpha hit=100", 2, 101);
        check(ReferenceEquals(buffs.PendingRecord, previousBuff), "Rejected HP rows preserve the pending BUFF object");
        lifecycle.Observe(hitLine.Replace("chr_0001_alpha", "chr_0002_beta", StringComparison.Ordinal), 3, 102);
        check(party.Loadouts.Count == 0 && buffs.ActiveWeapons.Count == 0 && buffs.ActiveSuits.Count == 0
            && first.Hits.Loadouts.Count == 1, "An outsider hit invalidates shared equipment within its own stream only");
        check(buffs.PendingRecord is null && previousBuff.SourceWeaponTemplate == "wpn_test",
            "Accepted HP clears the pending pointer while prior BUFF equipment evidence stays frozen");
        lifecycle.Observe(" BUFF_START uid=8 id=buff_test owner=eny_0001_target ownerId=22 src=chr_0001_alpha srcId=11", 4, 103);
        var typedPending = buffs.PendingRecord;
        lifecycle.Observe(observation with { Source = "eny_0001_target", Attacker = "eny_0001_target", Target = "chr_0001_alpha" }, 5, 104);
        check(ReferenceEquals(buffs.PendingRecord, typedPending), "Structured enemy-outgoing damage preserves pending BUFF lifecycle");
        lifecycle.Observe(observation, 6, 105);
        check(buffs.PendingRecord is null, "Structured accepted damage uses the same pending-BUFF boundary");

        var rawCalculation = (EvidenceObject)EvidenceJson.Parse("""{"nested":{"value":1}}""");
        var unit = new EvidenceObject(new Dictionary<string, EvidenceValue>
        {
            ["index"] = new EvidenceInteger(0), ["damageCalculation"] = rawCalculation,
        });
        var profile = new OfficialDamageProfile("skill_test", new EvidenceObject(new Dictionary<string, EvidenceValue>()),
            new Dictionary<string, IReadOnlyList<EvidenceObject>> { ["1"] = new[] { unit } });
        var projection = SkillDamageUnits.Project("skill_test", profile, null)[1].Single();
        check(projection.Calculation is not null && !ReferenceEquals(projection.Calculation.Get("nested"), rawCalculation.Get("nested")),
            "Damage calculation projection owns nested evidence containers");

        var directory = Path.Combine(Path.GetTempPath(), "endfield-hit-resource-spec-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        try
        {
            ResourceFiles resources = new(directory);
            SkillDamageUnits units = new(new SkillResourceCatalog(resources), new BuffRootCatalog(resources));
            var cached = units.For("missing");
            check(ReferenceEquals(cached, units.For("missing")), "Damage action lookup reuses the current resource observation");
            for (var index = 0; index < 4096; index++) units.For("missing_" + index);
            check(!ReferenceEquals(cached, units.For("missing")), "Damage action caches have the reference 4096-key bound");
        }
        finally { Directory.Delete(directory, recursive: true); }
    }
}
