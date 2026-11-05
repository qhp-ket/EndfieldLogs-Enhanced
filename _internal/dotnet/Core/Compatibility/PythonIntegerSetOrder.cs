using System.Numerics;

namespace EndfieldLogs.Core.Compatibility;

/// <summary>Insertion-only integer set ordering at the fixed CPython 3.14 x64 file boundary.</summary>
public static class PythonIntegerSetOrder
{
    public static IReadOnlyList<BigInteger> Distinct(IEnumerable<BigInteger> values)
    {
        BigInteger?[] table = new BigInteger?[8];
        var used = 0;
        foreach (var value in values)
        {
            if (!Insert(table, value)) continue;
            used++;
            if (used*5 < (table.Length-1)*3) continue;
            var minimum = used*(used > 50000 ? 2 : 4);
            var length = 8;
            while (length <= minimum) length = checked(length*2);
            BigInteger?[] next = new BigInteger?[length];
            foreach (var item in table) if (item is BigInteger number) Insert(next, number);
            table = next;
        }
        return table.OfType<BigInteger>().ToArray();
    }

    private static bool Insert(BigInteger?[] table, BigInteger value)
    {
        var hash = (long)(BigInteger.Abs(value) % ((BigInteger.One << 61)-1));
        if (value.Sign < 0) hash = -hash;
        if (hash == -1) hash = -2;
        var perturb = unchecked((ulong)hash);
        var mask = table.Length-1;
        var index = (int)(perturb & (uint)mask);
        while (true)
        {
            var last = index+9 <= mask ? index+9 : index;
            for (var slot = index; slot <= last; slot++)
            {
                if (table[slot] is not BigInteger existing) { table[slot] = value; return true; }
                if (existing == value) return false;
            }
            perturb >>= 5;
            index = (int)((unchecked((ulong)index*5+1)+perturb) & (uint)mask);
        }
    }
}
