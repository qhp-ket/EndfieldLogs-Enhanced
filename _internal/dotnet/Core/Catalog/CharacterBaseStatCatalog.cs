using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Catalog;

/// <summary>Exact official character levels; conflicting rows invalidate a level permanently.</summary>
public sealed class CharacterBaseStatCatalog
{
    private readonly ResourceFiles files;
    private readonly Lazy<IReadOnlyDictionary<string,IReadOnlyDictionary<BigInteger,EvidenceObject>>> entries;
    public CharacterBaseStatCatalog(ResourceFiles files)
    {
        this.files=files;
        entries=new(Load);
    }
    public IReadOnlyDictionary<string,IReadOnlyDictionary<BigInteger,EvidenceObject>> Entries=>entries.Value;

    public EvidenceObject? Get(string? character,BigInteger? level)
    {
        if(string.IsNullOrEmpty(character) || level is not BigInteger exact || exact<=0
            || !Entries.TryGetValue(character,out var levels) || !levels.TryGetValue(exact,out var row)) return null;
        var fields=new Dictionary<string,EvidenceValue>(((EvidenceObject)BuffEvidence.Clone(row)).Fields,StringComparer.Ordinal)
        { ["level_source"]=new EvidenceText("loadout") };
        return new(fields);
    }

    private static double Float(EvidenceValue value)=>value switch
    {
        EvidenceBoolean flag=>flag.Value ? 1 : 0,
        EvidenceInteger integer when double.IsFinite((double)integer.Value)=>(double)integer.Value,
        EvidenceInteger=>throw new OverflowException("Character attribute exceeds floating point range"),
        EvidenceReal real=>real.Value,
        EvidenceText text when TraceFields.TryFloat(text.Value,out var number)=>double.IsNaN(number)
            ? BitConverter.UInt64BitsToDouble(text.Value.Trim().StartsWith('-') ? 0xfff8000000000000UL : 0x7ff8000000000000UL) : number,
        EvidenceText=>throw new FormatException("Invalid character attribute"),
        _=>throw new InvalidCastException("Invalid character attribute"),
    };
    private static BigInteger? OptionalInteger(EvidenceValue value)=>value switch
    {
        EvidenceInteger integer=>integer.Value,
        EvidenceReal real=>TraceFields.OptionalInteger(real.Value),
        EvidenceText text=>TraceFields.OptionalInteger(text.Value),
        _=>null,
    };

    private IReadOnlyDictionary<string,IReadOnlyDictionary<BigInteger,EvidenceObject>> Load()
    {
        Dictionary<string,IReadOnlyDictionary<BigInteger,EvidenceObject>> result=new(StringComparer.Ordinal);
        var directory=files.PathFor("data/local_tables/character/items");
        if(!Directory.Exists(directory)) return result;
        foreach(var path in Directory.EnumerateFileSystemEntries(directory,"chr_*.json"))
        {
            var payload=files.Read(path);
            if(payload is null) continue;
            if(payload is not EvidenceObject document) throw new InvalidDataException("Character document must be an object");
            var raw=document.Get("raw") as EvidenceObject;
            if(raw?.Get("attributes") is not EvidenceArray attributes) continue;
            Dictionary<BigInteger,EvidenceObject> levels=[];
            HashSet<BigInteger> ambiguous=[];
            foreach(var row in attributes.Items.OfType<EvidenceObject>())
            {
                if((row.Get("Attribute") as EvidenceObject)?.Get("attrs") is not EvidenceArray attrs) continue;
                Dictionary<BigInteger,EvidenceReal> values=[];
                BigInteger? level=null;
                foreach(var item in attrs.Items.OfType<EvidenceObject>())
                {
                    BigInteger type;double value;
                    try { type=LoadoutMerging.Integer(item.Get("attrType"));value=Float(item.Get("attrValue")); }
                    catch(Exception error) when(error is InvalidCastException or FormatException) { continue; }
                    // float(existing_float) retains identity, including JSON's shared NaN literal.
                    values[type]=item.Get("attrValue") as EvidenceReal ?? new EvidenceReal(value);
                    if(type.IsZero && double.IsFinite(value) && Math.Truncate(value)==value) level=new BigInteger(value);
                }
                if(level is not BigInteger exact || ambiguous.Contains(exact)) continue;
                EvidenceValue Value(int type)=>values.TryGetValue(type,out var value) ? value : EvidenceNull.Value;
                var current=BuffEvidence.Object(("level",new EvidenceInteger(exact)),("main_attr_type",raw.Get("mainAttrType")),
                    ("sub_attr_type",raw.Get("subAttrType")),("break_stage",BuffEvidence.Number(OptionalInteger(row.Get("breakStage")))),
                    ("hp",Value(1)),("atk",Value(2)),("def",Value(3)),("attr_39",Value(39)),("attr_40",Value(40)),("attr_41",Value(41)),("attr_42",Value(42)));
                if(levels.TryGetValue(exact,out var previous) && !EvidenceJson.PythonEquals(previous,current))
                { levels.Remove(exact);ambiguous.Add(exact); }
                else levels[exact]=current;
            }
            if(levels.Count>0) result[Path.GetFileNameWithoutExtension(path)]=levels;
        }
        return result;
    }
}
