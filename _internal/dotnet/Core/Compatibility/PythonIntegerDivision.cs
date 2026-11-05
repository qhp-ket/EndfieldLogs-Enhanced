using System.Numerics;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Round an exact integer ratio once, including large operands and subnormal results.</summary>
public static class PythonIntegerDivision
{
    public static double Divide(BigInteger numerator,BigInteger denominator)
    {
        if(denominator.IsZero) throw new DivideByZeroException();
        var negative=(numerator.Sign<0)!=(denominator.Sign<0);
        numerator=BigInteger.Abs(numerator);denominator=BigInteger.Abs(denominator);
        if(numerator.IsZero) return negative ? -0.0 : 0.0;
        var exponent=numerator.GetBitLength()-denominator.GetBitLength();
        if(exponent>1024) throw new OverflowException("Integer ratio exceeds double range");
        if(exponent < -1075) return negative ? -0.0 : 0.0;
        if(exponent>=0 ? numerator < denominator<<(int)exponent : numerator<<checked((int)-exponent) < denominator) exponent--;
        if(exponent>1023) throw new OverflowException("Integer ratio exceeds double range");
        var scale=exponent < -1022 ? 1074 : 52-(int)exponent;
        var top=scale>=0 ? numerator<<scale : numerator;
        var bottom=scale<0 ? denominator<<-scale : denominator;
        var rounded=BigInteger.DivRem(top,bottom,out var remainder);
        var comparison=(remainder<<1).CompareTo(bottom);
        if(comparison>0 || comparison==0 && !rounded.IsEven) rounded++;
        var result=Math.ScaleB((double)rounded,-scale);
        if(!double.IsFinite(result)) throw new OverflowException("Integer ratio exceeds double range");
        return negative ? -result : result;
    }
}
