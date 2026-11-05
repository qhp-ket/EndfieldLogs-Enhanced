using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Ordered HP observations and counters. Entity and packet states belong to the same ingestion stream.</summary>
public sealed class HitObservationState(SkillIdentityCatalog identities,
    Func<string, IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>> unitsFor,
    Func<string, SkillHitProfile?> profileFor, Func<string, string?> characterName,
    Func<string, string?> enemyName, Func<string, string?> skillName,
    EntityObservationState entities, PacketObservationState packets, PartyObservationState? party = null)
{
    public PartyObservationState Party { get; } = party ?? new();
    public List<DamageHit> Hits { get; } = [];
    public Dictionary<BigInteger, DamageHit> HitsBySequence { get; } = [];
    public List<UnresolvedDamageHit> Unresolved { get; } = [];
    public Dictionary<string, BigInteger> EnemyCounts { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, BigInteger> LastEnemyHp { get; } = new(StringComparer.Ordinal);
    public List<string> Roster => Party.Roster;
    public Dictionary<string, ParticipantHitTotals> Participants => Party.Participants;
    public Dictionary<(string Character, string Skill), SkillHitTotals> Skills { get; } = [];
    public Dictionary<string, EvidenceObject> Loadouts => Party.Loadouts;
    public Dictionary<string, HashSet<string>> ActiveSuits => Party.ActiveSuits;
    public Dictionary<string, string> ActiveWeapons => Party.ActiveWeapons;

    private static string? ActorId(string? text) => Regex.IsMatch(text ?? "", @"\A[1-9]\d*\z") ? text : null;

    public static string EnemyHpKey(string target, string? actorId) => ActorId(actorId) is { } actor ? "actor:" + actor : "template:" + target;
    public static BigInteger CapOverkill(BigInteger hit, BigInteger? enemyHpAfter, BigInteger? previousHp)
    {
        if (hit <= 0 || enemyHpAfter is null || previousHp is null) return hit;
        if (previousHp <= 0 && enemyHpAfter <= 0) return 0;
        return enemyHpAfter <= 0 && previousHp > 0 ? BigInteger.Min(hit, previousHp.Value) : hit;
    }

    public bool Observe(string line, int lineNumber, long timestampMs)
    {
        if (!line.Contains(" HP_V2 ", StringComparison.Ordinal)) return false;
        return Apply(DamageObservation.FromLegacy(line), lineNumber, timestampMs, ownBlackboards: false);
    }

    public bool Observe(DamageObservation observation, int lineNumber, long timestampMs)
        => Apply(observation, lineNumber, timestampMs, ownBlackboards: true);

    internal bool ObserveOwned(DamageObservation observation, int lineNumber, long timestampMs)
        => Apply(observation, lineNumber, timestampMs, ownBlackboards: false);

    private bool Apply(DamageObservation observation, int lineNumber, long timestampMs, bool ownBlackboards)
    {
        var source = ActorIdentity.CharacterKey(observation.Source);
        var attacker = ActorIdentity.CharacterKey(observation.Attacker);
        if (source is null && attacker is null && ActorIdentity.EnemyKey(observation.Source, observation.Attacker) is not null)
            return true;
        var character = source ?? attacker;
        var target = ActorIdentity.EnemyKey(observation.Target);
        var conflict = source is not null && attacker is not null && source != attacker;
        if (character is null || target is null || conflict)
        {
            Unresolved.Add(new(lineNumber, timestampMs, observation.Source, observation.Attacker,
                observation.Target, observation.Skill, observation.UnresolvedHitText ?? (observation.HitObserved
                    ? observation.Hit.ToString(System.Globalization.CultureInfo.InvariantCulture) : null),
                conflict ? "conflicting_damage_actor" : "unresolved_damage_actor"));
            return true;
        }
        EnemyCounts[target] = EnemyCounts.GetValueOrDefault(target) + 1;
        var name = characterName(character) is { Length: > 0 } resolvedName ? resolvedName : character;
        var rawValue = observation.Hit;
        BigInteger? packetHit = observation.HitObserved ? rawValue : null;
        var hpObserved = observation.EnemyHpObserved;
        var hpAfter = observation.EnemyHp;
        var targetActor = ActorId(observation.TargetActor);
        var sourceActor = ActorId(observation.SourceActor);
        var hpKey = EnemyHpKey(target, targetActor);
        var value = CapOverkill(rawValue, hpObserved ? hpAfter : null,
            LastEnemyHp.TryGetValue(hpKey, out var previous) ? previous : null);
        var valueSource = packetHit is null ? "missing_packet_hit" : value != rawValue ? "packet_hit_overkill_capped" : "packet_hit";
        if (hpObserved) LastEnemyHp[hpKey] = hpAfter;
        var rawSkill = observation.Skill is { Length: > 0 } raw ? raw : "unknown_skill";
        var action = observation.Action;
        var unitIndex = observation.UnitIndex;
        var skill = identities.HitFromTemplate(rawSkill, character, observation.TemplateType, action, unitIndex)
            ?? identities.CanonicalHitSkill(rawSkill, character);
        var profile = profileFor(identities.CanonicalPacketSkill(skill));
        var group = profile?.Group;
        var family = identities.FamilyKey(skill, profile?.Family);
        if (skill == "sk_wpn_lance_0010") { group = 2; family = "chr_0015_lifeng_ultimate_skill"; }
        var sequence = observation.Sequence ?? Hits.Count + 1;
        var packet = new HitPacketEvidence(character, observation.PacketSequence, observation.PacketSession)
        {
            Baseline = packets.BaselinesByCharacter.GetValueOrDefault(character),
        };
        var units = unitsFor(skill);
        var element = HitDamageClassification.Element(units, action, unitIndex);
        SkillDamageUnit? staticUnit = null;
        if (action is BigInteger a && unitIndex is BigInteger i && units.TryGetValue(a, out var candidates))
        {
            var exact = candidates.Where(unit => unit.Index is EvidenceInteger index && index.Value == i && unit.Attribute == "hp").ToArray();
            if (exact.Length == 1) staticUnit = exact[0] with { Calculation = exact[0].Calculation is { } calc ? SkillDamageUnits.CopyObject(calc) : null };
        }
        var criticalFlag = observation.Critical;
        var owner = ActorId(observation.PacketOwner);
        if (owner is not null && TraceFields.OptionalInteger(owner) >= BigInteger.One << 64) owner = null;
        var hit = new DamageHit(new(sequence, lineNumber, timestampMs, character, name, target,
                enemyName(target) is { Length: > 0 } targetName ? targetName : target, rawSkill, skill,
                skillName(skill) is { Length: > 0 } resolvedSkill ? resolvedSkill : skill, targetActor, sourceActor),
            new(observation.SkillLevel, observation.TemplateInteger, ActorId(observation.EventInstance), ActorId(observation.EventOwner),
                observation.ClientTick, action, unitIndex, observation.OriginalTemplate, group, family, observation.PartInstance,
                observation.HitIndex, owner, observation.PacketGeneration),
            new(value, rawValue, packetHit, observation.Raw, observation.Final, valueSource, hpAfter, hpObserved,
                criticalFlag, observation.CriticalObserved),
            ownBlackboards ? observation.OwnBlackboards() : observation.Blackboards, packet, element, staticUnit,
            BindTarget(entities.SnapshotAt(targetActor, timestampMs), target),
            BindAttacker(entities.SnapshotAt(sourceActor, timestampMs), character),
            CopyCritical(sourceActor is null ? null : entities.CriticalAttributesByActor.GetValueOrDefault(sourceActor)));
        Hits.Add(hit);
        HitsBySequence[sequence] = hit;
        packets.HitsBySequence[sequence] = packet;
        Party.DiscardStaleLoadout(character);
        var participant = Party.ObserveCharacter(character, name);
        participant.Damage += value;
        participant.Maximum = BigInteger.Max(participant.Maximum, value);
        if (!criticalFlag.IsZero) participant.CriticalHits++;
        participant.Count++;
        if (!Skills.TryGetValue((character, skill), out var skillTotals)) Skills[(character, skill)] = skillTotals = new(character, name, skill, hit.Identity.SkillName);
        skillTotals.Damage += value;
        skillTotals.Maximum = BigInteger.Max(skillTotals.Maximum, value);
        skillTotals.Count++;
        if (hit.Action.HitIndex == 1) skillTotals.CastCount++;
        // The reference pipeline continues after successful lifecycle/HP rows;
        // unresolved and enemy-outgoing rows use its early-consumed return instead.
        return false;
    }

    private static TargetHitStats BindTarget(EntityStatsSnapshot? snapshot, string target) =>
        snapshot is null ? new(false, null) : snapshot.Template != target ? new(true, null) : new(false, snapshot);
    private static HitEntityBinding BindAttacker(EntityStatsSnapshot? snapshot, string character) =>
        snapshot is null ? new(false, null) : snapshot.Template != character || snapshot.Kind != "character"
            ? new(true, null) : new(false, snapshot.Attributes.Count > 0 ? snapshot : null);
    private static CriticalAttributeObservation? CopyCritical(CriticalAttributeObservation? value)
    {
        if (value is null) return null;
        var copy = new CriticalAttributeObservation(value.Template);
        foreach (var (key, item) in value.Values) copy.Values[key] = item;
        foreach (var (key, item) in value.Lines) copy.Lines[key] = item;
        foreach (var (key, item) in value.Times) copy.Times[key] = item;
        return copy;
    }
}
