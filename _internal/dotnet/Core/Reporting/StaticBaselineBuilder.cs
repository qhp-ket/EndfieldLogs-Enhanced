using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record StaticBaselineResult(IReadOnlyDictionary<string,EvidenceObject> Loadouts,bool LoadoutStale,
    IReadOnlyDictionary<string,double> StaticArtsStrength,IReadOnlyList<ReportHitInput> Hits,
    IReadOnlyDictionary<string,HashSet<string>> ActiveSuits,IReadOnlyDictionary<string,string> ActiveWeapons);

/// <summary>Attach proven static sources and observed base attack without retiring unresolved passives.</summary>
public sealed class StaticBaselineBuilder(BattleLoadoutResolver loadouts,StaticMultiplierDeriver multipliers,
    StaticArtsStrengthDeriver arts,CharacterBaseStatCatalog characters)
{
    private static readonly EvidenceObject Empty=new(new Dictionary<string,EvidenceValue>());
    private static readonly EvidenceArray NoItems=new([]);
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static IEnumerable<EvidenceObject> Objects(EvidenceValue value)=>CatalogValues.Iterable(CatalogValues.Or(value,NoItems)).Cast<EvidenceObject>();
    private static EvidenceArray Entries(EvidenceObject row,string key)=>row.Get(key) as EvidenceArray ?? NoItems;
    private static Dictionary<string,EvidenceValue> Fields(EvidenceObject row)=>(Dictionary<string,EvidenceValue>)row.Fields;
    private static BigInteger Int(EvidenceValue value)=>LoadoutMerging.Integer(value);

    public static StaticBaselineBuilder Load(ResourceFiles files)=>new(BattleLoadoutResolver.Load(files),StaticMultiplierDeriver.Load(files),
        StaticArtsStrengthDeriver.Load(files),new(files));

    public StaticBaselineResult Prepare(ReportBaselineInput input,BigInteger firstHitMs)
        => PrepareCore(input, firstHitMs, ownsHits: false);

    internal StaticBaselineResult PrepareOwned(ReportBaselineInput input,BigInteger firstHitMs,LiveHitPreparationCache? cache = null)
        => PrepareCore(input, firstHitMs, ownsHits: true, cache);

    private StaticBaselineResult PrepareCore(ReportBaselineInput input,BigInteger firstHitMs,bool ownsHits,LiveHitPreparationCache? cache = null)
    {
        var first=input.Hits.FirstOrDefault()?.Evidence;
        var anchor=first is null ? firstHitMs : Int(first.Fields.GetValueOrDefault("ts_ms") ?? throw new KeyNotFoundException("ts_ms"));
        var line=first is null ? BigInteger.Zero : Int(CatalogValues.Or(first.Get("line_no"),new EvidenceInteger(0)));
        var selected=loadouts.Select(input.Loadouts.Groups,input.Loadouts.Fallback,anchor,line.IsZero ? null : line)
            .ToDictionary(pair=>pair.Key,pair=>pair.Value,StringComparer.Ordinal);
        var observed=input.Hits.Select(hit=>Text(hit.Evidence.Get("character_key")))
            .Where(key=>key.StartsWith("chr_",StringComparison.Ordinal)).ToHashSet(StringComparer.Ordinal);
        var stale=selected.Count>0 && observed.Any(character=>!selected.ContainsKey(character));
        if(stale) selected.Clear();
        var activeSuits=stale ? new Dictionary<string,HashSet<string>>(StringComparer.Ordinal)
            : input.ActiveSuits.ToDictionary(pair=>pair.Key,pair=>new HashSet<string>(pair.Value,StringComparer.Ordinal),StringComparer.Ordinal);
        var activeWeapons=selected.Where(pair=>CatalogValues.Truth(pair.Value.Get("weapon_template")))
            .ToDictionary(pair=>pair.Key,pair=>Text(pair.Value.Get("weapon_template")),StringComparer.Ordinal);
        Dictionary<string,double> staticArts=new(StringComparer.Ordinal);
        foreach(var key in selected.Keys.ToArray())
        {
            var multiplier=multipliers.Derive(selected[key]);
            Fields(multiplier.Loadout)["static_multiplier_entries"]=new EvidenceArray(multiplier.Entries.Cast<EvidenceValue>().ToArray());
            var derived=arts.Derive(multiplier.Loadout);
            Fields(derived.Loadout)["static_arts_strength_entries"]=new EvidenceArray(derived.Entries.Cast<EvidenceValue>().ToArray());
            selected[key]=derived.Loadout;
            var sum=0.0;
            foreach(var entry in derived.Entries) sum+=BuffEvidence.OptionalFloat(entry.Get("rate")) ?? 0;
            staticArts[key]=sum;
        }
        cache?.Begin(this,selected);
        var hits=new List<ReportHitInput>(input.Hits.Count);
        foreach(var hitInput in input.Hits)
        {
            ReportHitInput PrepareHit()
            {
                var hit=ownsHits ? FrozenEvidence.OwnedMutableRoot(hitInput.Evidence) : (EvidenceObject)BuffEvidence.Clone(hitInput.Evidence);var fields=Fields(hit);
                var character=Text(hit.Get("character_key"));var row=cache?.Loadout(character) ?? selected.GetValueOrDefault(character) ?? Empty;
                fields["static_multiplier_entries"]=new EvidenceArray(Entries(row,"static_multiplier_entries").Items.ToArray());
                fields["rdps_unresolved_static_multiplier_sources"]=new EvidenceArray(Entries(row,"rdps_unresolved_static_multiplier_sources").Items.ToArray());
                fields["static_arts_strength_entries"]=Entries(row,"static_arts_strength_entries");
                var flat=Objects(row.Get("equipment_baseline_attributes")).Where(entry=>EvidenceJson.PythonEquals(entry.Get("attr_type"),new EvidenceInteger(2))
                    && EvidenceJson.PythonEquals(entry.Get("modifier_type"),new EvidenceInteger(7))).ToArray();
                var sum=0.0;foreach(var entry in flat) sum+=BuffEvidence.OptionalFloat(entry.Get("value")) ?? throw new InvalidDataException("Invalid derived flat attack");
                fields["static_flat_attack"]=flat.Length==0 ? new EvidenceInteger(0) : new EvidenceReal(sum);
                var flatEntries=new EvidenceArray(flat.Cast<EvidenceValue>().ToArray());
                fields["static_flat_attack_entries"]=cache is null ? BuffEvidence.Clone(flatEntries) : FrozenEvidence.CopyOwned(flatEntries);
                var level=CatalogValues.Or(hit.Get("attacker_stats_level"),row.Get("character_level"));
                var baseStats=characters.Get(character,level is EvidenceInteger exact ? exact.Value : null) ?? Empty;
                var basic=BuffEvidence.OptionalFloat(hitInput.BasicAttributes.GetValueOrDefault(2) ?? EvidenceNull.Value)
                    ?? BuffEvidence.OptionalFloat(baseStats.Get("atk"));
                var weapon=BuffEvidence.OptionalFloat(row.Get("weapon_base_atk"));
                if(basic is >0 && weapon is >0) fields["base_attack_for_percent"]=new EvidenceReal(basic.Value+weapon.Value);
                double? Attribute(EvidenceValue type)
                {
                    if(type is EvidenceObject or EvidenceArray) throw new InvalidCastException("Unhashable character attribute type");
                    foreach(var (key,value) in hitInput.Attributes)
                        if(EvidenceJson.PythonEquals(new EvidenceInteger(key),type)) return BuffEvidence.OptionalFloat(value);
                    return null;
                }
                var main=Attribute(baseStats.Get("main_attr_type"));var sub=Attribute(baseStats.Get("sub_attr_type"));
                var mainScale=Attribute(new EvidenceInteger(78));var subScale=Attribute(new EvidenceInteger(79));
                if(main is >=0 && sub is >=0 && mainScale is >=0 && subScale is >=0)
                {
                    var mainInteger=new BigInteger(main.Value);var subInteger=new BigInteger(sub.Value);
                    // Python converts the truncated integer back to double for each multiplication.
                    fields["attack_ability_factor"]=new EvidenceReal(1.0+(double)mainInteger*mainScale.Value+(double)subInteger*subScale.Value);
                }
                return hitInput with { Evidence=hit };
            }
            hits.Add(cache is null ? PrepareHit() : cache.Prepare(hitInput,PrepareHit));
        }
        IReadOnlyList<ReportHitInput> annotated = hits;
        if(cache is null) EnemyHpEvidence.AnnotateOwned(hits.Select(hit=>hit.Evidence).ToArray());
        else annotated=cache.Annotate(hits);
        return new(selected,stale,staticArts,annotated,activeSuits,activeWeapons);
    }
}
