using System.Numerics;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Decimal rounding of the exact binary64 input, with ties to even and a single final conversion.</summary>
public static class PythonDecimalRounding
{
    public static double Round(double value, int places)
    {
        if (!double.IsFinite(value) || value == 0 || places > 323) return value;
        var negative = BitConverter.DoubleToInt64Bits(value) < 0;
        if (places < -308) return negative ? -0.0 : 0.0;
        var bits = BitConverter.DoubleToUInt64Bits(value);
        var exponent = (int)((bits >> 52) & 0x7ff);
        BigInteger numerator = bits & 0xfffffffffffffUL;
        if (exponent != 0) numerator += BigInteger.One << 52;
        var shift = exponent == 0 ? -1074 : exponent - 1075;
        var denominator = BigInteger.One;
        if (shift >= 0) numerator <<= shift;
        else denominator <<= -shift;
        var scale = BigInteger.Pow(10, Math.Abs(places));
        if (places >= 0) numerator *= scale;
        else denominator *= scale;
        var rounded = BigInteger.DivRem(numerator, denominator, out var remainder);
        var comparison = (remainder << 1).CompareTo(denominator);
        if (comparison > 0 || comparison == 0 && !rounded.IsEven) rounded++;
        var result = places >= 0 ? PythonIntegerDivision.Divide(rounded, scale)
            : PythonIntegerDivision.Divide(rounded * scale, BigInteger.One);
        return negative ? -result : result;
    }
}
