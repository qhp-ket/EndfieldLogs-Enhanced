using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record RepairedBattleLoadouts(IReadOnlyList<EvidenceObject> Groups,
    IReadOnlyDictionary<string,EvidenceObject> Fallback);

/// <summary>Reconcile observed weapon transfers, then select only evidence available at the battle boundary.</summary>
public sealed class BattleLoadoutResolver(IReadOnlyDictionary<string,string> skillNumbers)
{
    private static readonly EvidenceArray Empty = new([]);
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static EvidenceObject Copy(EvidenceObject row)=>(EvidenceObject)BuffEvidence.Clone(row);
    private static Dictionary<string,EvidenceObject> Rows(EvidenceObject rows)=>rows.Fields
        .Where(pair=>pair.Value is EvidenceObject).ToDictionary(pair=>pair.Key,pair=>Copy((EvidenceObject)pair.Value),StringComparer.Ordinal);

    public static BattleLoadoutResolver Load(ResourceFiles files)=>new(new SkillResourceCatalog(files).Skills);

    public IReadOnlyDictionary<string,EvidenceObject> Select(IReadOnlyList<EvidenceObject> groups,
        IReadOnlyDictionary<string,EvidenceObject> fallback,BigInteger? anchorMs,BigInteger? anchorLineNumber=null)
    {
        var nonempty=groups.Where(group=>group.Get("rows") is EvidenceObject { Fields.Count:>0 }).ToArray();
        if(nonempty.Length==0) return fallback.ToDictionary(pair=>pair.Key,pair=>Copy(pair.Value),StringComparer.Ordinal);
        Dictionary<string,EvidenceObject> state=new(StringComparer.Ordinal);
        EvidenceObject? selected=null;
        foreach(var group in nonempty)
        {
            if(anchorMs is BigInteger anchor)
            {
                if(group.Get("ts_ms") is not EvidenceInteger timestamp || timestamp.Value>anchor) continue;
                if(timestamp.Value==anchor && anchorLineNumber is BigInteger line
                    && LoadoutMerging.Integer(CatalogValues.Or(group.Get("line_no"),new EvidenceInteger(0)))>line) continue;
            }
            selected=(EvidenceObject)group.Get("rows");
            foreach(var (key,value) in selected.Fields)
                if(value is EvidenceObject row) state[key]=LoadoutMerging.MergeTracked(state.GetValueOrDefault(key),Copy(row));
        }
        return selected is null ? new Dictionary<string,EvidenceObject>(StringComparer.Ordinal)
            : selected.Fields.Keys.Where(state.ContainsKey).ToDictionary(key=>key,key=>state[key],StringComparer.Ordinal);
    }

    public EvidenceObject WithoutMismatchedWeaponSkills(EvidenceObject source)
    {
        var row=Copy(source);
        var weapon=Text(row.Get("weapon_template"));
        if(!weapon.StartsWith("wpn_",StringComparison.Ordinal)) return row;
        var mainSkills=CatalogValues.Iterable(CatalogValues.Or(row.Get("weapon_source_skills"),row.Get("weapon_refine_stats"),Empty))
            .OfType<EvidenceObject>().Select(item=>Text(item.Get("skill_id")))
            .Select(id=>skillNumbers.GetValueOrDefault(id) ?? id).Where(id=>id.StartsWith("sk_wpn_",StringComparison.Ordinal)).ToHashSet(StringComparer.Ordinal);
        if(mainSkills.Count==0 || mainSkills.Contains("sk_"+weapon)) return row;
        var stale=LoadoutMerging.WeaponSourceSkillIds(row).ToHashSet();
        var fields=new Dictionary<string,EvidenceValue>(row.Fields,StringComparer.Ordinal)
        { ["weapon_source_skills"]=Empty,["weapon_refine_stats"]=Empty };
        if(row.Get("weapon_refine_source") is EvidenceText { Value:"source_skill" })
        { fields["weapon_refine"]=EvidenceNull.Value;fields["weapon_refine_source"]=EvidenceNull.Value; }
        fields["skill_int_ids"]=new EvidenceArray(CatalogValues.Iterable(CatalogValues.Or(row.Get("skill_int_ids"),Empty))
            .Select(LoadoutMerging.Integer).Where(id=>!id.IsZero && !stale.Contains(id)).Select(id=>(EvidenceValue)new EvidenceInteger(id)).ToArray());
        return new(fields);
    }

    public RepairedBattleLoadouts Repair(IReadOnlyList<EvidenceObject> groups,IReadOnlyDictionary<string,EvidenceObject> fallback)
    {
        Dictionary<string,EvidenceObject> rawState=new(StringComparer.Ordinal),correctedState=new(StringComparer.Ordinal);
        List<EvidenceObject> repaired=[];
        foreach(var source in groups)
        {
            var group=Copy(source);
            if(group.Get("rows") is not EvidenceObject rows) { repaired.Add(group);continue; }
            var raw=Rows(rows);
            var corrected=raw.ToDictionary(pair=>pair.Key,pair=>Copy(pair.Value),StringComparer.Ordinal);
            var reason=Text(group.Get("reason"));
            if(reason!="SC_SYNC_CHAR_BAG_INFO")
                foreach(var (key,row) in raw)
                    if(rawState.TryGetValue(key,out var previousRaw) && previousRaw.Fields.Count>0
                        && correctedState.TryGetValue(key,out var previousCorrected) && previousCorrected.Fields.Count>0
                        && !LoadoutMerging.SameWeapon(previousRaw,previousCorrected)
                        && Text(row.Get("weapon_inst_id"))==Text(previousRaw.Get("weapon_inst_id")))
                        corrected[key]=LoadoutMerging.WithWeapon(row,previousCorrected);
            Dictionary<string,EvidenceObject> updates=new(StringComparer.Ordinal);
            if(reason=="SC_WEAPON_PUTON")
                foreach(var (receiver,row) in raw)
                {
                    if(!rawState.TryGetValue(receiver,out var beforeRaw) || beforeRaw.Fields.Count==0
                        || !correctedState.TryGetValue(receiver,out var beforeCorrected) || beforeCorrected.Fields.Count==0) continue;
                    var instance=Text(row.Get("weapon_inst_id"));
                    if(instance.Length==0 || instance==Text(beforeRaw.Get("weapon_inst_id"))) continue;
                    var owner=correctedState.FirstOrDefault(pair=>pair.Key!=receiver && Text(pair.Value.Get("weapon_inst_id"))==instance);
                    if(owner.Key is null) { corrected[receiver]=WithoutMismatchedWeaponSkills(corrected[receiver]);continue; }
                    corrected[receiver]=LoadoutMerging.WithWeapon(row,owner.Value);
                    var moved=LoadoutMerging.WithWeapon(corrected.GetValueOrDefault(owner.Key) ?? owner.Value,beforeCorrected);
                    if(corrected.ContainsKey(owner.Key)) corrected[owner.Key]=moved;
                    else updates[owner.Key]=moved;
                }
            foreach(var key in corrected.Keys.ToArray()) corrected[key]=WithoutMismatchedWeaponSkills(corrected[key]);
            var fields=new Dictionary<string,EvidenceValue>(group.Fields,StringComparer.Ordinal)
            { ["rows"]=new EvidenceObject(corrected.ToDictionary(pair=>pair.Key,pair=>(EvidenceValue)pair.Value,StringComparer.Ordinal)) };
            repaired.Add(new(fields));
            foreach(var (key,row) in raw) rawState[key]=LoadoutMerging.MergeTracked(rawState.GetValueOrDefault(key),row);
            foreach(var (key,row) in corrected) correctedState[key]=LoadoutMerging.MergeTracked(correctedState.GetValueOrDefault(key),row);
            foreach(var (key,row) in updates) correctedState[key]=LoadoutMerging.MergeTracked(correctedState.GetValueOrDefault(key),row);
        }
        var final=fallback.ToDictionary(pair=>pair.Key,pair=>Copy(pair.Value),StringComparer.Ordinal);
        foreach(var (key,row) in correctedState) final[key]=LoadoutMerging.MergeTracked(final.GetValueOrDefault(key),row);
        return new(repaired,final);
    }
}
