using System.Numerics;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Observed target HP is a lower-bound observation; only explicit max HP establishes a ratio.</summary>
public static class EnemyHpEvidence
{
    private static string Text(EvidenceValue value)=>CatalogValues.Text(CatalogValues.Or(value,new EvidenceText("")));
    private static BigInteger? Integer(EvidenceValue value)=>value switch
    {
        EvidenceInteger integer=>integer.Value,EvidenceReal real=>TraceFields.OptionalInteger(real.Value),
        EvidenceText text=>TraceFields.OptionalInteger(text.Value),_=>null,
    };
    public static string StateKey(EvidenceValue target,EvidenceValue actor)
    {
        var text=Text(actor);
        return Regex.IsMatch(text,@"\A[1-9]\d*\z") ? "actor:"+text : "template:"+Text(target);
    }

    public static IReadOnlyList<EvidenceObject> Annotate(IReadOnlyList<EvidenceObject> hits)
    {
        var owned=hits.Select(hit=>(EvidenceObject)BuffEvidence.Clone(hit)).ToArray();
        AnnotateOwned(owned);
        return owned;
    }

    internal static void AnnotateOwned(IReadOnlyList<EvidenceObject> hits)
    {
        var owned=hits.Select(hit=>(Dictionary<string,EvidenceValue>)hit.Fields).ToArray();
        Dictionary<string,BigInteger> previous=new(StringComparer.Ordinal),maximum=new(StringComparer.Ordinal);
        foreach(var fields in owned)
        {
            var hit=new EvidenceObject(fields);
            if(Text(hit.Get("target_enemy_key")).Length==0 || Integer(hit.Get("enemy_hp_after")) is not BigInteger after) continue;
            var key=StateKey(hit.Get("target_enemy_key"),hit.Get("target_actor_id"));
            var damage=BigInteger.Max(0,Integer(hit.Get("hit_value")) ?? BigInteger.Zero);
            var hasPrevious=previous.TryGetValue(key,out var before) && before>=after;
            if(!hasPrevious) before=after+damage;
            fields["enemy_hp_before"]=new EvidenceInteger(before);
            fields["enemy_hp_before_source"]=new EvidenceText(hasPrevious ? "previous_enemy_hp" : "enemy_hp_after_plus_hit");
            maximum[key]=BigInteger.Max(maximum.GetValueOrDefault(key),BigInteger.Max(before,after));
            previous[key]=after;
        }
        foreach(var fields in owned)
        {
            var hit=new EvidenceObject(fields);
            var key=StateKey(hit.Get("target_enemy_key"),hit.Get("target_actor_id"));
            if(!maximum.TryGetValue(key,out var observed) || observed<=0) continue;
            fields["target_enemy_observed_max_hp"]=new EvidenceInteger(observed);
            if(Integer(hit.Get("enemy_hp_before")) is BigInteger before && Integer(hit.Get("target_enemy_max_hp")) is BigInteger explicitMax && explicitMax>0)
                fields["target_enemy_hp_ratio_before"]=new EvidenceReal(PythonIntegerDivision.Divide(before,explicitMax));
        }
    }
}
