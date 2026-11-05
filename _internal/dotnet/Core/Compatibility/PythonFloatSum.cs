namespace EndfieldLogs.Core.Compatibility;

/// <summary>The compensated binary64 sum used by the fixed Python 3.14 reference.</summary>
public static class PythonFloatSum
{
    // Value copies retain the compensation needed to resume exactly after a stable prefix.
    internal struct Accumulator
    {
        private double high, low;
        internal void Add(double value)
        {
            var total = high + value;
            low += Math.Abs(high) >= Math.Abs(value) ? (high - total) + value : (value - total) + high;
            high = total;
        }
        internal readonly double Value => low != 0 && double.IsFinite(low) ? high + low : high;
    }

    public static double Sum(IEnumerable<double> values)
    {
        Accumulator sum = new();
        foreach (var value in values) sum.Add(value);
        return sum.Value;
    }
}
