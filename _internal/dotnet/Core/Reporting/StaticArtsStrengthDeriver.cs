using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

public sealed record StaticArtsStrengthResult(EvidenceObject Loadout,IReadOnlyList<EvidenceObject> Entries);

/// <summary>Static arts points require an exact equipment slot or a version-bound card property.</summary>
public sealed class StaticArtsStrengthDeriver(EvidenceObject catalog,IReadOnlyDictionary<string,EvidenceObject> weapons,
    IReadOnlyDictionary<string,string> skillNumbers)
{
    private static readonly EvidenceObject Empty=new(new Dictionary<string,EvidenceValue>());
    private static readonly EvidenceArray NoItems=new([]);
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value)=>CatalogValues.Iterable(CatalogValues.Or(value,NoItems));
    private static EvidenceObject Object(EvidenceValue value)=>CatalogValues.Or(value,Empty) as EvidenceObject
        ?? throw new InvalidDataException("Static card field must be an object");
    private static bool Same(EvidenceValue value,int number)=>EvidenceJson.PythonEquals(value,new EvidenceInteger(number));
    private static bool Hash(EvidenceValue value)=>Regex.IsMatch(Text(value),@"\A[0-9a-f]{64}\z");
    private static bool NonnegativeInteger(EvidenceValue value)=>value is EvidenceInteger { Value:var number } && number>=0;
    private static EvidenceValue Required(EvidenceObject row,string key)=>row.Fields.TryGetValue(key,out var value) ? value : throw new KeyNotFoundException(key);

    public static StaticArtsStrengthDeriver Load(ResourceFiles files)=>new(files.ReadRelative("data/local_static/skill/item_arts_strength_catalog.json") as EvidenceObject ?? Empty,
        new WeaponCatalog(files).Entries,new SkillResourceCatalog(files).Skills);

    public StaticArtsStrengthResult Derive(EvidenceObject source)
    {
        var fields=new Dictionary<string,EvidenceValue>(((EvidenceObject)BuffEvidence.Clone(source)).Fields,StringComparer.Ordinal);
        var row=new EvidenceObject(fields);
        Dictionary<string,(EvidenceArray Identity,List<EvidenceObject> Values)> candidates=new(StringComparer.Ordinal);
        void Add(EvidenceArray identity,EvidenceObject entry)
        {
            var key=EvidenceJsonSignature.Sorted(identity);
            if(!candidates.TryGetValue(key,out var group)) candidates[key]=group=(identity,[]);
            group.Values.Add(entry);
        }
        foreach(var attribute in Items(row.Get("equipment_baseline_attributes")).OfType<EvidenceObject>())
        {
            if(attribute.Get("source_type") is not EvidenceText { Value:"equip_baseline" }
                || !Same(attribute.Get("attr_type"),87)
                || attribute.Get("evidence_kind") is not EvidenceText { Value:"official_EquipTable_attribute_zero_or_exact" }
                || attribute.Get("source_id") is not EvidenceText { Value.Length:>0 }
                || !new[] { "source_slot","attr_index","enhance_level" }.All(key=>NonnegativeInteger(attribute.Get(key)))
                || !Hash(attribute.Get("source_table_sha256"))
                || BuffEvidence.OptionalFloat(attribute.Get("value")) is not double value || value<0) continue;
            Add(new([new EvidenceText("equip"),attribute.Get("source_slot"),attribute.Get("source_id"),attribute.Get("attr_index")]),
                BuffEvidence.Object(("source_type",new EvidenceText("equip")),("source_name",attribute.Get("source_id")),("source_id",attribute.Get("source_id")),
                    ("source_slot",attribute.Get("source_slot")),("attr_index",attribute.Get("attr_index")),("enhance_level",attribute.Get("enhance_level")),
                    ("rate",new EvidenceReal(value)),("source_table_sha256",attribute.Get("source_table_sha256")),("evidence_kind",attribute.Get("evidence_kind"))));
        }
        var decoder=catalog.Get("decoder") as EvidenceObject;
        var trusted=Same(catalog.Get("schemaVersion"),1) && catalog.Get("source") is EvidenceText { Value:"current_official_item_skill_card_attribute" }
            && decoder is not null && NativeDamageSemanticsBinding.Evidence.Fields.All(pair=>EvidenceJson.PythonEquals(pair.Value,decoder.Get(pair.Key)));
        var document=trusted ? catalog : Empty;
        var weapon=Text(row.Get("weapon_template"));
        var declared=Items(weapons.GetValueOrDefault(weapon)?.Get("weapon_skill_ids") ?? EvidenceNull.Value).ToArray();
        foreach(var category in new[] { "suit","weapon" })
            foreach(var definition in Items(document.Get(category+"Entries")).OfType<EvidenceObject>())
            {
                var modifier=Object(definition.Get("modifier"));
                var param=Object(modifier.Get("param"));
                if(modifier.Get("$type") is not EvidenceText { Value:"Beyond.Gameplay.AttributeModifierData.AttributeModifier" }
                    || modifier.Get("attributeType") is not EvidenceText { Value:"PhysicalAndSpellInflictionEnhance" }
                    || modifier.Get("formulaItem") is not EvidenceText { Value:"BaseAddition" }
                    || modifier.Get("modifyAttributeType") is not EvidenceText { Value:"Specific" }
                    || param.Get("useBlackboardKey") is not EvidenceBoolean { Value:true }
                    || !EvidenceJson.PythonEquals(param.Get("blackboardKey"),definition.Get("bbKey"))
                    || definition.Get("bbKey") is not EvidenceText { Value.Length:>0 }
                    || !NonnegativeInteger(definition.Get("attributeIndex"))
                    || definition.Get("sourceBytes") is not EvidenceInteger { Value:var bytes } || bytes<=0
                    || !EvidenceJson.PythonEquals(definition.Get("consumedBytes"),definition.Get("sourceBytes"))
                    || !Hash(definition.Get("sourceSha256"))) continue;
                List<(EvidenceValue Item,string Type,string Name,EvidenceObject Blackboard)> rows=[];
                if(category=="weapon")
                {
                    var bindings=Items(definition.Get("weaponBindings")).OfType<EvidenceObject>()
                        .Where(binding=>EvidenceJson.PythonEquals(binding.Get("weaponId"),new EvidenceText(weapon))
                            && binding.Get("skillSlot") is EvidenceInteger { Value:var slot } && slot>=0 && slot<declared.Length
                            && EvidenceJson.PythonEquals(declared[(int)slot],definition.Get("skillId"))).ToArray();
                    if(bindings.Length!=1 || !EvidenceJson.PythonEquals(
                        BuffEvidence.Text(skillNumbers.GetValueOrDefault(CatalogValues.Text(definition.Get("numericSkillId")))),definition.Get("skillId"))) continue;
                    foreach(var skill in Items(CatalogValues.Or(row.Get("weapon_source_skills"),row.Get("weapon_refine_stats"),NoItems)).OfType<EvidenceObject>())
                    {
                        var id=Text(skill.Get("skill_id"));
                        var canonical=SkillIdentityCatalog.IsDigitText(id) ? skillNumbers.GetValueOrDefault(id) : id;
                        if(EvidenceJson.PythonEquals(BuffEvidence.Text(canonical),definition.Get("skillId")) && skill.Get("bb") is EvidenceObject bb)
                            rows.Add((new EvidenceText(weapon),"weapon_skill",weapon,bb));
                    }
                }
                else
                    foreach(var effect in Items(row.Get("suit_effects")).OfType<EvidenceObject>())
                        if(EvidenceJson.PythonEquals(effect.Get("suit_id"),definition.Get("suitId"))
                            && effect.Get("active") is EvidenceBoolean { Value:true } && effect.Get("value") is EvidenceObject bb)
                            rows.Add((Required(effect,"suit_id"),"equip_suit",CatalogValues.Text(CatalogValues.Or(effect.Get("suit_name"),Required(effect,"suit_id"))),bb));
                foreach(var (item,type,name,bb) in rows)
                {
                    var bbKey=((EvidenceText)definition.Get("bbKey")).Value;
                    if(BuffEvidence.OptionalFloat(bb.Get(bbKey)) is not double value || value<0) continue;
                    Add(new([new EvidenceText(category),item,Required(definition,"skillId"),definition.Get("attributeIndex")]),
                        BuffEvidence.Object(("source_type",new EvidenceText(type)),("source_name",new EvidenceText(name)),("source_id",definition.Get("skillId")),
                            ("item_id",item),("attr_index",definition.Get("attributeIndex")),("bb_key",new EvidenceText(bbKey)),("rate",new EvidenceReal(value)),
                            ("source_resource_sha256",definition.Get("sourceSha256")),("evidence_kind",new EvidenceText("current_official_item_skill_card_attribute"))));
                }
            }
        List<EvidenceObject> entries=[];
        foreach(var (identity,values) in candidates.Values)
        {
            var signatures=values.Select(value=>EvidenceJsonSignature.Sorted(new EvidenceObject(value.Fields.Where(pair=>pair.Key!="source_name")
                .ToDictionary(pair=>pair.Key,pair=>pair.Value,StringComparer.Ordinal)))).Distinct(StringComparer.Ordinal).ToArray();
            if(signatures.Length!=1)
            {
                var unresolved=fields.TryGetValue("rdps_unresolved_static_multiplier_sources",out var existing)
                    ? existing as EvidenceArray ?? throw new InvalidDataException("Static blockers must be a list") : NoItems;
                fields["rdps_unresolved_static_multiplier_sources"]=new EvidenceArray([..unresolved.Items,
                    BuffEvidence.Object(("reason",new EvidenceText("conflicting_static_arts_strength_source")),("identity",identity))]);
                continue;
            }
            var entry=new Dictionary<string,EvidenceValue>(values[0].Fields,StringComparer.Ordinal);
            if(values.Select(value=>CatalogValues.Text(value.Get("source_name"))).Distinct(StringComparer.Ordinal).Count()!=1)
                entry["source_name"]=new EvidenceText(CatalogValues.Text(CatalogValues.Or(values[0].Get("item_id"),values[0].Get("source_id"))));
            if(((EvidenceReal)entry["rate"]).Value<=0) continue;
            entry["attr_type"]=new EvidenceInteger(87);entry["zone"]=new EvidenceText("arts_strength");
            entry["zone_label"]=new EvidenceText("源石技艺强度");entry["element"]=new EvidenceText("all");entry["condition_text"]=new EvidenceText("");
            entries.Add(new(entry));
        }
        return new(row,entries);
    }
}
