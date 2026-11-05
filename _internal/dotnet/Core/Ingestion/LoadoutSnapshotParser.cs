using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

/// <summary>Observed slot and stat rows; all catalog data and skill identities belong to the ingestion context.</summary>
public sealed class LoadoutSnapshotParser(IReadOnlyDictionary<string, EvidenceObject> weapons,
    IReadOnlyDictionary<string, EvidenceObject> equipment, IReadOnlyDictionary<string, EvidenceObject> suits,
    WeaponRefinementRules refinement, SkillIdentityCatalog skills, Func<string, string?> characterName)
{
    private static readonly EvidenceObject Empty = new(new Dictionary<string, EvidenceValue>());
    private static EvidenceValue Text(string? value) => value is null ? EvidenceNull.Value : new EvidenceText(value);
    private static EvidenceValue Number(BigInteger? value) => value is BigInteger number ? new EvidenceInteger(number) : EvidenceNull.Value;
    private static BigInteger Coerce(string? value) => TraceFields.OptionalInteger(value) ?? BigInteger.Zero;
    private static EvidenceValue Or(EvidenceValue value, EvidenceValue fallback) => CatalogValues.Truth(value) ? value : fallback;
    private static EvidenceObject Blackboard(string? blob) => new(TraceFields.BlackboardAssignments(blob).ToDictionary(pair => pair.Key,
        pair => pair.Value is double number ? (EvidenceValue)new EvidenceReal(number) : new EvidenceText((string)pair.Value), StringComparer.Ordinal));
    private static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) => new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));

    public EvidenceValue SelectedBaseAttack(string weapon, BigInteger? level) => weapons.TryGetValue(weapon, out var meta)
        && meta.Get("base_atk_values") is EvidenceArray values && level is BigInteger index && index > 0 && index <= values.Items.Count
            ? values.Items[(int)index-1] : EvidenceNull.Value;

    public static EvidenceArray SourceSkills(string? blob)
    {
        List<EvidenceValue> result = [];
        foreach (var entry in TraceFields.SplitTopLevel(blob ?? "", ';'))
        {
            var colon = entry.IndexOf(':');
            if (colon < 0) continue;
            var rest = entry[(colon+1)..];
            var level = Regex.Match(rest, @"(?:^|:)level=([^:]+)");
            var potential = Regex.Match(rest, @"(?:^|:)potentialLv=([^:]+)");
            var bb = rest.IndexOf("bb={", StringComparison.Ordinal);
            var blackboard = bb >= 0 ? TraceFields.Braced("bb={" + rest[(bb+4)..], "bb") : null;
            result.Add(Object(("skill_id", new EvidenceText(entry[..colon].Trim())),
                ("level", level.Success ? Number(Coerce(level.Groups[1].Value)) : EvidenceNull.Value),
                ("potential_level", potential.Success ? Number(Coerce(potential.Groups[1].Value)) : EvidenceNull.Value),
                ("bb", Blackboard(blackboard))));
        }
        return new(result);
    }

    public EvidenceArray InlineEquipment(string line)
        => InlineEquipmentBlob(TraceFields.Braced(line, "equips"));

    public EvidenceArray InlineEquipmentBlob(string? equipmentBlob)
    {
        var blob = equipmentBlob ?? "";
        var matches = Regex.Matches(blob, @"\[(\d+)\]=");
        List<EvidenceValue> result = [];
        for (var index = 0; index < matches.Count; index++)
        {
            var match = matches[index];
            var end = index+1 < matches.Count ? matches[index+1].Index : blob.Length;
            var row = blob[(match.Index+match.Length)..end].Trim();
            var id = row.Split('|', 2)[0].Trim();
            var meta = equipment.GetValueOrDefault(id) ?? Empty;
            var level = Regex.Match(row, @"\|lv=([^|]+)");
            var stats = Regex.Match(row, @"\|stats=(.*)$");
            result.Add(Object(("slot", Number(Coerce(match.Groups[1].Value))), ("item_id", new EvidenceText(id)),
                ("item_name", Or(meta.Get("item_name"), new EvidenceText(id))), ("suit_id", Or(meta.Get("suit_id"), new EvidenceText(""))),
                ("suit_name", Or(meta.Get("suit_name"), new EvidenceText(""))), ("part_name", Or(meta.Get("part_name"), new EvidenceText(""))),
                ("rarity", meta.Get("rarity")), ("enhance_levels", new EvidenceArray(TraceFields.EquipmentLevels(level.Success ? level.Groups[1].Value : null)
                    .Select(item => (EvidenceValue)Object(("index", Number(item.Index)), ("level", Number(item.Level)))).ToArray())),
                ("stats", new EvidenceArray(TraceFields.InlineEquipmentStats(stats.Success ? stats.Groups[1].Value : null)
                    .Select(item => (EvidenceValue)Object(("slot", new EvidenceText(item.Slot)), ("name", new EvidenceText(item.Name)),
                        ("value", item.Value is double value ? new EvidenceReal(value) : new EvidenceText((string)item.Value)), ("level", Number(item.Level)))).ToArray())),
                ("catalog_main_attr", meta.Get("main_attr")), ("catalog_sub_attrs", Or(meta.Get("sub_attrs"), Empty))));
        }
        return new(result);
    }

    public EvidenceArray SuitCounts(string? blob)
    {
        List<EvidenceValue> result = [];
        foreach (Match match in Regex.Matches(blob ?? "", @"\[([^\]]+)\]=(\d+)"))
        {
            var id = match.Groups[1].Value;
            var count = Coerce(match.Groups[2].Value);
            var meta = suits.GetValueOrDefault(id) ?? Empty;
            result.Add(Object(("suit_id", new EvidenceText(id)), ("suit_name", Or(meta.Get("suit_name"), new EvidenceText(id))),
                ("piece_count", Number(count)), ("required_piece_count", meta.Get("required_piece_count")),
                ("active", new EvidenceBoolean(meta.Get("required_piece_count") is EvidenceInteger required && count >= required.Value)),
                ("description", Or(meta.Get("description"), new EvidenceText(""))), ("value", Or(meta.Get("value"), Empty))));
        }
        return new(result);
    }

    public EvidenceObject? Slot(string line)
    {
        var character = TraceFields.Token(line, "char");
        if (string.IsNullOrEmpty(character) || !character.StartsWith("chr_", StringComparison.Ordinal)) return null;
        var level = Coerce(TraceFields.Token(line, "weaponLv"));
        var rawRefine = TraceFields.Token(line, "refine") ?? "";
        var characterLevel = Coerce(TraceFields.Token(line, "charLv"));
        var unplaced = Regex.Match(line, @"\bunplacedEquipInstIds=\[([^\]]*)\]");
        var complete = TraceFields.Token(line, "equipsComplete");
        return Slot(new LoadoutSlotObservation(character)
        {
            Slot = Coerce(TraceFields.Token(line, "slot")), CharacterLevel = characterLevel.IsZero ? null : characterLevel,
            Potential = Coerce(TraceFields.Token(line, "potential")), WeaponInstance = TraceFields.Token(line, "weaponInstId"),
            Weapon = TraceFields.Token(line, "weaponTemplate") ?? "", WeaponLevel = level > 0 ? level : null,
            Refine = Regex.IsMatch(rawRefine, @"\A[0-5]\z") ? Coerce(rawRefine) : null,
            Breakthrough = Coerce(TraceFields.Token(line, "break")), SuitBlob = TraceFields.Braced(line, "equipSuit") ?? "",
            EquipmentBlob = TraceFields.Braced(line, "equips"), SkillIds = TraceFields.SkillIntegerIds(line),
            UnplacedIds = unplaced.Success ? Regex.Matches(unplaced.Groups[1].Value, @"\d+").Select(match => match.Value).ToArray() : null,
            EquipmentComplete = complete is "0" or "1" ? complete == "1" : null,
        });
    }

    public EvidenceObject? Slot(LoadoutSlotObservation observation)
    {
        var character = observation.Character; if (!character.StartsWith("chr_", StringComparison.Ordinal)) return null;
        var weapon = observation.Weapon; var level = observation.WeaponLevel;
        var meta = weapons.GetValueOrDefault(weapon) ?? Empty;
        var suit = observation.SuitBlob;
        var result = Object(("slot", Number(observation.Slot)), ("character_key", new EvidenceText(character)),
            ("character_name", new EvidenceText(characterName(character) is { Length: > 0 } name ? name : character)),
            ("character_level", Number(observation.CharacterLevel)), ("potential", Number(observation.Potential)),
            ("weapon_inst_id", Text(observation.WeaponInstance)), ("weapon_template", new EvidenceText(weapon)),
            ("weapon_name", Or(meta.Get("weapon_name"), new EvidenceText(weapon))), ("weapon_level", Number(level)),
            ("weapon_refine", Number(observation.Refine)), ("weapon_refine_source", observation.Refine is not null ? new EvidenceText("loadout") : EvidenceNull.Value),
            ("weapon_break", Number(observation.Breakthrough)), ("weapon_base_atk", SelectedBaseAttack(weapon, level)),
            ("weapon_catalog_skilllist", Or(meta.Get("skilllist"), new EvidenceArray([]))), ("equip_suit_raw", new EvidenceText(suit.Length > 0 ? "{"+suit+"}" : "{}")),
            ("suit_effects", SuitCounts(suit)), ("equips", InlineEquipmentBlob(observation.EquipmentBlob)),
            ("skill_int_ids", new EvidenceArray(observation.SkillIds.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray())),
            ("weapon_source_skills", new EvidenceArray([])), ("weapon_refine_stats", new EvidenceArray([])), ("gem_template", EvidenceNull.Value), ("gem_terms", Empty));
        var fields = new Dictionary<string, EvidenceValue>(result.Fields, StringComparer.Ordinal);
        if (observation.UnplacedIds is not null) fields["unresolved_equip_inst_ids"] = new EvidenceArray(observation.UnplacedIds.Select(value => (EvidenceValue)new EvidenceText(value)).ToArray());
        if (observation.EquipmentComplete is bool complete) fields["equipment_snapshot_complete"] = new EvidenceBoolean(complete);
        return new(fields);
    }

    public EvidenceObject? Stats(string line, EvidenceObject? context = null, IReadOnlyDictionary<string, string>? squad = null, bool allowBoundGem = false)
    {
        if (line.Contains(" CHAR_SKILLS ", StringComparison.Ordinal)) return CharacterSkills(line, context, squad);
        var character = TraceFields.Token(line, "char");
        if (string.IsNullOrEmpty(character) || !character.StartsWith("chr_", StringComparison.Ordinal)) return null;
        var level = Coerce(TraceFields.Token(line, "weaponLv"));
        return Stats(new LoadoutStatsObservation(character)
        {
            Weapon = TraceFields.Token(line, "weaponTemplate") ?? "", WeaponLevel = level > 0 ? level : null,
            WeaponInstance = TraceFields.Token(line, "weaponInstId") ?? "", RefineStatsBlob = TraceFields.Braced(line, "weaponRefineStats"),
            SourceSkillsBlob = TraceFields.Braced(line, "weaponSourceSkills"), BaseAttack = Coerce(TraceFields.Token(line, "weaponBaseAtk")),
            BaseAttackLv1 = Coerce(TraceFields.Token(line, "weaponBaseAtkLv1")), BaseAttackMax = Coerce(TraceFields.Token(line, "weaponBaseAtkMax")),
            GemInstance = TraceFields.Token(line, "gemInstId") ?? "", GemWeapon = TraceFields.Token(line, "gemWeaponId") ?? "",
            GemTemplate = TraceFields.Token(line, "gemTemplate"), TermsBlob = TraceFields.Braced(line, "gemTerms") ?? "",
        }, allowBoundGem);
    }

    public EvidenceObject? Stats(LoadoutStatsObservation observation, bool allowBoundGem = false)
    {
        var character = observation.Character; if (!character.StartsWith("chr_", StringComparison.Ordinal)) return null;
        var weapon = observation.Weapon; var level = observation.WeaponLevel;
        var refineStats = SourceSkills(observation.RefineStatsBlob);
        var source = SourceSkills(observation.SourceSkillsBlob);
        var rawTerms = observation.TermsBlob;
        var weaponId = observation.WeaponInstance; var gemId = observation.GemInstance;
        EvidenceArray? gemTerms = null;
        if (allowBoundGem && Regex.IsMatch(weaponId, @"\A[1-9]\d*\z") && Regex.IsMatch(gemId, @"\A[1-9]\d*\z")
            && observation.GemWeapon == weaponId && rawTerms.Length > 0)
        {
            var matches = rawTerms.Split(',').Select(value => Regex.Match(value.Trim(), @"\A(\d+):[^,@{}]*@cost(\d+)\z")).ToArray();
            if (matches.All(match => match.Success)) gemTerms = new(matches.Select(match => (EvidenceValue)Object(
                ("term_num_id", Number(Coerce(match.Groups[1].Value))), ("cost", Number(Coerce(match.Groups[2].Value))))).ToArray());
        }
        var refine = refinement.Infer(weapon, source.Items.Count > 0 ? source : refineStats, gemTerms);
        var attack = observation.BaseAttack;
        return Object(("character_key", new EvidenceText(character)), ("weapon_template", new EvidenceText(weapon)),
            ("weapon_refine", Number(refine)), ("weapon_refine_source", refine is null ? EvidenceNull.Value : new EvidenceText("source_skill")),
            ("weapon_base_atk", attack.IsZero ? SelectedBaseAttack(weapon, level) : Number(attack)),
            ("weapon_base_atk_lv1", Number(observation.BaseAttackLv1)), ("weapon_base_atk_max", Number(observation.BaseAttackMax)),
            ("weapon_refine_stats", refineStats), ("weapon_source_skills", source), ("gem_template", Text(observation.GemTemplate)),
            ("gem_terms", Blackboard(rawTerms.Replace(':', '='))));
    }

    private EvidenceObject? CharacterSkills(string line, EvidenceObject? context, IReadOnlyDictionary<string, string>? squad)
        => CharacterSkills(skills.ParseCharacterSkills(line), TraceFields.Token(line, "ownerId") ?? "", context, squad);

    public EvidenceObject? CharacterSkills(CharacterSkillLevels? parsed, string owner, EvidenceObject? context, IReadOnlyDictionary<string, string>? squad)
    {
        if (parsed is null || context is null || context.Fields.Count == 0 || squad is null || squad.Count == 0) return null;
        var weaponId = CatalogValues.Text(CatalogValues.Or(context.Get("weapon_inst_id"), new EvidenceText("")));
        if (squad.GetValueOrDefault(owner) != parsed.Owner || squad.Values.Count(value => value == parsed.Owner) != 1
            || context.Get("character_key") is not EvidenceText character || character.Value != parsed.Owner
            || !Regex.IsMatch(weaponId, @"\A[1-9]\d*\z") || context.Get("weapon_refine") is not EvidenceNull) return null;
        var weapon = CatalogValues.Text(CatalogValues.Or(context.Get("weapon_template"), new EvidenceText("")));
        var main = refinement.MainSkill(weapon);
        if (main.Length == 0 || !parsed.Levels.TryGetValue(main, out var level)) return null;
        var refine = refinement.Infer(weapon, new EvidenceArray([Object(("skill_id", new EvidenceText(main)), ("level", Number(level)))]));
        if (refine is null) return null;
        var fields = new Dictionary<string, EvidenceValue>(((EvidenceObject)BuffEvidence.Clone(context)).Fields, StringComparer.Ordinal)
        {
            ["weapon_refine"] = Number(refine), ["weapon_refine_source"] = new EvidenceText("source_skill"),
            ["weapon_refine_evidence"] = Object(("source", new EvidenceText("CHAR_SKILLS")), ("owner_id", new EvidenceText(owner)),
                ("weapon_inst_id", new EvidenceText(CatalogValues.Text(context.Get("weapon_inst_id")))), ("skill_id", new EvidenceText(main)), ("level", Number(level))),
        };
        return new(fields);
    }
}
