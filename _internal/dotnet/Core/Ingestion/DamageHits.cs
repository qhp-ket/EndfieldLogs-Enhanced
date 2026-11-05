using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

public sealed record HitIdentity(BigInteger Sequence, int LineNumber, long TimestampMs,
    string Character, string CharacterName, string Target, string TargetName, string RawSkill,
    string Skill, string SkillName, string? TargetActor, string? SourceActor);
public sealed record HitAction(BigInteger? SkillLevel, BigInteger? TemplateInteger, string? EventInstance,
    string? EventOwner, BigInteger? ClientTick, BigInteger? Action, BigInteger? UnitIndex,
    BigInteger? OriginalTemplate, BigInteger? Group, string Family, BigInteger? PartInstance, BigInteger HitIndex,
    string? PacketOwner, BigInteger? PacketGeneration);
public sealed record HitAmounts(BigInteger Value, BigInteger RawValue, BigInteger? PacketHit,
    double? PacketRaw, double? PacketFinal, string Source, BigInteger EnemyHpAfter, bool EnemyHpObserved,
    BigInteger CriticalFlag, bool CriticalFlagObserved)
{
    public BigInteger Overkill => BigInteger.Max(0, RawValue - Value);
}
public sealed record HitBlackboards(string? DynamicSignature, IReadOnlyDictionary<BigInteger, double> Dynamic,
    string? CalculationSignature, IReadOnlyDictionary<BigInteger, Dictionary<string, EvidenceValue>> Calculation);
public sealed record HitEntityBinding(bool Unresolved, EntityStatsSnapshot? Snapshot);
public sealed class TargetHitStats(bool unresolved, EntityStatsSnapshot? snapshot)
{
    public bool Unresolved { get; } = unresolved;
    public EntityStatsSnapshot? Snapshot { get; } = snapshot;
    public double? Defense { get; } = snapshot?.Attributes.TryGetValue(3, out var value) == true ? value : null;
    public IReadOnlyDictionary<string, double> ResistanceScalars { get; } = Select(snapshot,
        [("physical", 4), ("fire", 5), ("pulse", 6), ("cryst", 7), ("natural", 48), ("ether", 60)]);
    public IReadOnlyDictionary<string, double> ResistancePoints { get; } = Select(snapshot,
        [("physical", 94), ("natural", 95), ("cryst", 96), ("pulse", 97), ("fire", 98), ("ether", 99)]);

    private static IReadOnlyDictionary<string, double> Select(EntityStatsSnapshot? snapshot, (string Name, int Attribute)[] attributes) =>
        snapshot is null ? new Dictionary<string, double>() : attributes.Where(pair => snapshot.Attributes.ContainsKey(pair.Attribute))
            .ToDictionary(pair => pair.Name, pair => snapshot.Attributes[pair.Attribute], StringComparer.Ordinal);
}
public sealed record SkillHitProfile(BigInteger? Group, string? Family);
public sealed record UnresolvedDamageHit(int LineNumber, long TimestampMs, string? SourceActor,
    string? AttackerActor, string? TargetActor, string? RawSkill, string? PacketHit, string Reason);

/// <summary>One hit owns its packet evidence; late packet rows update this same object.</summary>
public sealed class DamageHit(HitIdentity identity, HitAction action, HitAmounts amounts,
    HitBlackboards blackboards, HitPacketEvidence packet, string? element, SkillDamageUnit? staticUnit,
    TargetHitStats targetStats, HitEntityBinding attackerStats, CriticalAttributeObservation? critical)
{
    public HitIdentity Identity { get; } = identity;
    public HitAction Action { get; } = action;
    public HitAmounts Amounts { get; } = amounts;
    public HitBlackboards Blackboards { get; } = blackboards;
    public HitPacketEvidence Packet { get; } = packet;
    public string? Element { get; } = element;
    public string? School { get; } = HitDamageClassification.School(element);
    public SkillDamageUnit? StaticUnit { get; } = staticUnit;
    public ArtsStrengthDamage ArtsStrength { get; } = HitDamageClassification.ArtsStrength(null, staticUnit?.StaticMask, staticUnit?.StaticMaskSource);
    public TargetHitStats TargetStats { get; } = targetStats;
    public HitEntityBinding AttackerStats { get; } = attackerStats;
    public CriticalAttributeObservation? Critical { get; } = critical;
}

public sealed class ParticipantHitTotals(string character, string name)
{
    public string Character { get; } = character;
    public string Name { get; internal set; } = name;
    public BigInteger Damage { get; internal set; }
    public BigInteger Maximum { get; internal set; }
    public BigInteger CriticalHits { get; internal set; }
    public BigInteger Count { get; internal set; }
}
public sealed class SkillHitTotals(string character, string characterName, string skill, string name)
{
    public string Character { get; } = character;
    public string CharacterName { get; } = characterName;
    public string Skill { get; } = skill;
    public string Name { get; } = name;
    public BigInteger Damage { get; internal set; }
    public BigInteger Maximum { get; internal set; }
    public BigInteger Count { get; internal set; }
    public BigInteger CastCount { get; internal set; }
}
