using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Effects;

/// <summary>Exact skill category evidence; a template proves positive bits but cannot prove runtime absence.</summary>
public static class DamageAttributeApplicability
{
    private static readonly IReadOnlyDictionary<int,int> Masks=new Dictionary<int,int>
    { [17]=0x20484,[28]=0x200,[32]=0x100,[33]=0x2000 };

    public static bool? Evaluate(EvidenceValue attribute,EvidenceValue runtimeMask,
        EvidenceValue staticMask,EvidenceValue staticMaskSource)
    {
        if(attribute is EvidenceObject or EvidenceArray) throw new InvalidCastException("Unhashable attribute type");
        var mask=Masks.FirstOrDefault(pair=>EvidenceJson.PythonEquals(attribute,new EvidenceInteger(pair.Key))).Value;
        if(mask==0) return true;
        if(runtimeMask is not EvidenceNull)
            return ValidMask(runtimeMask) is BigInteger observed ? (observed & mask)!=0 : null;
        if(staticMaskSource is EvidenceText { Value:"current_typed_skill_or_buff_exact_unit_generation_only" }
            && ValidMask(staticMask) is BigInteger declared && (declared & mask)!=0) return true;
        return null;
    }

    private static BigInteger? ValidMask(EvidenceValue value)=>value is EvidenceInteger integer
        && integer.Value>=0 && integer.Value<(BigInteger.One<<64) ? integer.Value : null;
}
