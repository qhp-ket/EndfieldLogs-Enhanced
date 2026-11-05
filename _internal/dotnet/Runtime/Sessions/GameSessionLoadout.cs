using System.Globalization;
using System.Numerics;
using System.Collections;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Runtime.Sessions;

public sealed partial class GameSessionBusiness
{
    public IReadOnlyList<IReadOnlyDictionary<string, object?>> LoadoutSnapshot() => LoadoutRows();
    private static string NumberText(BigInteger value) => value.ToString(CultureInfo.InvariantCulture);
    private static string FormatMap<T>(IReadOnlyDictionary<BigInteger, T> values) => "{" + string.Join(' ', values
        .OrderBy(pair => NumberText(pair.Key), PythonDisplay.CodePointComparer).Select(pair => $"[{NumberText(pair.Key)}]={pair.Value}")) + "}";
    private static string FormatSourceSkills(IEnumerable<SourceSkill> rows) => string.Join(';', rows.Select(row =>
        $"{row.Id}:level={row.Level}:potentialLv={row.Potential}:bb={{{string.Join(',', row.Blackboard.OrderBy(pair => pair.Key, PythonDisplay.CodePointComparer).Select(pair => pair.Key + "=" + LoadoutDisplayCatalog.ValueText(pair.Value, 12)))}}}"));
    private BigInteger[] LoadoutTeam()
    {
        var current = currentTeam.Where(characters.ContainsKey).ToArray();
        var scene = sceneTeam.Where(characters.ContainsKey).ToArray();
        var dungeon = (dungeonTeam ?? []).Where(characters.ContainsKey).ToArray();
        if (scene.Length > 0)
        {
            if (dungeon.Length > 0 && dungeon.ToHashSet().SetEquals(scene)) return dungeon;
            if (current.Length > 0 && current.ToHashSet().SetEquals(scene)) return current;
            return scene;
        }
        return dungeonTeam is not null ? dungeon : current;
    }
    private string EquipmentText(BigInteger id, EquipmentItem? item)
    {
        var template = item is { Template.Length: > 0 } ? item.Template : item is { TemplateId.IsZero: false } ? NumberText(item.TemplateId) : NumberText(id);
        if (item is null) return template;
        var levels = string.Join(',', item.Enhance.OrderBy(pair => pair.Key).Select(pair => $"{pair.Key}:{pair.Value}"));
        var stats = loadoutCatalog?.EquipmentStats(template, item.Enhance) ?? "";
        return template + (levels.Length > 0 ? "|lv=" + levels : "") + (stats.Length > 0 ? "|stats=" + stats : "");
    }
    private List<Dictionary<string, object?>> LoadoutRows()
    {
        List<Dictionary<string, object?>> rows = [];
        foreach (var id in LoadoutTeam())
        {
            var character = characters[id]; var weaponId = character.Weapon;
            var weapon = weapons.GetValueOrDefault(weaponId);
            Dictionary<BigInteger, string> equips = []; Dictionary<BigInteger, BigInteger> equipIds = [];
            HashSet<BigInteger> usedIds = [];
            foreach (var (slot, equipId) in character.Equipment.OrderBy(pair => pair.Key))
            {
                if (equipId.IsZero || !usedIds.Add(equipId)) continue;
                equips[slot] = EquipmentText(equipId, equipment.GetValueOrDefault(equipId)); equipIds[slot] = equipId;
            }
            var inferred = equipment.Where(pair => !character.Complete && pair.Value.Owner == id && !usedIds.Contains(pair.Key)).ToArray();
            foreach (var (equipId, item) in inferred.OrderBy(pair => pair.Value.Template.Length > 0 ? pair.Value.Template : NumberText(pair.Key), PythonDisplay.CodePointComparer))
            {
                var template = item.Template.Length > 0 ? item.Template : !item.TemplateId.IsZero ? NumberText(item.TemplateId) : NumberText(equipId);
                var slots = loadoutCatalog?.Slots(template) ?? [];
                if (slots.Count != 1 || equips.ContainsKey(slots[0])) continue;
                equips[slots[0]] = EquipmentText(equipId, item); equipIds[slots[0]] = equipId; usedIds.Add(equipId);
            }
            var gemId = weapon?.Gem ?? 0;
            var gem = !gemId.IsZero ? gems.GetValueOrDefault(gemId) : null;
            if (gem is null && !weaponId.IsZero && gemsByWeapon.TryGetValue(weaponId, out var bound)) { gem = bound; gemId = bound.Id; }
            var templateId = weapon is { Template.Length: > 0 } ? weapon.Template : weapon is { TemplateId.IsZero: false } ? NumberText(weapon.TemplateId)
                : !weaponId.IsZero ? NumberText(weaponId) : "unknown_weapon";
            var source = weapon?.Source ?? "missing";
            BigInteger? refine = source is "template_only" or "missing" ? null : weapon!.Refine;
            var observedSkills = new EvidenceArray(character.SourceSkills.Select(row => (EvidenceValue)row.Evidence()).ToArray());
            if (source == "template_only" && loadoutCatalog?.Refinement.Infer(templateId, observedSkills,
                gem is not null && gemId > 0 && gem.Weapon == weaponId ? gem.TermEvidence() : null) is { } inferredRefine)
            { refine = inferredRefine; source += "+source_skill_refine"; }
            var sourceSkills = FormatSourceSkills(character.SourceSkills);
            var bounds = loadoutCatalog?.AttackBounds(templateId) ?? (EvidenceNull.Value, EvidenceNull.Value);
            rows.Add(new() { ["slot"] = rows.Count, ["char"] = character.Template, ["char_inst_id"] = id, ["char_level"] = character.Level,
                ["potential"] = character.Potential, ["weapon_inst_id"] = weaponId, ["weapon_template"] = templateId, ["weapon_sync_source"] = source,
                ["weapon_lv"] = weapon?.Level ?? 0, ["refine"] = refine, ["breakthrough"] = weapon?.Breakthrough ?? 0,
                ["weapon_base_atk"] = ProtoMessage.Plain(loadoutCatalog?.Attack(templateId, weapon?.Level ?? 0) ?? EvidenceNull.Value),
                ["weapon_base_atk_lv1"] = ProtoMessage.Plain(bounds.Item1), ["weapon_base_atk_max"] = ProtoMessage.Plain(bounds.Item2),
                ["weapon_refine_stats"] = sourceSkills.Length > 0 ? sourceSkills : refine is { } known ? loadoutCatalog?.RefineStats(templateId, known) ?? "" : "",
                ["weapon_refine_stats_source"] = sourceSkills.Length > 0 ? "server_weapon_skill" : "weapon_data_refine",
                ["attached_gem"] = gemId, ["gem_weapon_id"] = gem?.Weapon ?? 0, ["gem_template"] = gem?.TemplateId ?? 0,
                ["gem_terms"] = gem is null ? "" : string.Join(',', gem.Terms.Select(term => $"{term.Id}:{loadoutCatalog?.GemLabel(term.Id) ?? "attr_" + term.Id}@cost{term.Cost}")),
                ["equip_inst_ids"] = FormatMap(equipIds), ["equips"] = FormatMap(equips), ["equipment_snapshot_complete"] = character.Complete,
                ["unresolved_equip_inst_ids"] = inferred.Select(pair => pair.Key).Where(key => !usedIds.Contains(key)).Order().ToArray(),
                ["equip_suit"] = "{" + string.Join(' ', character.Suits.OrderBy(pair => pair.Key, PythonDisplay.CodePointComparer).Select(pair => $"[{pair.Key}]={pair.Value}")) + "}",
                ["skill_int_ids"] = string.Join(',', character.SkillIds.Distinct().Order()), ["weapon_source_skills"] = sourceSkills });
        }
        return rows;
    }
    private void EmitLoadout(string reason, long timestampMs, bool force = false)
    {
        loadoutContext?.Invoke(reason, timestampMs, force);
        var rows = LoadoutRows();
        if (rows.Count == 0) return;
        static EvidenceValue SignatureValue(object? value) => value switch
        {
            null => EvidenceNull.Value, bool flag => new EvidenceBoolean(flag), string text => new EvidenceText(text),
            BigInteger number => new EvidenceInteger(number), int number => new EvidenceInteger(number), long number => new EvidenceInteger(number),
            double number => new EvidenceReal(number),
            IReadOnlyDictionary<string, object?> row => new EvidenceObject(row.ToDictionary(pair => pair.Key, pair => SignatureValue(pair.Value), StringComparer.Ordinal)),
            IEnumerable items => new EvidenceArray(items.Cast<object?>().Select(SignatureValue).ToArray()),
            _ => throw new InvalidDataException("Unsupported loadout signature value"),
        };
        var signature = EvidenceJsonSignature.Sorted(SignatureValue(rows));
        if (!force && signature == lastLoadout) return;
        lastLoadout = signature;
        Emit("LOADOUT", timestampMs, new() { ["reason"] = reason, ["rows"] = rows });
    }

    private void RefreshWeaponSkillEvidence(BigInteger owner, ProtoMessage battle)
    {
        var member = squad.GetValueOrDefault(owner);
        var character = member?.Owner.ObjectId is { IsZero: false } id ? characters.GetValueOrDefault(id) : null;
        if (character is null || character.Template != member!.Owner.TemplateId || character.Weapon.IsZero || loadoutCatalog is null) return;
        var weapon = weapons.GetValueOrDefault(character.Weapon);
        var template = weapon?.Template ?? "";
        var gemId = weapon?.Gem ?? 0;
        var gem = !gemId.IsZero ? gems.GetValueOrDefault(gemId) : null;
        if (gem is null && gemsByWeapon.TryGetValue(character.Weapon, out var bound)) { gem = bound; gemId = gem.Id; }
        var terms = gem is not null && gemId > 0 && gem.Weapon == character.Weapon ? gem.TermEvidence() : null;
        var observed = WeaponSkills(battle);
        if (loadoutCatalog.Refinement.Infer(template, new EvidenceArray(character.SourceSkills.Select(row => (EvidenceValue)row.Evidence()).ToArray()), terms) is null
            && loadoutCatalog.Refinement.Infer(template, new EvidenceArray(observed.Select(row => (EvidenceValue)row.Evidence()).ToArray()), terms) is not null)
            ReplaceSourceSkills(character, observed);
    }
}
