using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

public sealed class LoadoutGroup(long timestampMs, int lineNumber, string reason, int index)
{
    public long TimestampMs { get; } = timestampMs;
    public int LineNumber { get; } = lineNumber;
    public string Reason { get; } = reason;
    public int Index { get; } = index;
    public Dictionary<string, EvidenceObject> Rows { get; } = new(StringComparer.Ordinal);
}

/// <summary>Ordered equipment evidence, owned together with hit and BUFF party state.</summary>
public sealed class LoadoutObservations
{
    private readonly LoadoutSnapshotParser parser;
    private readonly SkillIdentityCatalog skills;
    public PartyObservationState Party { get; }
    public Dictionary<string, EvidenceObject> WeaponOverrides { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, string> SquadActorKeys { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, IReadOnlyDictionary<string, BigInteger>> CharacterSkills { get; } = new(StringComparer.Ordinal);
    public List<LoadoutGroup> Groups { get; } = [];
    public LoadoutGroup? CurrentGroup { get; private set; }

    public LoadoutObservations(LoadoutSnapshotParser parser, SkillIdentityCatalog skills,
        PartyObservationState? party = null, IReadOnlyDictionary<string, EvidenceObject>? overrides = null)
    {
        this.parser = parser;
        this.skills = skills;
        Party = party ?? new();
        foreach (var (key, row) in overrides ?? new Dictionary<string, EvidenceObject>())
        {
            WeaponOverrides[key] = (EvidenceObject)BuffEvidence.Clone(row);
            Party.Loadouts[key] = (EvidenceObject)BuffEvidence.Clone(row);
            var weapon = CatalogValues.Text(CatalogValues.Or(row.Get("weapon_template"), new EvidenceText("")));
            if (weapon.Length > 0) Party.ActiveWeapons[key] = weapon;
        }
    }

    private LoadoutGroup Begin(long time, int line, string reason)
    {
        CurrentGroup = new(time, line, reason, Groups.Count);
        Groups.Add(CurrentGroup);
        return CurrentGroup;
    }

    public bool Observe(string line, int lineNumber, long timestampMs) =>
        ObserveGroup(line, lineNumber, timestampMs) || ObserveSnapshot(line, lineNumber, timestampMs)
        || ObserveCharacterSkills(line, lineNumber, timestampMs);

    public bool ObserveGroup(string line, int lineNumber, long timestampMs)
    {
        if (line.Contains("LOADOUT reason=", StringComparison.Ordinal))
        { Begin(timestampMs, lineNumber, TraceFields.Extract(line).GetValueOrDefault("reason") ?? ""); return true; }
        return false;
    }

    public void BeginGroup(string reason, int evidenceIndex, long timestampMs) => Begin(timestampMs, evidenceIndex, reason);

    public void ObserveSnapshot(LoadoutSlotObservation observation, int evidenceIndex, long timestampMs)
        => ApplySnapshot(parser.Slot(observation), false, evidenceIndex, timestampMs);

    public void ObserveSnapshot(LoadoutStatsObservation observation, int evidenceIndex, long timestampMs)
    {
        var allow = CurrentGroup?.TimestampMs == timestampMs && CurrentGroup.Reason is "SC_SYNC_CHAR_BAG_INFO" or "SC_SELF_SCENE_INFO";
        ApplySnapshot(parser.Stats(observation, allow), true, evidenceIndex, timestampMs);
    }

    private void ApplySnapshot(EvidenceObject? row, bool stats, int lineNumber, long timestampMs)
    {
        if (row is null) return;
        var character = CatalogValues.Text(row.Get("character_key"));
        EvidenceObject Initial() => new(stats ? new Dictionary<string, EvidenceValue> { ["character_key"] = new EvidenceText(character) } : new Dictionary<string, EvidenceValue>());
        var merged = LoadoutMerging.MergeTracked(Party.Loadouts.GetValueOrDefault(character) ?? Initial(), row);
        if (WeaponOverrides.TryGetValue(character, out var authoritative)) merged = LoadoutMerging.WithWeapon(merged, authoritative);
        Party.Loadouts[character] = merged;
        var group = CurrentGroup?.TimestampMs == timestampMs ? CurrentGroup : Begin(timestampMs, lineNumber, "");
        var groupRow = LoadoutMerging.Merge(group.Rows.GetValueOrDefault(character) ?? Initial(), row);
        group.Rows[character] = authoritative is null ? groupRow : LoadoutMerging.WithWeapon(groupRow, authoritative);
    }

    public void ObserveActive(string character, string weapon, IEnumerable<string> suits)
    {
        Party.ActiveWeapons[character] = CatalogValues.Text(CatalogValues.Or(Party.Loadouts.GetValueOrDefault(character)?.Get("weapon_template"), new EvidenceText(weapon)));
        Party.ActiveSuits[character] = suits.ToHashSet(StringComparer.Ordinal);
    }

    public bool ObserveSnapshot(string line, int lineNumber, long timestampMs)
    {
        var stats = line.Contains("LOADOUT_STATS ", StringComparison.Ordinal);
        var slot = !stats && line.Contains("LOADOUT slot=", StringComparison.Ordinal);
        if (stats || slot)
        {
            var allow = CurrentGroup?.TimestampMs == timestampMs && CurrentGroup.Reason is "SC_SYNC_CHAR_BAG_INFO" or "SC_SELF_SCENE_INFO";
            var row = stats ? parser.Stats(line, allowBoundGem: allow) : parser.Slot(line);
            ApplySnapshot(row, stats, lineNumber, timestampMs);
            if (slot)
            {
                var match = Regex.Match(line, @"\bLOADOUT\s+slot=\d+\s+char=(\S+).*?weaponTemplate=(\S+).*?equipSuit=(\{.*\})");
                if (match.Success)
                {
                    ObserveActive(match.Groups[1].Value, match.Groups[2].Value, TraceFields.LoadoutSuits(match.Groups[3].Value));
                }
            }
            return true;
        }
        return false;
    }

    public bool ObserveCharacterSkills(string line, int lineNumber, long timestampMs)
    {
        if (!line.Contains(" CHAR_SKILLS ", StringComparison.Ordinal)) return false;
        ApplyCharacterSkills(skills.ParseCharacterSkills(line), TraceFields.Token(line, "ownerId") ?? "", lineNumber, timestampMs);
        return true;
    }

    public void ObserveCharacterSkills(string owner, string ownerId, IEnumerable<(string Skill, string Level)> observations, int evidenceIndex, long timestampMs)
        => ApplyCharacterSkills(skills.CharacterSkills(owner, observations), ownerId, evidenceIndex, timestampMs);

    private void ApplyCharacterSkills(CharacterSkillLevels? parsed, string ownerId, int lineNumber, long timestampMs)
    {
        if (parsed is not null)
        {
            CharacterSkills[parsed.Owner] = parsed.Levels;
            var row = parser.CharacterSkills(parsed, ownerId, Party.Loadouts.GetValueOrDefault(parsed.Owner), SquadActorKeys);
            if (row is not null)
            {
                Party.Loadouts[parsed.Owner] = row;
                var group = Begin(timestampMs, lineNumber, "CHAR_SKILLS");
                foreach (var key in SquadActorKeys.Values.Distinct(StringComparer.Ordinal))
                    if (Party.Loadouts.TryGetValue(key, out var loadout)) group.Rows[key] = (EvidenceObject)BuffEvidence.Clone(loadout);
            }
        }
    }
}
