using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Allocation;

internal static class IngestionSpecs
{
    public static void Run(Action<bool, string> check)
    {
        SkillIdentityCatalog identities = new(new Dictionary<string, string>(), new Dictionary<string, string>(),
            new Dictionary<string, RuntimeBuffDamageProfile>());
        Dictionary<string, EvidenceObject> objects = [];
        BattleIngestionResources resources = new()
        {
            Identities = identities, BuffMappings = new(objects, new Dictionary<string, IReadOnlyList<EvidenceObject>>(), new Dictionary<string, string>()),
            BuffRoots = objects, BuffNumbers = new Dictionary<string, string>(),
            Loadouts = new(objects, objects, objects, new(objects), identities, key => key),
            Metadata = _ => new("", "", "", new Dictionary<BigInteger, string>(), false),
            DamageUnits = _ => new Dictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>(),
            SkillProfile = _ => null, CharacterName = key => key, EnemyName = key => key, SkillName = key => key, Dungeon = _ => null,
        };
        CriticalAttributeObservation initial = new("chr_0001_alpha");
        initial.Values[9] = 0.2;
        initial.Lines[9] = 3;
        initial.Times[9] = 4;
        var critical = new Dictionary<string, CriticalAttributeObservation> { ["11"] = initial };
        BattleIngestionStream first = new(resources, criticalOverrides: critical);
        BattleIngestionStream second = new(resources, criticalOverrides: critical);
        first.Entities.CriticalAttributesByActor["11"].Values[9] = 0.4;
        check(initial.Values[9] == 0.2 && second.Entities.CriticalAttributesByActor["11"].Values[9] == 0.2,
            "Ingestion streams clone critical overrides independently of the caller");
        check(!first.Accept(1, "invalid") && first.TimestampClockOrigin is null && first.FirstContextMs is null,
            "Rows without a timestamp leave stream context untouched");
        check(!first.Accept(2, "GAME_TIMER_RESET source=CAPTURE_SESSION_START")
            && first.Entities.CriticalAttributesByActor.Count == 0 && second.Entities.CriticalAttributesByActor.Count == 1,
            "Capture reset clears this stream's critical state even without a timestamp");
        first.Accept(3, "[23:59:59.000] SQUAD [chr_0001_alpha_11 chr_0002_beta_12]");
        first.Accept(4, "[00:00:00.100] LIVE_TIMER_TICK elapsedMs=1100");
        first.Accept(5, "[23:59:59.500] ordinary");
        first.Accept(6, "[00:00:00.100] LIVE_TIMER_TICK elapsedMs=1100");
        check(first.FirstContextMs == 86_399_000 && first.LastContextMs == 86_400_100
            && first.TimerObservedTimes[4] == first.TimerObservedTimes[6],
            "Midnight replay keeps the fixed modulo-day coordinate rather than advancing days");
        first.Accept(7, "[00:00:00.200] SQUAD [chr_0001_alpha_11 chr_0002_beta_11]");
        check(first.Loadouts.SquadActorKeys.Count == 0 && first.PartyActorIds.SetEquals(new[] { "11", "12" }),
            "Ambiguous squad bindings clear current mappings while accumulated actor evidence remains");
        first.Accept(8, "[00:00:00.300] BUFF_START uid=7 id=buff_test owner=eny_0001_test ownerId=22 src=chr_0001_alpha srcId=11");
        var buff = first.Buffs.PendingRecord;
        first.Accept(9, "[00:00:00.400] HP_V2 #1 src=eny_0001_test atk=eny_0001_test tgt=chr_0001_alpha hit=20");
        check(buff is not null && ReferenceEquals(first.Buffs.PendingRecord, buff),
            "Rejected enemy HP rows preserve the pending BUFF across unified dispatch");
        first.Accept(10, "[00:00:00.500] HP_V2 #2 src=chr_0001_alpha atk=chr_0001_alpha tgt=eny_0001_test hit=100 eHP=1000");
        check(first.Buffs.PendingRecord is null && first.Hits.Hits.Count == 1
            && ReferenceEquals(first.Party, first.Loadouts.Party) && ReferenceEquals(first.Party, first.Hits.Party)
            && ReferenceEquals(first.Party, first.Buffs.Party),
            "Accepted HP clears pending BUFF and all handlers share the same party owner");
        first.Accept(11, "[00:00:00.600] BASELINE #2 1=40");
        check(first.Hits.Hits[0].Packet.Baseline?[1] == 40 && second.Hits.Hits.Count == 0 && second.Packets.BaselinesByCharacter.Count == 0,
            "Late packet evidence reaches the real hit without affecting another stream");
        var prefix = first.Ink.Capture();
        first.Accept(12, "invalid BB_SIMPLE_CALC seq=102 tick=1000 inst=7 ownerId=3 skill=" + InkProvenanceStream.Buff + " actionId=47 key=EntityBB_ink_damage valueA=0 valueB=200 final=200");
        var captured = EndfieldLogs.Core.Reporting.ReportCalculationInput.Capture(first).Ink!;
        check(prefix.Count == 2 && captured.Count == 3 && captured.After(2).Single().Number == 12
            && captured.After(2).Single().Fields["final"] == "200" && second.Ink.Capture().Count == 0,
            "Ingestion retains original ink indices even without timestamps, and captured prefixes remain independent");
    }
}
