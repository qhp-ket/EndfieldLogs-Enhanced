namespace EndfieldLogs.Core.Reporting;

/// <summary>Reviewed baseline and trigger fields remain scoped to their exact item and skill.</summary>
internal static class ReviewedItemFields
{
    private static HashSet<string> Keys(params string[] keys)=>new(keys,StringComparer.Ordinal);
    public static readonly IReadOnlyDictionary<string,(HashSet<string> Base,HashSet<string> Trigger)> Suits=new Dictionary<string,(HashSet<string>,HashSet<string>)>(StringComparer.Ordinal)
    {
        ["suit_expend_spell01"]=(Keys("atk_up"),Keys("spell_dmg_up","duration","max_stack")),
        ["suit_atb01"]=(Keys("comboskill_cooldown"),Keys("dmg_up","duration")),
        ["suit_heal01"]=(Keys("heal_up"),Keys("dmg_taken_down","dmg_taken_down2","duration")),
        ["suit_combo_cd01"]=(Keys("comboskill_cooldown"),Keys("spell_up","duration","max_stack")),
        ["suit_fire_natr01"]=(Keys("phy_spell_up"),Keys("fire_dmg_up","nature_dmg_up","duration","duration2")),
        ["suit_usp02"]=(Keys("hp_up"),Keys("dmg_up","duration")),
    };
    public static readonly IReadOnlySet<string> BasicAttack=Keys("wpn_sp_attr_atk_high","wpn_sp_attr_atk_mid","wpn_sp_attr_atk_low");
    public static readonly IReadOnlyDictionary<string,IReadOnlyDictionary<string,HashSet<string>>> Weapons=new Dictionary<string,IReadOnlyDictionary<string,HashSet<string>>>(StringComparer.Ordinal)
    {
        ["wpn_sword_0006"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_wisd_high"]=Keys("wisd"),["wpn_sp_attr_atk_high"]=Keys("atk"),["sk_wpn_sword_0006"]=Keys("fire_dmg_up","duration","normal_atk_up") },
        ["wpn_sword_0007"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_wisd_mid"]=Keys("wisd"),["wpn_sp_attr_usgs_mid"]=Keys("usgs"),["sk_wpn_sword_0007"]=Keys("atk_up","phy_spell_up") },
        ["wpn_pistol_0012"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_agi_mid"]=Keys("agi"),["wpn_sp_attr_usgs_mid"]=Keys("usgs"),["sk_wpn_pistol_0012"]=Keys("atk_up","duration","count","nature_dmg_up","nature_dmg_up_mult") },
        ["wpn_funnel_0008"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_main_high"]=Keys("mainattr"),["wpn_sp_attr_phy_spell_high"]=Keys("physpell"),["sk_wpn_funnel_0008"]=Keys("second_attr_up","duration","lv","spell_damage_taken_up") },
        ["wpn_funnel_0013"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_wisd_high"]=Keys("wisd"),["wpn_sp_attr_heal_high"]=Keys("heal"),["sk_wpn_funnel_0013"]=Keys("second_attr_up","duration","lv","spell_dmg_taken_up") },
        ["wpn_funnel_0017"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_will_high"]=Keys("will"),["wpn_sp_attr_electrondam_high"]=Keys("electrondam"),["sk_wpn_funnel_0017"]=Keys("atk_up","duration","max_stack","pulse_dmg_up2") },
        ["wpn_sword_0012"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_will_high"]=Keys("will"),["wpn_sp_attr_atk_high"]=Keys("atk"),["sk_wpn_sword_0012"]=Keys("atk_up","atk_up2","duration","max_stack","lv") },
        ["wpn_lance_0014"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_will_high"]=Keys("will"),["wpn_sp_attr_heal_high"]=Keys("heal"),["sk_wpn_lance_0014"]=Keys("atk_up","duration","max_stack","primary_attr_up") },
        ["wpn_funnel_0004"]=new Dictionary<string,HashSet<string>> { ["wpn_attr_wisd_mid"]=Keys("wisd"),["wpn_sp_attr_electrondam_mid"]=Keys("electrondam"),["sk_wpn_funnel_0004"]=Keys("phy_spell_up","dmg_up","duration") },
    };
}
