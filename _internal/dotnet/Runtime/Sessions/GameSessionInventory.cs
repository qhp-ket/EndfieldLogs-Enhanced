using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Runtime.Sessions;

public sealed partial class GameSessionBusiness
{
    private sealed class CharacterItem
    {
        public required BigInteger Id { get; init; }
        public required string Template { get; init; }
        public BigInteger Level, Potential, Weapon;
        public Dictionary<BigInteger, BigInteger> Equipment = [];
        public Dictionary<string, BigInteger> Suits = new(StringComparer.Ordinal);
        public BigInteger[] SkillIds = [];
        public List<SourceSkill> SourceSkills = [];
        public bool Complete;
    }
    private sealed record SourceSkill(BigInteger Id, string TextId, BigInteger Instance, BigInteger Potential, BigInteger Level,
        Dictionary<string, EvidenceValue> Blackboard)
    {
        public EvidenceObject Evidence() => new(new Dictionary<string, EvidenceValue>
        { ["skill_int_id"] = new EvidenceInteger(Id), ["skill_str_id"] = new EvidenceText(TextId), ["inst_id"] = new EvidenceInteger(Instance),
            ["potential_lv"] = new EvidenceInteger(Potential), ["level"] = new EvidenceInteger(Level), ["blackboard"] = new EvidenceObject(Blackboard) });
    }
    private sealed class EquipmentItem
    {
        public BigInteger Id, TemplateId, Owner;
        public string Template = "";
        public Dictionary<BigInteger, BigInteger> Enhance = [], LegacyEnhance = [];
    }
    private sealed class WeaponItem
    {
        public BigInteger Id, TemplateId, Exp, Level, Refine, Breakthrough, Owner, Gem;
        public string Template = "", Source = "missing";
    }
    private sealed class GemItem
    {
        public BigInteger Id, Instance, Weapon, TemplateId, TotalCost, Domain;
        public string Template = "";
        public (BigInteger Id, BigInteger Cost)[] Terms = [];
        public Dictionary<string, object?> Payload = [];
        public EvidenceArray TermEvidence() => new(Terms.Select(term => (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>
            { ["term_num_id"] = new EvidenceInteger(term.Id), ["cost"] = new EvidenceInteger(term.Cost) })).ToArray());
    }
    private readonly Dictionary<BigInteger, CharacterItem> characters = [];
    private readonly Dictionary<BigInteger, EquipmentItem> equipment = [];
    private readonly Dictionary<BigInteger, WeaponItem> weapons = [];
    private readonly Dictionary<BigInteger, GemItem> gems = [], gemsByWeapon = [];
    private BigInteger[] currentTeam = [];
    private string? lastLoadout;

    private static Dictionary<BigInteger, BigInteger> IntMap(ProtoMessage message, string field) =>
        message.Mapping(field).ToDictionary(pair => Integer(pair.Key), pair => Integer(pair.Value!));
    private static Dictionary<string, BigInteger> StringMap(ProtoMessage message, string field) =>
        message.Mapping(field).ToDictionary(pair => pair.Key.ToString()!, pair => Integer(pair.Value!), StringComparer.Ordinal);

    private static List<SourceSkill> WeaponSkills(ProtoMessage battle)
    {
        List<SourceSkill> rows = [];
        foreach (var skill in battle.Children("skill_list"))
        {
            if (skill.Enum("source") != "Weapon") continue;
            Dictionary<string, EvidenceValue> values = new(StringComparer.Ordinal);
            foreach (var (key, value) in skill.Child("blackboard").Mapping("blackboard"))
            {
                var entry = new ProtoMessage(value as Google.Protobuf.IMessage);
                var text = entry.Text("str_value");
                values[key.ToString()!] = text.Length > 0 || entry.Boolean("is_dynamic") ? new EvidenceText(text) : new EvidenceReal(entry.Real("float_value"));
            }
            var template = skill.Child("skill_id");
            rows.Add(new(template.Number("int_id"), template.Text("str_id"), skill.Number("inst_id"),
                skill.Number("potential_lv"), skill.Number("level"), values));
        }
        return rows;
    }
    private static void ReplaceSourceSkills(CharacterItem character, IReadOnlyList<SourceSkill> rows)
    {
        var previous = character.SourceSkills.Select(row => row.Id).Where(id => !id.IsZero).ToHashSet();
        character.SourceSkills = rows.Select(row => row with { Potential = character.Potential, Blackboard = new(row.Blackboard, StringComparer.Ordinal) }).ToList();
        List<BigInteger> ids = character.SkillIds.Where(id => !id.IsZero && !previous.Contains(id)).ToList();
        foreach (var row in rows) if (!row.Id.IsZero && !ids.Contains(row.Id)) ids.Add(row.Id);
        character.SkillIds = ids.ToArray();
    }

    private bool ProcessInventory(string kind, ProtoMessage message, long timestampMs)
    {
        switch (kind)
        {
            case "SC_SYNC_CHAR_BAG_INFO":
                foreach (var row in message.Children("char_info"))
                {
                    var template = row.Text("templateid");
                    if (template.Length == 0) continue;
                    var id = row.Number("objid");
                    potentials[template] = row.Number("potential_level");
                    characters[id] = new() { Id = id, Template = template, Level = row.Number("level"), Potential = row.Number("potential_level"),
                        Weapon = row.Number("weapon_id"), Equipment = IntMap(row, "equip_col"), Suits = StringMap(row, "equip_suit"),
                        Complete = row.Declares("equip_col"), SourceSkills = WeaponSkills(row.Child("battle_mgr_info")),
                        SkillIds = row.Child("battle_mgr_info").Children("skill_list").Select(skill => skill.Child("skill_id").Number("int_id")).Where(id => !id.IsZero).Distinct().Order().ToArray() };
                }
                var teams = message.Children("team_info").ToArray();
                if (teams.Length > 0)
                {
                    var index = message.Number("curr_team_index");
                    currentTeam = index >= 0 && index < teams.Length ? teams[(int)index].Items("char_team").Select(Integer).Where(id => !id.IsZero).ToArray() : [];
                }
                break;
            case "SC_CHAR_BAG_SET_TEAM": currentTeam = message.Items("char_team").Select(Integer).Where(id => !id.IsZero).ToArray(); break;
            case "SC_CHAR_BAG_SET_TEAM_LEADER": break;
            case "SC_ITEM_BAG_SCOPE_SYNC":
            case "SC_ITEM_BAG_SCOPE_MODIFY":
                foreach (var grid in message.Child("bag").Children("grids")) IndexGrid(grid);
                foreach (var field in new[] { "depot", "factory_depot" })
                foreach (var (_, depot) in message.Mapping(field))
                foreach (var grid in new ProtoMessage(depot as Google.Protobuf.IMessage).Children("inst_list")) IndexGrid(grid);
                break;
            case "SC_EQUIP_PUTON": EquipPutOn(message); break;
            case "SC_EQUIP_PUTOFF":
                if (characters.TryGetValue(message.Number("charid"), out var character))
                {
                    if (character.Equipment.Remove(message.Number("slotid"), out var id) && equipment.TryGetValue(id, out var item)) item.Owner = 0;
                    character.Suits = StringMap(message, "suitinfo");
                }
                break;
            case "SC_EQUIP_ENHANCE":
                var equip = ReadEquipment(message.Child("equip_data"), "");
                if (equip.Id.IsZero) equip.Id = message.Number("equip_inst_id");
                if (!equip.Id.IsZero)
                {
                    if (equipment.TryGetValue(equip.Id, out var previous)) equip.Template = previous.Template;
                    equipment[equip.Id] = equip;
                }
                break;
            case "SC_WEAPON_PUTON": WeaponPutOn(message); break;
            case "SC_WEAPON_ADD_EXP": case "SC_WEAPON_BREAKTHROUGH": case "SC_WEAPON_REFINE_UPGRADE":
            case "SC_WEAPON_ATTACH_GEM": case "SC_WEAPON_DETACH_GEM": WeaponDelta(kind, message); break;
            default: return false;
        }
        EmitLoadout(kind, timestampMs);
        return true;
    }

    private static EquipmentItem ReadEquipment(ProtoMessage row, string template) => new() { Id = row.Number("equipid"), TemplateId = row.Number("templateid"),
        Template = template, Owner = row.Number("equip_char_id"), Enhance = IntMap(row, "enhance"), LegacyEnhance = IntMap(row, "legacy_enhance") };
    private void IndexGrid(ProtoMessage grid)
    {
        var template = grid.Text("id"); var inst = grid.Child("inst"); var id = inst.Number("inst_id");
        switch (inst.Case("inst_impl"))
        {
            case "equip":
                var equip = ReadEquipment(inst.Child("equip"), template);
                if (equip.Id.IsZero) equip.Id = id;
                if (!equip.Id.IsZero) equipment[equip.Id] = equip;
                return;
            case "weapon":
                var row = inst.Child("weapon"); var weapon = new WeaponItem { Id = row.Number("inst_id"), TemplateId = row.Number("template_id"),
                    Template = template, Exp = row.Number("exp"), Level = row.Number("weapon_lv"), Refine = row.Number("refine_lv"), Breakthrough = row.Number("breakthrough_lv"),
                    Owner = row.Number("equip_char_id"), Gem = row.Number("attach_gem_id"), Source = "WEAPON_DATA" };
                if (weapon.Id.IsZero) weapon.Id = id;
                if (!weapon.Id.IsZero) weapons[weapon.Id] = weapon;
                return;
            case "gem" when !id.IsZero:
                var data = inst.Child("gem"); var gemId = data.Number("gem_id");
                var gem = new GemItem { Instance = id, Id = gemId.IsZero ? id : gemId, Template = template, TemplateId = data.Number("template_id"),
                    Weapon = data.Number("weapon_id"), Domain = data.Number("domain_id"), TotalCost = data.Number("total_cost"), Payload = data.Payload(),
                    Terms = data.Children("terms").Select(term => (term.Number("term_num_id"), term.Number("cost"))).ToArray() };
                if (gems.TryGetValue(gem.Id, out var previous) && (!previous.Terms.SequenceEqual(gem.Terms) || previous.Weapon != gem.Weapon))
                    foreach (var character in characters.Values.Where(character => !character.Weapon.IsZero && (character.Weapon == previous.Weapon || character.Weapon == gem.Weapon))) ReplaceSourceSkills(character, []);
                gems[id] = gem; gems[gem.Id] = gem;
                if (!gem.Weapon.IsZero)
                {
                    gemsByWeapon[gem.Weapon] = gem;
                    var target = GetWeapon(gem.Weapon);
                    if (target.Gem.IsZero) target.Gem = gem.Id;
                }
                return;
        }
        if (!id.IsZero && template.StartsWith("wpn_", StringComparison.Ordinal))
        {
            var weapon = GetWeapon(id); weapon.Template = template;
            if (weapon.Source == "missing") weapon.Source = "template_only";
        }
    }
    private WeaponItem GetWeapon(BigInteger id)
    {
        if (!weapons.TryGetValue(id, out var value)) weapons[id] = value = new() { Id = id };
        return value;
    }
    private void EquipPutOn(ProtoMessage message)
    {
        var owner = message.Number("charid"); var id = message.Number("equipid"); var slot = message.Number("slotid");
        if (!owner.IsZero && characters.TryGetValue(owner, out var character))
        {
            var previous = character.Equipment.GetValueOrDefault(slot);
            if (!previous.IsZero && previous != id && equipment.TryGetValue(previous, out var old)) old.Owner = 0;
            foreach (var key in character.Equipment.Keys.Where(key => key != slot && character.Equipment[key] == id).ToArray()) character.Equipment.Remove(key);
            character.Equipment[slot] = id; character.Suits = StringMap(message, "suitinfo");
        }
        foreach (var other in characters.Values.Where(character => character.Id != owner))
            foreach (var key in other.Equipment.Keys.Where(key => other.Equipment[key] == id).ToArray()) other.Equipment.Remove(key);
        var off = message.Number("put_off_charid");
        if (!off.IsZero && characters.TryGetValue(off, out var previousOwner))
        {
            foreach (var key in previousOwner.Equipment.Keys.Where(key => previousOwner.Equipment[key] == id).ToArray()) previousOwner.Equipment.Remove(key);
            previousOwner.Suits = StringMap(message, "old_owner_suitinfo");
        }
        if (!id.IsZero && equipment.TryGetValue(id, out var item)) item.Owner = owner;
    }
    private void WeaponPutOn(ProtoMessage message)
    {
        var owner = message.Number("charid"); var id = message.Number("weaponid"); var offId = message.Number("offweaponid"); var offOwner = message.Number("put_off_charid");
        var receiver = !owner.IsZero ? characters.GetValueOrDefault(owner) : null;
        var previous = !offOwner.IsZero && offOwner != owner ? characters.GetValueOrDefault(offOwner) : null;
        var previousId = receiver?.Weapon ?? 0; var fromId = previous?.Weapon ?? 0;
        var receiverSkills = receiver?.SourceSkills.ToArray() ?? []; var previousSkills = previous?.SourceSkills.ToArray() ?? [];
        if (receiver is not null) { receiver.Weapon = id; if (id != previousId) ReplaceSourceSkills(receiver, previous is not null && fromId == id ? previousSkills : []); }
        if (previous is not null) { previous.Weapon = offId; ReplaceSourceSkills(previous, !offId.IsZero && previousId == offId ? receiverSkills : []); }
        if (!id.IsZero) GetWeapon(id).Owner = owner;
        if (!offId.IsZero) GetWeapon(offId).Owner = previous is not null ? offOwner : 0;
    }
    private void WeaponDelta(string kind, ProtoMessage message)
    {
        var id = message.Number("weaponid"); if (id.IsZero) return;
        var weapon = GetWeapon(id);
        if (kind is "SC_WEAPON_ATTACH_GEM" or "SC_WEAPON_DETACH_GEM")
            foreach (var character in characters.Values.Where(character => character.Weapon == id)) ReplaceSourceSkills(character, []);
        switch (kind)
        {
            case "SC_WEAPON_ADD_EXP": weapon.Exp = message.Number("new_exp"); weapon.Level = message.Number("weapon_lv"); break;
            case "SC_WEAPON_BREAKTHROUGH": weapon.Breakthrough = message.Number("breakthrough_lv"); break;
            case "SC_WEAPON_REFINE_UPGRADE": weapon.Refine = message.Number("refine_lv"); break;
            case "SC_WEAPON_ATTACH_GEM":
                weapon.Gem = message.Number("gemid");
                if (gems.TryGetValue(weapon.Gem, out var gem)) { gem.Weapon = id; gemsByWeapon[id] = gem; }
                break;
            case "SC_WEAPON_DETACH_GEM":
                var detached = message.Number("detach_gemid"); if (detached.IsZero) detached = weapon.Gem;
                weapon.Gem = 0; gemsByWeapon.Remove(id);
                if (!detached.IsZero && gems.TryGetValue(detached, out var old)) old.Weapon = 0;
                break;
        }
    }
}
