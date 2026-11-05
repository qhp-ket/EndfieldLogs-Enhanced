using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using static EndfieldLogs.Core.Reporting.StaticLoadoutEvidence;

namespace EndfieldLogs.Core.Reporting;

public sealed record StaticMultiplierResult(EvidenceObject Loadout,IReadOnlyList<EvidenceObject> Entries);

/// <summary>Derive baseline evidence without treating reviewed transient triggers as static contributions.</summary>
public sealed class StaticMultiplierDeriver(IReadOnlyDictionary<string,EvidenceObject> equipment,
    IReadOnlyDictionary<string,EvidenceObject> weapons,IReadOnlyDictionary<string,string> skillNumbers,EvidenceObject damageCatalog)
{
    private readonly SkillIdentityCatalog identities=new(skillNumbers,new Dictionary<string,string>(),new Dictionary<string,RuntimeBuffDamageProfile>());
    private static readonly IReadOnlyDictionary<string,int> DamageAttributes=new Dictionary<string,int>(StringComparer.Ordinal)
    { ["NormalAttackDamageIncrease"]=17,["UltimateSkillDamageIncrease"]=28,["NormalSkillDamageIncrease"]=32,["ComboSkillDamageIncrease"]=33,
        ["PhysicalDamageIncrease"]=50,["FireDamageIncrease"]=51,["PulseDamageIncrease"]=52,["CrystDamageIncrease"]=53,["NaturalDamageIncrease"]=54,["EtherDamageIncrease"]=55 };
    public static StaticMultiplierDeriver Load(ResourceFiles files)=>new(new EquipmentCatalog(files).Pieces,new WeaponCatalog(files).Entries,
        new SkillResourceCatalog(files).Skills,files.ReadRelative("data/local_static/skill/item_damage_baseline_catalog.json") as EvidenceObject ?? Empty);
    private string? Canonical(EvidenceObject skill,HashSet<string> declared)
    {
        var canonical=identities.CanonicalSkillNumber(Text(skill.Get("skill_id")),null);
        return canonical ?? (skill.Get("skill_id") is EvidenceText text && declared.Contains(text.Value) ? text.Value : null);
    }

    public StaticMultiplierResult Derive(EvidenceObject source)
    {
        var row=(EvidenceObject)BuffEvidence.Clone(source);
        Fields(row)["rdps_unresolved_static_multiplier_sources"]=NoItems;
        if(CatalogValues.Truth(row.Get("unresolved_equip_inst_ids")))
            Block(row,Obj(("reason",Str("unresolved_equipment_slot")),("equip_inst_ids",new EvidenceArray(Items(row.Get("unresolved_equip_inst_ids")).ToArray()))));
        List<EvidenceValue> baseline=[];
        var entries=EquipmentBaselineDeriver.Apply(row,equipment,baseline);
        // This array is replaced at the end so weapon/suit evidence joins the same owned baseline.
        var weapon=Text(row.Get("weapon_template"));var meta=weapons.GetValueOrDefault(weapon) ?? Empty;
        var declared=Items(meta.Get("weapon_skill_ids")).Select(CatalogValues.Text).ToHashSet(StringComparer.Ordinal);
        var skills=Items(CatalogValues.Or(row.Get("weapon_source_skills"),row.Get("weapon_refine_stats"),NoItems)).OfType<EvidenceObject>().ToArray();
        Dictionary<(string Skill,string Key),string> attackSpecs=[];
        foreach(var skill in ReviewedItemFields.BasicAttack.Where(declared.Contains)) attackSpecs[(skill,"atk")]="BaseMultiplier";
        foreach(var field in Items(meta.Get("static_attack_fields")).OfType<EvidenceObject>())
            attackSpecs[(CatalogValues.Text(Required(field,"skillId")),CatalogValues.Text(Required(field,"bbKey")))]=CatalogValues.Text(Required(field,"formulaItem"));
        Dictionary<(string Skill,string Key),HashSet<double?>> attackValues=[];
        foreach(var skill in skills)
        {
            var canonical=Canonical(skill,declared);
            foreach(var pair in attackSpecs)
                if(canonical==pair.Key.Skill)
                {
                    if(!attackValues.TryGetValue(pair.Key,out var values)) attackValues[pair.Key]=values=[];
                    values.Add(BuffEvidence.OptionalFloat(Object(skill.Get("bb")).Get(pair.Key.Key)));
                }
        }
        foreach(var (key,values) in attackValues)
        {
            var value=values.Count==1 ? values.Single() : null;
            if(value is not double valid || valid<0)
            { Block(row,Obj(("reason",Str("missing_or_conflicting_weapon_basic_attack")),("source_id",Str(key.Skill))));continue; }
            if(attackSpecs[key]=="BaseFinalAddition")
            {
                baseline.Add(Obj(("source_type",Str("weapon_skill")),("source_id",Str(key.Skill)),("attr_type",Int(2)),("modifier_type",Int(7)),
                    ("modify_attribute_type",Int(0)),("value",new EvidenceReal(valid)),("bb_key",Str(key.Key)),("evidence_kind",Str("official_WeaponSkill_card_flat_attack"))));continue;
            }
            entries.Add(Obj(("source_type",Str("weapon_skill")),("source_name",Str(weapon)),("source_id",Str(key.Skill)),("zone",Str("atk")),("zone_label",Str(ZoneLabels["atk"])),
                ("element",Str("all")),("attr_type",Int(2)),("modifier_type",Int(6)),("bb_key",Str(key.Key)),("rate",new EvidenceReal(valid)),
                ("evidence_kind",Str("official_WeaponSkill_text_basic_atk")),("source_table_sha256",meta.Get("weapon_definition_sha256")),("condition_text",Str(""))));
        }
        var damageKeys=ApplyDamageCards(row,meta,skills,entries,out var reviewedSuits);
        ApplySuits(row,baseline,reviewedSuits);
        ApplyWeaponReview(row,skills,declared,attackSpecs,damageKeys);
        Fields(row)["equipment_baseline_attributes"]=new EvidenceArray(baseline.ToArray());
        return new(row,Deduplicate(row,entries));
    }

    private Dictionary<string,HashSet<string>> ApplyDamageCards(EvidenceObject row,EvidenceObject weaponMeta,IReadOnlyList<EvidenceObject> skills,
        List<EvidenceObject> entries,out HashSet<string> reviewedSuits)
    {
        Dictionary<string,HashSet<string>> keys=new(StringComparer.Ordinal);reviewedSuits=new(StringComparer.Ordinal);
        var trusted=Same(damageCatalog.Get("schemaVersion"),1) && damageCatalog.Get("source") is EvidenceText { Value:"current_official_item_skill_card_attribute" }
            && damageCatalog.Get("decoder") is EvidenceObject decoder && TypedResourceBinding.Matches(decoder);
        if(!trusted) return keys;
        foreach(var category in new[] { "weapon","suit" })
            foreach(var definition in Items(damageCatalog.Get(category+"Entries")).OfType<EvidenceObject>())
            {
                var modifier=Object(definition.Get("modifier"));var param=Object(modifier.Get("param"));var attr=definition.Get("attributeType");
                var attribute=AttributeEffects.Keys.Where(key=>EvidenceJson.PythonEquals(new EvidenceInteger(key),attr)).Cast<BigInteger?>().FirstOrDefault();
                if(modifier.Get("$type") is not EvidenceText { Value:"Beyond.Gameplay.AttributeModifierData.AttributeModifier" }
                    || modifier.Get("attributeType") is not EvidenceText kind || !DamageAttributes.TryGetValue(kind.Value,out var expected)
                    || !Same(attr,expected) || attribute is not BigInteger type
                    || modifier.Get("modifyAttributeType") is not EvidenceText { Value:"Specific" }
                    || param.Get("useBlackboardKey") is not EvidenceBoolean { Value:true }
                    || !EvidenceJson.PythonEquals(param.Get("blackboardKey"),definition.Get("bbKey")) || definition.Get("bbKey") is not EvidenceText { Value.Length:>0 } bbKey
                    || definition.Get("attributeIndex") is not EvidenceInteger { Value:var index } || index<0
                    || definition.Get("sourceBytes") is not EvidenceInteger { Value:var bytes } || bytes<=0
                    || !EvidenceJson.PythonEquals(definition.Get("consumedBytes"),definition.Get("sourceBytes"))
                    || !Hash(new EvidenceText(Text(definition.Get("sourceSha256"))))
                    || !EvidenceJson.PythonEquals(BuffEvidence.Text(skillNumbers.GetValueOrDefault(CatalogValues.Text(definition.Get("numericSkillId")))),definition.Get("skillId"))) continue;
                List<(EvidenceValue Item,string Source,EvidenceObject Blackboard)> observations=[];
                var id=CatalogValues.Text(Required(definition,"skillId"));
                if(category=="weapon")
                {
                    var declared=Items(weaponMeta.Get("weapon_skill_ids")).ToArray();
                    var bindings=Items(definition.Get("weaponBindings")).OfType<EvidenceObject>().Where(binding=>
                        EvidenceJson.PythonEquals(binding.Get("weaponId"),row.Get("weapon_template"))
                        && binding.Get("skillSlot") is EvidenceInteger { Value:var slot } && slot>=0 && slot<declared.Length
                        && EvidenceJson.PythonEquals(declared[(int)slot],definition.Get("skillId"))).ToArray();
                    if(bindings.Length!=1) continue;
                    if(!keys.TryGetValue(id,out var bbKeys)) keys[id]=bbKeys=new(StringComparer.Ordinal);
                    bbKeys.Add(bbKey.Value);
                    foreach(var skill in skills)
                    {
                        var raw=Text(skill.Get("skill_id"));var canonical=SkillIdentityCatalog.IsDigitText(raw) ? skillNumbers.GetValueOrDefault(raw) : raw;
                        if(canonical==id && skill.Get("bb") is EvidenceObject bb) observations.Add((Str(CatalogValues.Text(Required(row,"weapon_template"))),"weapon_skill",bb));
                    }
                }
                else
                    foreach(var effect in Items(row.Get("suit_effects")).OfType<EvidenceObject>())
                        if(EvidenceJson.PythonEquals(effect.Get("suit_id"),definition.Get("suitId")) && effect.Get("active") is EvidenceBoolean { Value:true }
                            && effect.Get("value") is EvidenceObject bb && Same(definition.Get("requiredPieces"),3) && Same(definition.Get("skillLevel"),1))
                        { var item=Required(effect,"suit_id");observations.Add((item,"equip_suit",bb));reviewedSuits.Add(CatalogValues.Text(item)); }
                foreach(var (item,source,bb) in observations)
                {
                    var value=BuffEvidence.OptionalFloat(bb.Get(bbKey.Value));var formula=modifier.Get("formulaItem") as EvidenceText;
                    if(value is not double valid || valid<0 || formula?.Value is not ("BaseAddition" or "Addition"))
                    {
                        Block(row,Obj(("reason",Str(value is null || value<0 ? "missing_item_damage_baseline_value" : "unmodeled_item_damage_attribute_stage")),
                            ("source_id",definition.Get("skillId")),("bb_key",bbKey),("formula_item",modifier.Get("formulaItem"))));continue;
                    }
                    var (zone,element)=AttributeEffects[type];
                    entries.Add(Obj(("source_type",Str(source)),("source_name",item),("item_id",item),("source_id",definition.Get("skillId")),("attr_index",definition.Get("attributeIndex")),
                        ("zone",Str(zone)),("zone_label",Str(ZoneLabels[zone])),("element",Str(element)),("attr_type",attr),("modifier_type",Int(formula.Value=="BaseAddition" ? 5 : 0)),
                        ("formula_item",formula),("bb_key",bbKey),("rate",new EvidenceReal(valid)),("source_resource_sha256",definition.Get("sourceSha256")),
                        ("evidence_kind",Str("current_official_item_skill_card_attribute")),("condition_text",Str(""))));
                }
            }
        return keys;
    }

    private static void ApplySuits(EvidenceObject row,List<EvidenceValue> baseline,HashSet<string> reviewedDamage)
    {
        var effects=Items(row.Get("suit_effects")).OfType<EvidenceObject>().ToArray();
        var suits=effects.Where(effect=>CatalogValues.Truth(effect.Get("suit_id"))).Select(effect=>Text(effect.Get("suit_id"))).ToHashSet(StringComparer.Ordinal);
        foreach(var effect in effects)
        {
            var id=Text(effect.Get("suit_id"));
            if(!ReviewedItemFields.Suits.TryGetValue(id,out var reviewed)) continue;
            var values=effect.Get("value") as EvidenceObject;
            if(values is null || values.Fields.Keys.Any(key=>!reviewed.Base.Contains(key) && !reviewed.Trigger.Contains(key)))
            {
                IEnumerable<string> unknown=values is null ? [] : values.Fields.Keys.Where(key=>!reviewed.Base.Contains(key) && !reviewed.Trigger.Contains(key)).Order(PythonDisplay.CodePointComparer);
                Block(row,Obj(("reason",Str("unmodeled_suit_static_semantics")),("suit_ids",new EvidenceArray([Str(id)])),("unknown_fields",new EvidenceArray(unknown.Select(key=>(EvidenceValue)Str(key)).ToArray()))));continue;
            }
            foreach(var field in reviewed.Base)
                if(BuffEvidence.OptionalFloat(values.Get(field)) is double value && value>=0)
                    baseline.Add(Obj(("source_type",Str("equip_suit_baseline")),("source_id",Str(id)),("field",Str(field)),("value",new EvidenceReal(value)),("evidence_kind",Str("official_EquipSuit_text"))));
        }
        suits.ExceptWith(ReviewedItemFields.Suits.Keys);suits.ExceptWith(reviewedDamage);
        if(suits.Count>0) Block(row,Obj(("reason",Str("unmodeled_suit_static_semantics")),("suit_ids",new EvidenceArray(suits.Order(PythonDisplay.CodePointComparer).Select(key=>(EvidenceValue)Str(key)).ToArray()))));
    }

    private void ApplyWeaponReview(EvidenceObject row,IReadOnlyList<EvidenceObject> skills,HashSet<string> declared,
        Dictionary<(string Skill,string Key),string> attackSpecs,Dictionary<string,HashSet<string>> damageKeys)
    {
        var weapon=Text(row.Get("weapon_template"));var definitions=ReviewedItemFields.Weapons.GetValueOrDefault(weapon);
        List<string> triggers=[];
        foreach(var skill in skills)
        {
            var canonical=Canonical(skill,declared);
            var known=canonical is not null && definitions?.TryGetValue(canonical,out var found)==true ? new HashSet<string>(found,StringComparer.Ordinal) : null;
            if(canonical is null || !declared.Contains(canonical)) known=null;
            var bb=Object(skill.Get("bb"));
            if(weapon=="wpn_funnel_0008" && canonical=="wpn_sp_attr_phy_spell_high" && declared.Contains(canonical)
                && BuffEvidence.OptionalFloat(bb.Get("atk"))==0)
            { known ??=new(StringComparer.Ordinal);known.Add("atk"); }
            if(canonical is not null && ReviewedItemFields.BasicAttack.Contains(canonical) && declared.Contains(canonical)) known=new(["atk"],StringComparer.Ordinal);
            var statics=attackSpecs.Keys.Where(key=>key.Skill==canonical).Select(key=>key.Key).ToArray();
            var damage=canonical is not null ? damageKeys.GetValueOrDefault(canonical) : null;
            if(statics.Length>0 || damage?.Count>0) { known ??=new(StringComparer.Ordinal);known.UnionWith(statics);if(damage is not null) known.UnionWith(damage); }
            if(known is null) triggers.Add("unreviewed_skill:"+CatalogValues.Text(CatalogValues.Or(skill.Get("skill_id"),Str("unknown"))));
            foreach(var key in bb.Fields.Keys) if(known?.Contains(key)!=true) triggers.Add(key);
        }
        if(triggers.Count>0)
            Block(row,Obj(("reason",Str("unmodeled_weapon_static_semantics")),("weapon_template",row.Get("weapon_template")),
                ("weapon_source_skill_ids",new EvidenceArray(skills.Where(skill=>skill.Get("skill_id") is not EvidenceNull).Select(skill=>skill.Get("skill_id")).ToArray())),
                ("trigger_blackboard_keys",new EvidenceArray(triggers.Distinct(StringComparer.Ordinal).Order(PythonDisplay.CodePointComparer).Select(key=>(EvidenceValue)Str(key)).ToArray()))));
    }

    private IReadOnlyList<EvidenceObject> Deduplicate(EvidenceObject row,List<EvidenceObject> entries)
    {
        List<EvidenceObject> result=[];Dictionary<string,EvidenceObject> seen=new(StringComparer.Ordinal);HashSet<string> conflicts=new(StringComparer.Ordinal);
        foreach(var entry in entries)
        {
            if(entry.Get("evidence_kind") is EvidenceText { Value:"official_EquipTable_attribute" }) { result.Add(entry);continue; }
            if(CatalogValues.Truth(entry.Get("condition_text"))) continue;
            var id=Text(entry.Get("source_id"));id=identities.CanonicalSkillNumber(id,null) ?? id;
            var parts=new[] { Text(entry.Get("source_type")),Text(entry.Get("item_id")),id,Text(entry.Get("attr_index")),Text(entry.Get("bb_key")),
                Text(entry.Get("attr_type")),Text(entry.Get("modifier_type")),Text(entry.Get("element")),string.Join(',',Items(entry.Get("skill_groups")).Select(value=>
                    value is EvidenceText text ? text.Value : throw new InvalidCastException("Skill group must be a string"))) };
            var key=EvidenceJsonSignature.Sorted(new EvidenceArray(parts.Select(value=>(EvidenceValue)Str(value)).ToArray()));
            if(conflicts.Contains(key)) continue;
            if(seen.TryGetValue(key,out var prior))
            {
                if(!EvidenceJson.PythonEquals(prior.Get("rate"),entry.Get("rate")))
                {
                    seen.Remove(key);result.RemoveAll(value=>ReferenceEquals(value,prior));conflicts.Add(key);
                    Block(row,Obj(("reason",Str("conflicting_static_multiplier_source")),("source_id",Str(id)),("bb_key",entry.Get("bb_key"))));
                }
                continue;
            }
            seen[key]=entry;result.Add(entry);
        }
        return result;
    }
}
