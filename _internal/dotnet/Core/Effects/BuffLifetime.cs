using System.Numerics;

namespace EndfieldLogs.Core.Effects;

/// <summary>Observed ends include pauses; nominal duration only bounds an otherwise unended instance.</summary>
public static class BuffLifetime
{
    public static BigInteger EndAt(BigInteger start,BigInteger? observedEnd,BigInteger? nominalDuration,
        BigInteger battleEnd,bool infinite,BigInteger? snapshotEnd=null)
    {
        var remaining=BigInteger.Max(battleEnd-start,BigInteger.Zero);
        var duration=observedEnd is BigInteger end && end>=start ? BigInteger.Min(remaining,end-start)
            : nominalDuration is BigInteger raw && raw>=0 ? BigInteger.Min(remaining,raw)
            : infinite ? remaining : BigInteger.Zero;
        var result=start+duration;
        return snapshotEnd is BigInteger boundary ? BigInteger.Min(result,boundary) : result;
    }
}
