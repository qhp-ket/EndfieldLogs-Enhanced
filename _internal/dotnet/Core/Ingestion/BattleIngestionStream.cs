using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Tracing;
using EndfieldLogs.Core.Timing;
using EndfieldLogs.Core.Allocation;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Single-owner trace ingestion. Dispatch order is part of the evidence contract.</summary>
public sealed class BattleIngestionStream
{
    public EntityObservationState Entities { get; } = new();
    public PacketObservationState Packets { get; } = new();
    public PartyObservationState Party { get; } = new();
    public SkillObservationState Skills { get; } = new();
    public TimerObservationState Timers { get; }
    public LoadoutObservations Loadouts { get; }
    public HitObservationState Hits { get; }
    public BuffInstanceState Buffs { get; }
    private readonly BuffPacketObservations buffPackets;
    private readonly BuffDynamicObservations dynamics;
    private readonly HitBuffLifecycleObservations lifecycle;
    public long? TimestampClockOrigin { get; private set; }
    public long? FirstContextMs { get; private set; }
    public long? LastContextMs { get; private set; }
    public HashSet<string> PartyActorIds { get; } = new(StringComparer.Ordinal);
    public Dictionary<int, long> TimerObservedTimes { get; } = [];
    public TimerEvidenceCollector OfficialTimerCollector { get; } = new();
    public int EvidenceCount { get; private set; }
    public InkObservationLog Ink { get; } = new();
    public bool HasIdentityInference { get; private set; }

    public BattleIngestionStream(BattleIngestionResources resources,
        IReadOnlyDictionary<string, EvidenceObject>? loadoutOverrides = null,
        IReadOnlyDictionary<string, CriticalAttributeObservation>? criticalOverrides = null)
    {
        foreach (var (key, row) in criticalOverrides ?? new Dictionary<string, CriticalAttributeObservation>())
        {
            CriticalAttributeObservation copy = new(row.Template);
            foreach (var pair in row.Values) copy.Values[pair.Key] = pair.Value;
            foreach (var pair in row.Lines) copy.Lines[pair.Key] = pair.Value;
            foreach (var pair in row.Times) copy.Times[pair.Key] = pair.Value;
            Entities.CriticalAttributesByActor[key] = copy;
        }
        Timers = new(resources.Dungeon);
        Loadouts = new(resources.Loadouts, resources.Identities, Party, loadoutOverrides);
        Hits = new(resources.Identities, resources.DamageUnits, resources.SkillProfile,
            resources.CharacterName, resources.EnemyName, resources.SkillName, Entities, Packets, Party);
        Buffs = new(resources.BuffMappings, resources.BuffRoots, resources.BuffNumbers,
            key => key is null ? null : resources.CharacterName(key),
            key => key is null ? null : resources.EnemyName(key), Party);
        buffPackets = new(Buffs, resources.EffectApprovalFactory?.Invoke() ?? resources.EffectApproval);
        dynamics = new(Buffs, resources.Metadata);
        lifecycle = new(Hits, Buffs);
    }

    /// <returns>Whether the row had a trace timestamp and entered the stream.</returns>
    public bool Accept(int lineNumber, string line)
    {
        EvidenceCount = Math.Max(EvidenceCount, lineNumber);
        Ink.Observe(lineNumber, line);
        HasIdentityInference |= line.Contains(" IDENTITY_INFERENCE ", StringComparison.Ordinal);
        // Session reset applies even to a row with no usable timestamp.
        if (line.Contains("GAME_TIMER_RESET source=CAPTURE_SESSION_START", StringComparison.Ordinal))
            Entities.CriticalAttributesByActor.Clear();
        if (TraceFields.PrefixedTimestampMs(line) is not long stamp)
        {
            OfficialTimerCollector.Observe(lineNumber, line, null);
            return false;
        }
        TimestampClockOrigin ??= stamp;
        const long day = 86_400_000;
        var difference = (stamp-TimestampClockOrigin.Value) % day;
        var time = TimestampClockOrigin.Value+(difference < 0 ? difference+day : difference);
        if (line.Contains("TIMER_", StringComparison.Ordinal) || line.Contains("GAME_INST_", StringComparison.Ordinal)
            || line.Contains("GAME_MECHANICS_TIME_FREEZE", StringComparison.Ordinal)) TimerObservedTimes[lineNumber] = time;
        FirstContextMs ??= time;
        LastContextMs = time;
        OfficialTimerCollector.Observe(lineNumber, line, time);
        PartyActorIds.UnionWith(ActorIdentity.PartyActorIds(line));
        if (line.Contains(" SQUAD ", StringComparison.Ordinal))
            ActorIdentity.ObserveSquad(line, PartyActorIds, Loadouts.SquadActorKeys);

        if (Entities.Observe(line, lineNumber, time)) return true;
        if (buffPackets.Observe(line, lineNumber, time)) return true;
        if (Loadouts.ObserveGroup(line, lineNumber, time)) return true;
        if (Timers.ObserveStage(line)) return true;
        if (Loadouts.ObserveSnapshot(line, lineNumber, time)) return true;
        if (Timers.ObserveTimer(line, time)) return true;
        if (Skills.Observe(line, lineNumber, time)) return true;
        if (Loadouts.ObserveCharacterSkills(line, lineNumber, time)) return true;
        if (dynamics.Observe(line, lineNumber, time)) return true;
        if (Buffs.ObserveBlackboard(line)) return true;
        if (Packets.Observe(line, lineNumber, time)) return true;
        lifecycle.Observe(line, lineNumber, time);
        return true;
    }

    public void Accept(IEnumerable<(int LineNumber, string Text)> batch)
    {
        foreach (var (line, text) in batch) Accept(line, text);
    }

    /// <summary>Structured families are connected incrementally; unknown families never silently disappear.</summary>
    public void Accept(int evidenceIndex, TraceEvent item)
    {
        if (item.Type == "damage") StructuredDamage.Accept(item, evidenceIndex, lifecycle, Packets);
        else if (item.Type is "damage_raw" or "damage_baseline" or "legacy_attribute_modifier" or "legacy_damage_modifier")
            HistoricalEvidenceWire.Accept(item, Packets, Buffs);
        else if (item.Type is "entity_stats" or "entity_attributes" or "entity_value" or "entity_die" or "ability_spawn")
            StructuredEntity.Accept(StructuredEntity.Observation(item), evidenceIndex, item.CapturedAtMs, Entities, PartyActorIds);
        else if (item.Type is "squad" or "actor_mapping") StructuredIdentity.Accept(item, PartyActorIds, Loadouts.SquadActorKeys);
        else if (item.Type == "identity_inference")
        {
            StructuredIdentity.Accept(item, PartyActorIds, Loadouts.SquadActorKeys);
            HasIdentityInference = true;
            Buffs.PendingRecord = null;
        }
        else if (item.Type == "character_skills") StructuredCharacterSkills.Accept(item, evidenceIndex, Loadouts);
        else if (item.Type is "loadout_group" or "loadout_slot" or "loadout_stats") StructuredLoadout.Accept(item, evidenceIndex, Loadouts);
        else if (item.Type is "skill_cast" or "atb" or "poise") StructuredSkill.Accept(item, evidenceIndex, Skills, Packets);
        else if (item.Type is "buff_start" or "buff_end" or "buff_blackboard") StructuredBuff.Accept(item, evidenceIndex, Buffs);
        else if (item.Type is "buff_creation" or "buff_origin" or "buff_enable" or "buff_keyword" or "buff_unresolved") StructuredBuffPacket.Accept(item, evidenceIndex, buffPackets);
        else if (item.Type is "blackboard_dynamic" or "buff_attribute_refresh" or "blackboard_skill_setting") StructuredDynamic.Accept(item, evidenceIndex, dynamics);
        else if (item.Type is "blackboard_calculation" or "blackboard_modify" or "blackboard_preset" or "ink_release") BlackboardWire.Observation(item);
        else if (item.Type is "clock_tick" or "clock_sync" or "time_freeze_request" or "time_freeze_state")
        {
            var clock = ClockWire.Observation(item);
            if (clock.Source == "GAME_TIMER_TICK") TimerObservedTimes[evidenceIndex] = item.CapturedAtMs;
            if (clock.Source is "GAME_TIMER_TICK" or "HEARTBEAT") Buffs.PendingRecord = null;
        }
        else if (item.Type is "battle_timer" or "official_timer" or "battle_phase" or "battle_timer_missing")
        {
            var (marker, fields) = TimerWire.Observation(item);
            if (marker == "GAME_TIMER_RESET" && fields.GetValueOrDefault("source") == "CAPTURE_SESSION_START") Entities.CriticalAttributesByActor.Clear();
            Timers.ObserveTimer(marker, fields, item.CapturedAtMs);
            if (item.Type != "battle_phase") TimerObservedTimes[evidenceIndex] = item.CapturedAtMs;
        }
        else if (item.Type is "game_instance" or "game_mechanics" or "scene_battle" or "battle_reset" or "session_warning")
        {
            var data = ContextWire.Observation(item);
            if (item.Type == "game_instance" || item.Type == "game_mechanics" && data.Get("action") is EvidenceText { Value: "time_freeze" })
                TimerObservedTimes[evidenceIndex] = item.CapturedAtMs;
        }
        else if (item.Type is "dungeon" or "contracts" or "battle_result")
        {
            var (marker, fields, tags) = StageWire.Observation(item);
            Timers.ObserveStage(marker, fields, tags);
        }
        else throw new NotSupportedException("Structured ingestion is not connected for " + item.Type);
        OfficialTimerCollector.Observe(evidenceIndex, item);
        Ink.Observe(evidenceIndex, item);
        EvidenceCount = Math.Max(EvidenceCount, evidenceIndex);
        TimestampClockOrigin ??= item.CapturedAtMs;
        FirstContextMs ??= item.CapturedAtMs;
        LastContextMs = item.CapturedAtMs;
    }

    public void Accept(IEnumerable<(int EvidenceIndex, TraceEvent Event)> batch)
    {
        foreach (var (index, item) in batch) Accept(index, item);
    }
}
