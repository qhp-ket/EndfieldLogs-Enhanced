using System.Numerics;

namespace EndfieldLogs.Core.Ingestion;

public sealed record LoadoutSlotObservation(string Character)
{
    public BigInteger Slot { get; init; }
    public BigInteger? CharacterLevel { get; init; }
    public BigInteger Potential { get; init; }
    public string? WeaponInstance { get; init; }
    public string Weapon { get; init; } = "";
    public BigInteger? WeaponLevel { get; init; }
    public BigInteger? Refine { get; init; }
    public BigInteger Breakthrough { get; init; }
    public string SuitBlob { get; init; } = "";
    public string? EquipmentBlob { get; init; }
    public IReadOnlyList<string> SkillIds { get; init; } = [];
    public IReadOnlyList<string>? UnplacedIds { get; init; }
    public bool? EquipmentComplete { get; init; }
}

public sealed record LoadoutStatsObservation(string Character)
{
    public string Weapon { get; init; } = "";
    public string WeaponInstance { get; init; } = "";
    public BigInteger? WeaponLevel { get; init; }
    public string? RefineStatsBlob { get; init; }
    public string? SourceSkillsBlob { get; init; }
    public BigInteger BaseAttack { get; init; }
    public BigInteger BaseAttackLv1 { get; init; }
    public BigInteger BaseAttackMax { get; init; }
    public string GemInstance { get; init; } = "";
    public string GemWeapon { get; init; } = "";
    public string? GemTemplate { get; init; }
    public string TermsBlob { get; init; } = "";
}
