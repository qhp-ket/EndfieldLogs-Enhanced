using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Resource lookups shared by the handlers within one ordered stream.</summary>
public sealed class BattleIngestionResources
{
    public required SkillIdentityCatalog Identities { get; init; }
    public required PacketBuffCatalog BuffMappings { get; init; }
    public required IReadOnlyDictionary<string, EvidenceObject> BuffRoots { get; init; }
    public required IReadOnlyDictionary<string, string> BuffNumbers { get; init; }
    public required LoadoutSnapshotParser Loadouts { get; init; }
    public required Func<string, SkillItemMetadata> Metadata { get; init; }
    public required Func<string, IReadOnlyDictionary<BigInteger, IReadOnlyList<SkillDamageUnit>>> DamageUnits { get; init; }
    public required Func<string, SkillHitProfile?> SkillProfile { get; init; }
    public required Func<string, string?> CharacterName { get; init; }
    public required Func<string, string?> EnemyName { get; init; }
    public required Func<string, string?> SkillName { get; init; }
    public required Func<string, DungeonContext?> Dungeon { get; init; }
    public Func<BuffRecord, EvidenceObject?>? EffectApproval { get; init; }
    public Func<Func<BuffRecord, EvidenceObject?>>? EffectApprovalFactory { get; init; }

    public static BattleIngestionResources Load(ResourceFiles files)
    {
        SkillResourceCatalog skills = new(files);
        var identities = skills.CreateIdentityCatalog();
        CharacterResourceCatalog characters = new(files);
        DisplayNameCatalog names = new(files, characters, identities);
        SkillProfileCatalog profiles = new(files, characters, identities);
        BuffRootCatalog roots = new(files);
        SkillDamageUnits units = new(skills, roots);
        SkillItemMetadataCatalog metadata = new(files);
        EquipmentCatalog equipment = new(files);
        DungeonCatalog dungeons = new(files);
        var approvalRegistry = EffectApprovalCatalog.Load(files);
        return new()
        {
            Identities = identities, BuffMappings = PacketBuffCatalog.Load(files, skills),
            BuffRoots = roots.Roots, BuffNumbers = skills.Buffs,
            Loadouts = new(new WeaponCatalog(files).Entries, equipment.Pieces, equipment.Suits,
                WeaponRefinementRules.Load(files), identities, names.Character),
            Metadata = key => { lock (metadata) return metadata.For(key); },
            DamageUnits = key => { lock (units) return units.For(key); },
            SkillProfile = profiles.ForHit, CharacterName = names.Character, EnemyName = names.Enemy,
            SkillName = names.Skill, Dungeon = dungeons.Resolve,
            EffectApprovalFactory = () =>
            {
                EffectApproval approval = new(approvalRegistry, roots.Roots, skills.Buffs, skills.Skills);
                return record => approval.Match(record);
            },
        };
    }
}
