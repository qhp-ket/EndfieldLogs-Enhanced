using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Effects;

/// <summary>Display suppression based on explicit wrapper roles and existing semantic hints.</summary>
public sealed class BuffDisplayClassification(PacketBuffCatalog packets,
    IReadOnlyDictionary<string,EvidenceObject> semantics, IReadOnlyDictionary<string,EvidenceObject> classifier)
{
    private static readonly string[] NoisePrefixes = ["buff_common_vfx_","buff_common_normal_skill_fx_",
        "buff_common_combo_attack_fx","buff_common_dash","buff_common_dash_","buff_common_full_immune_weak"];
    private static readonly HashSet<string> NoiseIds = new(["buff_chr_0011_seraph_mainchr_heal","buff_chr_0023_antal_ultimate_icon",
        "buff_chr_0023_antal_ultimate_icon_2","buff_common_obtain_ultimate_sp","buff_common_dash_behit_listener",
        "buff_common_poise_break_damage_taken_scale"],StringComparer.Ordinal);
    private static readonly Regex[] RateIgnored = new[]
    {
        @"^buff_equipsuit_(?:usp_02|combo_cd01)$", @"buff_common_affixes_slow",
        @"^buff_chr_0023_antal_(?:normal_skill|tageffect|utimate_skill)$", @"^buff_common_affixes_shelter_default_child$",
        @"buff_common_affixes_vulnerable_spell",
        @"^buff_common_(?:physical|fire|pulse|cryst|natural|spell)_(?:physical|fire|pulse|cryst|natural|spell)_corrupt_triggered$",
        @"^buff_common_(?:try_)?(?:physical|fire|pulse|cryst|natural|spell)_triggered(?:_wrapper)?$",
        @"^buff_common_try_(?:physical|fire|pulse|cryst|natural|spell)_(?:physical|fire|pulse|cryst|natural|spell)_triggered$",
        @"^buff_common_(?:physical|fire|pulse|cryst|natural|spell)_(?:physical|fire|pulse|cryst|natural|spell)_triggered_wrapper$",
    }.Select(pattern=>new Regex(pattern,RegexOptions.IgnoreCase|RegexOptions.CultureInvariant)).ToArray();
    internal static readonly string[] ChildFields = ["createdBuffIds","referencedBuffIds","binaryCreatedBuffIds","binaryReferencedBuffIds"];
    private static string Text(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static IEnumerable<string> Strings(EvidenceValue value) => CatalogValues.Iterable(CatalogValues.Or(value,new EvidenceArray([])))
        .Where(CatalogValues.Truth).Select(CatalogValues.Text);

    public static BuffDisplayClassification Load(ResourceFiles files,PacketBuffCatalog packets)
    {
        static Dictionary<string,EvidenceObject> Objects(EvidenceValue? value) => (value as EvidenceObject)?.Fields
            .Where(row=>row.Value is EvidenceObject).ToDictionary(row=>row.Key,row=>(EvidenceObject)row.Value,StringComparer.Ordinal) ?? [];
        return new(packets, Objects((files.ReadOnlyRelative("data/local_semantics/buff/details.json") as EvidenceObject)?.Get("entries")),
            Objects((files.ReadOnlyRelative("data/local_semantics/classifier_hints.json") as EvidenceObject)?.Get("buffHints")));
    }

    public static bool IsNoise(string key) => NoiseIds.Contains(key) || NoisePrefixes.Any(prefix=>key.StartsWith(prefix,StringComparison.Ordinal));
    public static bool IgnoresRate(string key) => RateIgnored.Any(pattern=>pattern.IsMatch(key));
    public static bool IgnoresRecordRate(EvidenceObject record) => Text(record.Get("event_key"))=="buff_equipsuit_atk_02_aruadetect";

    private EvidenceObject? Hint(EvidenceObject record) => record.Get("packet_mapping") as EvidenceObject
        ?? packets.Hint(CatalogValues.Text(CatalogValues.Or(record.Get("raw_event_key"),record.Get("event_key"),new EvidenceText("unknown_buff"))));

    public bool IsPacketWrapper(EvidenceObject record)
    {
        var hint=Hint(record);
        return hint is not null && Text(hint.Get("role")).ToLowerInvariant() is "wrapper" or "marker" or "utility"
            && !CatalogValues.Truth(hint.Get("effects")) && !CatalogValues.Truth(hint.Get("dynamic_effects"));
    }

    public static bool IsInternalTrigger(EvidenceObject record)
    {
        var key=CatalogValues.Text(CatalogValues.Or(record.Get("raw_event_key"),record.Get("event_key"),new EvidenceText("unknown_buff")));
        if(!SkillIdentityCatalog.IsDigitText(key)) return false;
        var keys=Strings(record.Get("bb_keys")).Select(key=>key.ToLowerInvariant()).ToHashSet(StringComparer.Ordinal);
        var blackboard=CatalogValues.Or(record.Get("bb_values"),new EvidenceObject(new Dictionary<string,EvidenceValue>()));
        if(blackboard is not EvidenceObject values) throw new InvalidDataException("Trigger blackboard must be an object");
        keys.UnionWith(values.Fields.Keys.Select(key=>key.ToLowerInvariant()));
        if(!new[] { "phy_dmg_up","final_phy_dmg_up","shatter_dmg","consumed_layer" }.All(keys.Contains)) return false;
        var owner=CatalogValues.Text(CatalogValues.Or(record.Get("owner_raw"),record.Get("target_character_key"),record.Get("target_enemy_key"),new EvidenceText("")));
        var source=CatalogValues.Text(CatalogValues.Or(record.Get("raw_source"),record.Get("source_character_key"),new EvidenceText("")));
        return owner.StartsWith("eny_",StringComparison.Ordinal) && source.StartsWith("chr_",StringComparison.Ordinal);
    }

    public bool IsEffectlessWrapper(EvidenceObject record)
    {
        var key=CatalogValues.Text(CatalogValues.Or(record.Get("event_key"),new EvidenceText("unknown_buff")));
        if(record.Get("packet_mapping") is EvidenceObject mapping && Text(mapping.Get("role")).ToLowerInvariant()=="effect") return false;
        var semantic=semantics.GetValueOrDefault(key);
        if(semantic is not null && Strings(semantic.Get("actionTypes")).Contains("VulnerableAction",StringComparer.Ordinal)) return false;
        if(IsInternalTrigger(record)) return true;
        if(CatalogValues.Truth(record.Get("attr_mods"))) return false;
        if(IsPacketWrapper(record)) return true;
        if(!classifier.TryGetValue(key,out var hint)) return false;
        var classification=Text(hint.Get("classification"));
        if(classification is not ("wrapper" or "marker_or_utility")) return false;
        if(CatalogValues.Truth(hint.Get("resolvedEffectHints")) || Integer(CatalogValues.Or(hint.Get("resolvedEffectCount"),new EvidenceInteger(0)))>0) return false;
        if(hint.Get("semanticFlags") is EvidenceObject flags && CatalogValues.Truth(flags.Get("hasDynamicBlackboard")))
        {
            return semantic is not null && Strings(semantic.Get("actionTypes")).Contains("OnSpellAbnormalStartFinish",StringComparer.Ordinal)
                && ChildFields.Any(field=>Strings(semantic.Get(field)).Any());
        }
        if(classification=="wrapper" && ChildFields.Any(field=>Strings(hint.Get(field)).Any())) return true;
        var children=Strings(hint.Get("createdBuffIds")).ToArray();
        return children.Length>0 && children.All(IsNoise);
    }

    private static BigInteger Integer(EvidenceValue value) => value switch
    {
        EvidenceInteger integer=>integer.Value,
        EvidenceBoolean boolean=>boolean.Value ? BigInteger.One : BigInteger.Zero,
        EvidenceReal real when double.IsFinite(real.Value)=>new BigInteger(real.Value),
        EvidenceReal real when double.IsNaN(real.Value)=>throw new FormatException("cannot convert float NaN to integer"),
        EvidenceReal=>throw new OverflowException("cannot convert float infinity to integer"),
        EvidenceText text=>TraceFields.OptionalInteger(text.Value) ?? throw new FormatException("Invalid resolved effect count"),
        _=>throw new InvalidCastException("Invalid resolved effect count"),
    };
}
