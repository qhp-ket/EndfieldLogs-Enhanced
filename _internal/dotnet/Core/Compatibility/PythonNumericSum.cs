using System.Numerics;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Exact leading integer accumulation followed by Python's compensated binary64 sum.</summary>
public static class PythonNumericSum
{
    private static double Number(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => PythonIntegerDivision.Divide(integer.Value, BigInteger.One),
        EvidenceBoolean flag => flag.Value ? 1 : 0,
        EvidenceReal real => real.Value,
        _ => throw new InvalidCastException("Numeric sum requires numeric evidence"),
    };
    internal struct Accumulator
    {
        private BigInteger integer;
        private PythonFloatSum.Accumulator sum;
        private bool floating;

        internal void Add(EvidenceValue value)
        {
            if (floating) sum.Add(Number(value));
            else if (value is EvidenceInteger exact) integer += exact.Value;
            else if (value is EvidenceBoolean flag) integer += flag.Value ? BigInteger.One : BigInteger.Zero;
            else
            {
                if (value is not EvidenceReal) throw new InvalidCastException("Numeric sum requires numeric evidence");
                sum.Add(Number(new EvidenceInteger(integer)));
                sum.Add(Number(value));
                floating = true;
            }
        }
        internal readonly EvidenceValue Value => floating ? new EvidenceReal(sum.Value) : new EvidenceInteger(integer);
    }

    public static EvidenceValue Sum(IEnumerable<EvidenceValue> source)
    {
        Accumulator sum = new();
        foreach (var value in source) sum.Add(value);
        return sum.Value;
    }
}
