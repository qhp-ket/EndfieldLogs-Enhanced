using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

internal static class StaticLoadoutEvidence
{
    public static readonly EvidenceObject Empty=new(new Dictionary<string,EvidenceValue>());
    public static readonly EvidenceArray NoItems=new([]);
    public static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    public static EvidenceText Str(string value)=>new(value);
    public static EvidenceInteger Int(int value)=>new(value);
    public static EvidenceObject Obj(params (string Key,EvidenceValue Value)[] fields)=>BuffEvidence.Object(fields);
    public static EvidenceObject Object(EvidenceValue value)=>CatalogValues.Or(value,Empty) as EvidenceObject ?? throw new InvalidDataException("Static field must be an object");
    public static IEnumerable<EvidenceValue> Items(EvidenceValue value)=>CatalogValues.Iterable(CatalogValues.Or(value,NoItems));
    public static EvidenceValue Required(EvidenceObject row,string key)=>row.Fields.GetValueOrDefault(key) ?? throw new KeyNotFoundException(key);
    public static bool Same(EvidenceValue value,int number)=>EvidenceJson.PythonEquals(value,Int(number));
    public static bool Hash(EvidenceValue value)=>value is EvidenceText text && Regex.IsMatch(text.Value,@"\A[0-9a-f]{64}\z");
    public static Dictionary<string,EvidenceValue> Fields(EvidenceObject row)=>(Dictionary<string,EvidenceValue>)row.Fields;
    public static void Block(EvidenceObject row,EvidenceObject reason)
    {
        var existing=row.Get("rdps_unresolved_static_multiplier_sources") as EvidenceArray ?? NoItems;
        Fields(row)["rdps_unresolved_static_multiplier_sources"]=new EvidenceArray([..existing.Items,reason]);
    }
    public static readonly IReadOnlyDictionary<BigInteger,(string Zone,string Element)> AttributeEffects=new Dictionary<BigInteger,(string,string)>
    {
        [2]=("atk","all"),[9]=("crit","all"),[10]=("crit","all"),[17]=("dmg_inc","all"),[28]=("dmg_inc","all"),[32]=("dmg_inc","all"),[33]=("dmg_inc","all"),
        [50]=("dmg_inc","physical"),[51]=("dmg_inc","fire"),[52]=("dmg_inc","pulse"),[53]=("dmg_inc","cryst"),[54]=("dmg_inc","natural"),[55]=("dmg_inc","ether"),
        [65]=("amp","fire"),[66]=("amp","pulse"),[67]=("amp","cryst"),[68]=("amp","natural"),
        [70]=("fragile","physical"),[71]=("fragile","fire"),[72]=("fragile","pulse"),[73]=("fragile","cryst"),[74]=("fragile","natural"),[75]=("fragile","ether"),
    };
    public static readonly IReadOnlyDictionary<string,string> ZoneLabels=new Dictionary<string,string>(StringComparer.Ordinal)
    { ["atk"]="攻击",["dmg_inc"]="增伤",["fragile"]="脆弱",["vuln_taken"]="易伤",["amp"]="增幅",["res"]="减抗",["combo"]="连击",["crit"]="暴击",["arts_strength"]="源石技艺强度",["prod_dmg_inc"]="独立增伤",["prod_vuln_taken"]="独立承伤易伤" };
}
