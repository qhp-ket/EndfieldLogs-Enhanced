using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Effects;

/// <summary>Known loadout evidence filters suit/weapon BUFFs; missing actor loadouts remain unknown.</summary>
public sealed class BuffLoadoutFilter(PacketBuffCatalog packets,IReadOnlyDictionary<string,IReadOnlySet<string>> suitBuffs)
{
    private static readonly Regex Weapon = new(@"^buff_(wpn_[a-z]+_\d+)_",RegexOptions.CultureInvariant);
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static IEnumerable<string> Children(EvidenceObject entry) => BuffDisplayClassification.ChildFields
        .SelectMany(field=>CatalogValues.Iterable(CatalogValues.Or(entry.Get(field),new EvidenceArray([]))))
        .Select(Text).Where(key=>key.Length>0);

    public static BuffLoadoutFilter Load(ResourceFiles files,PacketBuffCatalog packets)
    {
        static Dictionary<string,EvidenceObject> Entries(EvidenceValue? document)=>((document as EvidenceObject)?.Get("entries") as EvidenceObject)?.Fields
            .Where(row=>row.Value is EvidenceObject).ToDictionary(row=>row.Key,row=>(EvidenceObject)row.Value,StringComparer.Ordinal) ?? [];
        return new(packets,BuildSuitBuffs(Entries(files.ReadOnly(files.PathFor("data/local_semantics/skill/details.json"))),
            Entries(files.ReadOnly(files.PathFor("data/local_semantics/buff/details.json"))),
            files.JsonObjects("data/local_tables/equip/items").Where(row=>Path.GetFileName(row.Path).StartsWith("suit_",StringComparison.Ordinal))
                .OrderBy(row=>row.Path,PythonDisplay.CodePointComparer).Select(row=>row.Payload)));
    }

    public static IReadOnlyDictionary<string,IReadOnlySet<string>> BuildSuitBuffs(IReadOnlyDictionary<string,EvidenceObject> skills,
        IReadOnlyDictionary<string,EvidenceObject> buffs,IEnumerable<EvidenceObject> suits)
    {
        Dictionary<string,IReadOnlySet<string>> result=new(StringComparer.Ordinal);
        foreach(var suit in suits)
        {
            var id=Text(suit.Get("suitID"));
            var skill=Text(suit.Get("passiveSkillId"));
            if(id.Length==0 || skill.Length==0 || !skills.TryGetValue(skill,out var entry)) continue;
            Stack<string> pending=new(Children(entry).Where(key=>key.StartsWith("buff_equipsuit_",StringComparison.Ordinal)));
            HashSet<string> allowed=new(StringComparer.Ordinal);
            while(pending.TryPop(out var key))
            {
                if(!allowed.Add(key) || !buffs.TryGetValue(key,out var buff)) continue;
                foreach(var child in Children(buff)) if(!allowed.Contains(child)) pending.Push(child);
            }
            if(allowed.Count>0) result[id]=allowed;
        }
        return result;
    }

    public bool MatchesSuit(string? eventKey,string? source,IReadOnlyDictionary<string,HashSet<string>>? active)
    {
        var key=eventKey ?? "";
        if(!key.StartsWith("buff_equipsuit_",StringComparison.Ordinal) || string.IsNullOrEmpty(source)
            || active is null || !active.TryGetValue(source,out var suits)) return true;
        return suits.Any(suit=>suitBuffs.TryGetValue(suit,out var allowed) && allowed.Contains(key));
    }

    public bool MatchesWeapon(string? eventKey,string? source,IReadOnlyDictionary<string,string>? active)
    {
        var key=eventKey ?? "";
        var match=Weapon.Match(key);
        if(!match.Success || string.IsNullOrEmpty(source) || active is null
            || !active.TryGetValue(source,out var weapon) || weapon.Length==0) return true;
        var hint=packets.Hint(key);
        var id=hint is not null ? Text(hint.Get("weapon_id")) : "";
        if(id.Length==0) id=match.Groups[1].Value;
        return id==weapon;
    }
}
