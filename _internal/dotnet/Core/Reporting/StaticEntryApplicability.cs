using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public readonly record struct StaticEntryApplicabilityResult(bool Applies,bool UnresolvedCondition);

/// <summary>Evaluate a static source without mutating the hit or counting captured final attributes twice.</summary>
public static class StaticEntryApplicability
{
    private static readonly HashSet<string> Zones=new(StringComparer.Ordinal)
    { "atk","dmg_inc","amp","fragile","vuln_taken","res","combo","arts_strength","prod_dmg_inc","prod_vuln_taken" };
    private static readonly HashSet<string> AttributeKinds=new(StringComparer.Ordinal)
    { "official_EquipTable_attribute","official_WeaponSkill_text_basic","current_official_item_skill_card_attribute" };
    private static readonly IReadOnlyDictionary<string,int> GroupMasks=new Dictionary<string,int>(StringComparer.Ordinal)
    { ["normal"]=0x20484,["skill"]=0x100,["combo"]=0x2000,["ultimate"]=0x200 };
    private static string Text(EvidenceValue value,string fallback="")=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText(fallback)));

    // The optional numeric map preserves the integer-key precedence at the Python compatibility boundary.
    // Text keys remain in hit.baseline; JSON must not collapse two differently typed observed keys.
    public static StaticEntryApplicabilityResult Evaluate(EvidenceObject entry,EvidenceObject hit,
        IReadOnlyDictionary<BigInteger,EvidenceValue>? numericBaseline=null)
    {
        if(!Zones.Contains(Text(entry.Get("zone"))) || BuffEvidence.OptionalFloat(entry.Get("rate")) is not double rate || rate<=0) return new(false,false);
        var unresolved=false;
        if(AttributeKinds.Contains(Text(entry.Get("evidence_kind"))))
        {
            var attr=entry.Get("attr_type");
            if(attr is EvidenceObject or EvidenceArray) throw new InvalidCastException("Unhashable attribute type");
            if(!EvidenceJson.PythonEquals(attr,new EvidenceInteger(2)))
            {
                EvidenceValue? observed=null;
                if(numericBaseline is not null)
                    foreach(var (key,value) in numericBaseline)
                        if(EvidenceJson.PythonEquals(new EvidenceInteger(key),attr)) { observed=value;break; }
                if(observed is null && hit.Get("baseline") is EvidenceObject baseline) observed=baseline.Fields.GetValueOrDefault(CatalogValues.Text(attr));
                if(observed is not null)
                {
                    if(BuffEvidence.OptionalFloat(observed) is not null) return new(false,false);
                    unresolved=true;
                }
            }
            var applicable=DamageAttributeApplicability.Evaluate(attr,hit.Get("damage_decorate_mask"),
                hit.Get("static_damage_decorate_mask"),hit.Get("static_damage_decorate_mask_source"));
            if(applicable is null) unresolved=true;
            if(applicable is not true) return new(false,unresolved);
        }
        if(!EffectConditions.AppliesToElement(Text(entry.Get("element"),"all"),
            hit.Get("damage_element") is EvidenceText element ? element.Value : null,
            hit.Get("damage_school") is EvidenceNull ? null : CatalogValues.Text(hit.Get("damage_school")))) return new(false,unresolved);
        var groups=CatalogValues.Iterable(CatalogValues.Or(entry.Get("skill_groups"),new EvidenceArray([])))
            .Select(group=>Text(group)).Where(group=>group.Length>0).ToHashSet(StringComparer.Ordinal);
        if(groups.Count==0) return new(true,unresolved);
        if(groups.Any(group=>!GroupMasks.ContainsKey(group))) return new(false,true);
        var condition=BuffEvidence.Object(("condition",BuffEvidence.Object(
            ("type",new EvidenceText("damage_decorate_mask")),("check",new EvidenceText("HasAny")),
            ("mask",new EvidenceInteger(groups.Sum(group=>GroupMasks[group]))))));
        var failure=EffectConditions.Failure(condition,hit);
        if(failure?.Get("reason_group") is EvidenceText { Value:"condition_unobservable" }) unresolved=true;
        return new(failure is null,unresolved);
    }
}
