using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Effects;

public sealed record BuffLabelsResult(EvidenceObject Record,IReadOnlyList<string> Labels);

/// <summary>Display labels retain anomaly evidence and typed semantics independently of allocation.</summary>
public sealed class BuffLabelCatalog(SemanticEffectCatalog semantic,BuffDisplayClassification classification,PacketEffectDisplayCatalog packets)
{
    private static readonly Dictionary<string,int> Priority=new(StringComparer.Ordinal)
    {
        ["攻击提升"]=0,["增伤"]=1,["增幅"]=2,["导电"]=2,["腐蚀"]=2,["燃烧"]=2,["冻结"]=2,["碎冰"]=2,["法术爆发"]=2,
        ["破防"]=2,["倒地"]=2,["击飞"]=2,["猛击"]=2,["脆弱"]=2,["物理脆弱"]=2,["物理脆弱 / 碎甲"]=2,["碎甲"]=2,
        ["易伤"]=3,["承伤易伤"]=3,["减抗"]=4,["连击增伤"]=5,["暴击"]=6,["暴击伤害"]=7,
    };
    private static readonly HashSet<string> NoiseKeys=new([
        "atb","atk_duration","cd","comboskill_cooldown","common_character_perfect_dodge","count","damage_interval",
        "def_decrease_tick","def_decrease_tick_final","duration","dodgeSkillId","end_early","heal_value","healvalue",
        "hit_spellduration","hp_up","imbue_scale","infliction_num","max_stack","max_def_decrease","max_def_decrease_final",
        "phy_spell_up","poise","posie","potential_1","potential_3","potential_3_atb","rate_add","shatter_dmg","skill_bg_type",
        "speed","stack_cond","start_def_decrease","time_warning","usp_everyone","usp_self","vfx_buff_name"],StringComparer.Ordinal);
    private static readonly Dictionary<string,string[]> IgnoredKeys=new(StringComparer.Ordinal)
    {
        ["buff_chr_0011_seraph_atk_buff"]=["atk_up"],["buff_chr_0011_seraph_potential_1_atkup"]=["atk_up"],
        ["buff_equipsuit_atk_02"]=["dmg_up","max_stack"],["buff_physical_do_fracture"]=["atk_scale"],
        ["buff_wpn_funnel_0006_valid"]=["atk_up"],["buff_wpn_funnel_0011_valid"]=["nature_dmg_up"],
        ["buff_wpn_sword_0012_atk_up"]=["atk_up"],["buff_wpn_sword_0013_atk_up"]=["atk_up","atk_up_add","atk_up_mult"],
        ["buff_wpn_sword_0016_team"]=["phy_dmg_up","phy_dmg_up2"],["buff_wpn_sword_0016_valid"]=["phy_dmg_up","phy_dmg_up2"],
        ["buff_wpn_sword_0020_cryst"]=["atk_up"],
    };
    private static readonly Dictionary<int,string> AttributeLabels=new()
    {
        [2]="攻击提升",[9]="暴击",[10]="暴击伤害",[17]="增伤",[28]="增伤",[32]="增伤",[33]="增伤",[50]="增伤",[51]="增伤",[53]="增伤",
        [65]="增幅",[66]="增幅",[67]="增幅",[68]="增幅",[70]="易伤",
    };
    internal static string? AttributeLabel(BigInteger attribute) => attribute >= int.MinValue && attribute <= int.MaxValue
        ? AttributeLabels.GetValueOrDefault((int)attribute) : null;
    private static readonly Dictionary<string,string> ZoneLabels=new(StringComparer.Ordinal)
    {
        ["atk"]="攻击提升",["dmg_inc"]="增伤",["amp"]="增幅",["fragile"]="脆弱",["vuln_taken"]="易伤",["res"]="减抗",
        ["combo"]="连击增伤",["arts_strength"]="源石技艺强度",["crit"]="暴击",["speedup"]="加速",["slow"]="缓速",
    };
    internal static string ZoneLabel(string zone) => ZoneLabels.GetValueOrDefault(zone, zone);
    private static readonly HashSet<string> Lifeng=new(["buff_chr_0015_lifeng_purify","buff_chr_0015_lifeng_normal_skill_debuff",
        "buff_chr_0015_lifeng_normal_skill_debuff_icon"],StringComparer.Ordinal);
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static IEnumerable<EvidenceValue> Items(EvidenceValue value)=>CatalogValues.Iterable(CatalogValues.Or(value,new EvidenceArray([])));
    private static bool Ignored(string buff,string key)=>IgnoredKeys.TryGetValue(buff.ToLowerInvariant(),out var keys) && keys.Contains(key.ToLowerInvariant(),StringComparer.Ordinal);
    private static bool DamageIncrease(string key)=>key is "dmg_up" or "pd_up" or "spell_up" || key.EndsWith("_dmg_up",StringComparison.Ordinal) || key.EndsWith("_dmg_up2",StringComparison.Ordinal);
    private static bool Has(string value,params string[] tokens)=>tokens.Any(token=>value.Contains(token,StringComparison.Ordinal));

    public static string? ZoneFromLabel(string label)=>label switch
    {
        "攻击提升"=>"atk","增伤"=>"dmg_inc","增幅"=>"amp","脆弱" or "物理脆弱"=>"fragile",
        "物理脆弱 / 碎甲" or "碎甲" or "易伤" or "承伤易伤"=>"vuln_taken","减抗"=>"res","连击增伤"=>"combo",
        "源石技艺强度"=>"arts_strength","加速"=>"speedup","缓速"=>"slow",_=>null,
    };

    public BuffLabelsResult Collect(EvidenceObject source)
    {
        var key=CatalogValues.Text(CatalogValues.Or(source.Get("event_key"),new EvidenceText("unknown_buff")));
        var enemy=CatalogValues.Truth(source.Get("target_enemy_key"));
        var provider=Text(source.Get("source_character_key"));
        var raw=CatalogValues.Or(source.Get("bb_values"),new EvidenceObject(new Dictionary<string,EvidenceValue>()));
        if(raw is not EvidenceObject blackboard) throw new InvalidDataException("Label blackboard must be an object");
        var bb=blackboard.Fields.Keys.Select(key=>key.ToLowerInvariant()).ToHashSet(StringComparer.Ordinal);
        var resolved=semantic.Collect(source);
        var record=resolved.Record;
        var effects=resolved.Effects;
        var labels=Anomalies(key,provider,enemy,bb);
        BuffLabelsResult Result()=>new(record,labels.OrderBy(label=>Priority.GetValueOrDefault(label,99)).ThenBy(label=>label,PythonDisplay.CodePointComparer).ToArray());
        if(BuffDisplayClassification.IgnoresRecordRate(record)) return Result();
        if((BuffDisplayClassification.IsNoise(key) || BuffDisplayClassification.IgnoresRate(key)) && effects.Count==0) return Result();
        if(classification.IsEffectlessWrapper(record) && effects.Count==0) return Result();
        if(key=="buff_common_affixes_combo_trigger") labels.Add("连击增伤");
        if(Lifeng.Contains(key)) labels.Add("物理脆弱");
        if(key=="buff_chr_0029_pograni_talent2") labels.Add("铁卫标记");
        Dictionary<string,string> special=new(StringComparer.Ordinal);
        if(bb.Contains("physical_res_down"))
        {
            var label=provider=="chr_0029_pograni" ? "碎甲" : "物理脆弱";
            special["physical_res_down"]=label; labels.Add(label);
        }
        if(bb.Contains("phy_resist_down")) special["phy_resist_down"]="物理脆弱";
        var semanticKeys=effects.Select(effect=>Text(effect.Get("bb_key"))).Where(key=>key.Length>0).ToHashSet(StringComparer.Ordinal);
        var semanticLower=semanticKeys.Select(key=>key.ToLowerInvariant()).ToHashSet(StringComparer.Ordinal);
        foreach(var effect in packets.Static(record).Where(effect=>!semanticKeys.Contains(Text(effect.Get("bb_key")))).Concat(packets.Dynamic(record)))
            if(ZoneLabels.TryGetValue(Text(effect.Get("zone")),out var label)) labels.Add(label);
        foreach(var effect in effects)
        {
            var zone=Text(effect.Get("zone"));
            if(zone=="vuln_taken") labels.Add("承伤易伤");
            else if(ZoneLabels.TryGetValue(zone,out var label)) labels.Add(label);
        }
        foreach(var value in Items(record.Get("bb_keys")))
        {
            var text=CatalogValues.Text(value); var lower=text.ToLowerInvariant();
            if(semanticLower.Contains(lower)) continue;
            if(special.TryGetValue(lower,out var label)) labels.Add(label);
            else if(BlackboardLabel(text,key,enemy) is string inferred) labels.Add(inferred);
        }
        var modifiers=record.Get("attr_mods");
        var rows=CatalogValues.Truth(modifiers) ? Items(modifiers)
            : Items(record.Get("attr_types")).Select(type=>(EvidenceValue)new EvidenceObject(new Dictionary<string,EvidenceValue> { ["attr_type"]=type,["bb_key"]=new EvidenceText("") }));
        foreach(var value in rows)
        {
            if(value is not EvidenceObject modifier) throw new InvalidDataException("Label attribute modifier must be an object");
            BigInteger type;
            try { type=Integer(modifier.Get("attr_type")); }
            catch(Exception error) when(error is InvalidCastException or FormatException) { continue; }
            var originalKey=Text(modifier.Get("bb_key"));
            var lower=originalKey.ToLowerInvariant();
            if(Ignored(key,lower)) continue;
            if(special.TryGetValue(lower,out var label)) { labels.Add(label); continue; }
            if(type>=65 && type<=68 && DamageIncrease(originalKey.ToLowerInvariant())) continue;
            if(originalKey is "def_decrease" or "additional_def_decrease") { labels.Add("减抗"); continue; }
            if(type>=70 && type<86) { labels.Add("脆弱"); continue; }
            if(type>=int.MinValue && type<=int.MaxValue && AttributeLabels.TryGetValue((int)type,out var attribute)) labels.Add(attribute);
        }
        return Result();
    }

    private static HashSet<string> Anomalies(string key,string source,bool enemy,IReadOnlySet<string> bb)
    {
        HashSet<string> labels=new(StringComparer.Ordinal);
        var lower=key.ToLowerInvariant();
        var physical=lower switch { "buff_physical_no_guard"=>"破防","buff_physical_knockdown"=>"倒地","buff_physical_airborne"=>"击飞",
            "buff_physical_crushed" or "buff_common_cryst_triggered_physical_break"=>"猛击",_=>null };
        if(physical is not null) labels.Add(physical);
        if(lower.Contains("conduct_triggered",StringComparison.Ordinal)) labels.Add("导电");
        if(Has(lower,"corrupt_triggered","corrupt_do") || Regex.IsMatch(lower,@"^buff_common_(?:try_)?natural_(?:fire|pulse|cryst|natural)_triggered(?:_wrapper)?$")) labels.Add("腐蚀");
        if(Has(lower,"fire_fire_triggered","burn")) labels.Add("燃烧");
        if(Regex.IsMatch(lower,@"^buff_common_(fire|pulse|cryst|natural|spell)_\1_triggered(?:_wrapper|_do)?$")) labels.Add("法术爆发");
        if(lower.Contains("frozen",StringComparison.Ordinal) && !bb.Contains("physical_res_down") && !bb.Contains("phy_resist_down")) labels.Add("冻结");
        if(enemy && source=="chr_0029_pograni" && bb.Contains("physical_res_down")) labels.Add("碎甲");
        return labels;
    }

    private static string? BlackboardLabel(string raw,string buff,bool enemy)
    {
        var key=raw.ToLowerInvariant();
        if(key.Length==0 || NoiseKeys.Contains(key) || Ignored(buff,key)) return null;
        if(key is "atk" or "atk_up" or "atk_up2") return "攻击提升";
        if(key is "phy_resist_down" or "physical_res_down" or "physical_vulnerable_dmg_increase") return "物理脆弱 / 碎甲";
        if(key=="ratio_speed") return "加速";
        if(key=="ratio_speedreduction") return "缓速";
        if(key is "crit_up" or "crit_up2" or "critical_rate") return "暴击";
        if(key is "crit_dmg" or "critical_damage_inc") return "暴击伤害";
        if(key is "fire_up" or "pulse_up" or "cryst_up" or "crystal_up" or "natural_up" or "physical_up" or "physic_up") return enemy ? "脆弱" : "增幅";
        if(DamageIncrease(key) || key.EndsWith("_up_valid",StringComparison.Ordinal)) return "增伤";
        if(key.EndsWith("_taken_up",StringComparison.Ordinal)) return "承伤易伤";
        if(key=="def_down_damage") return "脆弱";
        if(key is "def_decrease" or "additional_def_decrease") return "减抗";
        if(key.EndsWith("_vul",StringComparison.Ordinal) || key.StartsWith("rate_",StringComparison.Ordinal) && key.Contains("vulnerable",StringComparison.Ordinal)) return "脆弱";
        if(key.StartsWith("enhance_",StringComparison.Ordinal)) return "增幅";
        if(Regex.IsMatch(key,@"^(?:.+_)?taken_up_(?:physical|physic|fire|pulse|cryst|crystal|natural|spell)$")
            || Regex.IsMatch(key,@"^damage_taken_up_(?:physical|physic|fire|pulse|cryst|crystal|natural|spell)$")) return "承伤易伤";
        if(key.EndsWith("_resistance_decrease",StringComparison.Ordinal) || key.EndsWith("_resistance_down",StringComparison.Ordinal)) return "承伤易伤";
        if(key.EndsWith("_res_down",StringComparison.Ordinal) || key.StartsWith("ignore_",StringComparison.Ordinal) && key.EndsWith("_resist",StringComparison.Ordinal)) return "减抗";
        if(key=="combo_damageup") return "连击增伤";
        var lower=buff.ToLowerInvariant();
        if(key is "atk_scale" or "extra_atk_scale" or "burning_atk_scale" && enemy)
            return Has(lower,"vulnerable","fragile","fracture") ? "脆弱" : null;
        if(key=="rate")
        {
            if(Lifeng.Contains(lower)) return "物理脆弱";
            if(Has(lower,"vulnerable","fragile","waterdebuff")) return "脆弱";
            if(lower.Contains("enhance_",StringComparison.Ordinal)) return "增幅";
            if(Has(lower,"spellup","dmg","damage_increase")) return "增伤";
            if(lower.Contains("criticalrate",StringComparison.Ordinal)) return "暴击";
            if(lower.Contains("combo_damage",StringComparison.Ordinal)) return "连击增伤";
        }
        return null;
    }

    private static BigInteger Integer(EvidenceValue value)=>value switch
    {
        EvidenceInteger integer=>integer.Value,EvidenceBoolean flag=>flag.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value)=>new BigInteger(real.Value),
        EvidenceReal real when double.IsNaN(real.Value)=>throw new FormatException("cannot convert float NaN to integer"),
        EvidenceReal=>throw new OverflowException("cannot convert float infinity to integer"),
        EvidenceText text=>Ingestion.TraceFields.OptionalInteger(text.Value) ?? throw new FormatException("Invalid attribute type"),
        _=>throw new InvalidCastException("Invalid attribute type"),
    };
}
