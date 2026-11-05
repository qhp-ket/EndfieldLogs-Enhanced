using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;
using static EndfieldLogs.Core.Reporting.StaticLoadoutEvidence;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Enrich an owned report loadout using exact official equipment attributes.</summary>
internal static class EquipmentBaselineDeriver
{
    private static readonly HashSet<BigInteger> Allocatable=[2,17,28,32,33,50,51,52,53,54];
    private static readonly HashSet<BigInteger> Abilities=[39,40,41,42,87];
    public static List<EvidenceObject> Apply(EvidenceObject row,IReadOnlyDictionary<string,EvidenceObject> catalog,List<EvidenceValue> baseline)
    {
        List<EvidenceObject> entries=[];
        var equips=Items(row.Get("equips")).OfType<EvidenceObject>().ToArray();
        if(equips.Any(equip=>equip.Get("slot") is EvidenceArray or EvidenceObject)) throw new InvalidCastException("Unhashable equipment slot");
        var complete=row.Get("equipment_snapshot_complete") is EvidenceBoolean { Value:true };
        foreach(var equip in equips)
        {
            var item=Text(equip.Get("item_id"));var slot=equip.Get("slot");
            var meta=catalog.GetValueOrDefault(item) ?? Empty;
            var proof=meta.Get("attribute_source_sha256");
            if(slot is not EvidenceInteger || equips.Count(other=>EvidenceJson.PythonEquals(other.Get("slot"),slot))!=1
                || meta.Get("attribute_modifiers") is not EvidenceArray modifiers || !Hash(proof))
            {
                Block(row,Obj(("item_id",Str(item)),("slot",slot),("reason",Str("missing_or_conflicting_equipment_attribute_evidence"))));continue;
            }
            Dictionary<BigInteger,HashSet<BigInteger>> levels=[];
            foreach(var level in Items(equip.Get("enhance_levels")).OfType<EvidenceObject>())
                if(level.Get("index") is EvidenceInteger index && level.Get("level") is EvidenceInteger value)
                {
                    if(!levels.TryGetValue(index.Value,out var values)) levels[index.Value]=values=[];
                    values.Add(value.Value);
                }
            if(complete)
                foreach(var modifier in modifiers.Items.OfType<EvidenceObject>())
                    if(modifier.Get("attrIndex") is EvidenceInteger index && !levels.ContainsKey(index.Value)) levels[index.Value]=[0];
            (EvidenceValue Index,double?[] Values,HashSet<BigInteger> Candidates,BigInteger? Level) Values(EvidenceObject modifier)
            {
                var index=modifier.Get("attrIndex");
                if(index is EvidenceObject or EvidenceArray) throw new InvalidCastException("Unhashable attribute index");
                var matching=levels.FirstOrDefault(pair=>EvidenceJson.PythonEquals(new EvidenceInteger(pair.Key),index));
                var candidates=matching.Value ?? [];
                return (index,modifier.Get("attrValues") is EvidenceArray values ? values.Items.Select(BuffEvidence.OptionalFloat).ToArray() : [],
                    candidates,candidates.Count==1 ? candidates.Single() : null);
            }
            static double? At(double?[] values,BigInteger? level)=>level is BigInteger index && index>=0 && index<values.Length && values.All(value=>value is not null) ? values[(int)index] : null;
            void Display(EvidenceValue index,double value,BigInteger? level)
            {
                if(equip.Get("stats") is EvidenceArray stats && index is EvidenceInteger number && number.Value>=0 && number.Value<stats.Items.Count
                    && stats.Items[(int)number.Value] is EvidenceObject stat && stat.Get("value") is EvidenceText { Value:"unknown" })
                {
                    Fields(stat)["value"]=new EvidenceReal(value);Fields(stat)["level"]=BuffEvidence.Number(level);
                    Fields(stat)["value_source"]=Str("official_EquipTable_attribute_zero_or_exact");
                }
            }
            EvidenceObject Baseline(BigInteger type,EvidenceValue index,double value,BigInteger? level,bool enums,BigInteger formula,BigInteger target,string kind)
            {
                var entry=Obj(("source_type",Str("equip_baseline")),("source_id",Str(item)),("source_slot",slot),("attr_type",new EvidenceInteger(type)),
                    ("attr_index",index),("value",new EvidenceReal(value)),("enhance_level",BuffEvidence.Number(level)),("evidence_kind",Str(kind)),("source_table_sha256",proof));
                if(enums) { Fields(entry)["modifier_type"]=new EvidenceInteger(formula);Fields(entry)["modify_attribute_type"]=new EvidenceInteger(target); }
                return entry;
            }
            foreach(var input in modifiers.Items)
            {
                if(input is not EvidenceObject modifier) { Block(row,Obj(("item_id",Str(item)),("reason",Str("invalid_attribute_row"))));continue; }
                if(modifier.Get("attrType") is not EvidenceInteger attr || modifier.Get("modifierType") is not EvidenceInteger formula || modifier.Get("modifyAttributeType") is not EvidenceInteger target)
                { Block(row,Obj(("item_id",Str(item)),("reason",Str("invalid_attribute_enum"))));continue; }
                var type=attr.Value;var stage=formula.Value;var destination=target.Value;
                if(complete && !Allocatable.Contains(type) && !Abilities.Contains(type))
                {
                    var (index,values,_,level)=Values(modifier);var value=At(values,level);
                    if(value is double valid && valid>=0)
                    { baseline.Add(Baseline(type,index,valid,level,true,stage,destination,"official_EquipTable_attribute_zero_or_exact"));Display(index,valid,level);continue; }
                }
                if(complete && destination.IsZero && Abilities.Contains(type) && stage==5)
                {
                    var (index,values,_,level)=Values(modifier);var value=At(values,level);
                    if(value is double valid && valid>=0)
                    { baseline.Add(Baseline(type,index,valid,level,false,stage,destination,"official_EquipTable_attribute_zero_or_exact"));Display(index,valid,level);continue; }
                }
                if(!destination.IsZero || Abilities.Contains(type) || type==61 || type==2 && stage!=6 && stage!=7)
                {
                    Block(row,Obj(("item_id",Str(item)),("slot",slot),("attr_type",attr),("modifier_type",formula),("modify_attribute_type",target),
                        ("reason",Str("unmodeled_static_attribute_mechanism"))));continue;
                }
                if(!destination.IsZero || !Allocatable.Contains(type) || type!=2 && stage!=5) continue;
                var data=Values(modifier);double? rate=null;
                if(data.Values.Length>0 && data.Values.All(value=>value is not null) && data.Index is EvidenceInteger)
                {
                    if(data.Candidates.Count==1) rate=At(data.Values,data.Level);
                    else if(data.Candidates.Count==0 && data.Values.Distinct().Count()==1) rate=data.Values[0];
                }
                if(rate is not double amount || amount<0)
                {
                    Block(row,Obj(("item_id",Str(item)),("slot",slot),("attr_index",data.Index),("attr_type",attr),
                        ("reason",Str("missing_or_conflicting_equipment_enhancement"))));continue;
                }
                Display(data.Index,amount,data.Level);
                if(type==2 && stage==7)
                { baseline.Add(Baseline(type,data.Index,amount,data.Level,true,stage,destination,"official_EquipTable_flat_attack"));continue; }
                var (zone,element)=AttributeEffects[type];
                entries.Add(Obj(("source_type",Str("equip")),("source_name",Str(Text(CatalogValues.Or(meta.Get("item_name"),Str(item))))),
                    ("source_id",Str(item)),("source_slot",slot),("label",Str("attribute_type_"+type)),("zone",Str(zone)),("zone_label",Str(ZoneLabels[zone])),
                    ("element",Str(element)),("rate",new EvidenceReal(amount)),("attr_type",attr),("modifier_type",formula),("attr_index",data.Index),
                    ("enhance_level",BuffEvidence.Number(data.Level)),("skill_groups",NoItems),("condition_text",Str("")),("evidence_kind",Str("official_EquipTable_attribute")),("source_table_sha256",proof)));
            }
        }
        return entries;
    }
}
