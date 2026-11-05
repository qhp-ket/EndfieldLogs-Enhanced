using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

namespace EndfieldLogs.Core.Realtime;

public sealed partial class LiveAllocationCache
{
    private sealed class DependencySnapshot(EvidenceObject[] rows)
    {
        internal EvidenceObject[] Rows = rows;
        internal List<EffectSignature>? Keys;
        internal Dictionary<EffectSignature, int>? Positions;
        internal bool Unique => Positions!.Count == Rows.Length;
    }

    private sealed record DependencyChange(DependencySnapshot Before, EvidenceObject[] Rows, EvidenceValue Cutoff,
        IReadOnlyList<EffectSignature>? Added = null, DependencySnapshot? Replacement = null)
    {
        internal DependencySnapshot Commit()
        {
            if (Replacement is not null) return Replacement;
            var keys = Before.Keys!;
            var positions = Before.Positions!;
            for (var index = keys.Count - 1; index >= Rows.Length; index--) positions.Remove(keys[index]);
            if (keys.Count > Rows.Length) keys.RemoveRange(Rows.Length, keys.Count - Rows.Length);
            foreach (var key in Added ?? []) { positions.Add(key, keys.Count); keys.Add(key); }
            Before.Rows = Rows;
            return Before;
        }
    }

    internal long DependencyIdentitiesBuilt { get; private set; }
    internal long DependencyIndexRebuilds { get; private set; }

    private EffectSignature DependencyIdentity(EvidenceObject row)
    {
        DependencyIdentitiesBuilt++;
        return Identity(row);
    }

    private void IndexDependencies(DependencySnapshot snapshot)
    {
        if (snapshot.Keys is not null) return;
        List<EffectSignature> keys = [];
        Dictionary<EffectSignature, int> positions = [];
        foreach (var row in snapshot.Rows)
        {
            var key = DependencyIdentity(row);
            positions[key] = keys.Count;
            keys.Add(key);
        }
        snapshot.Keys = keys;
        snapshot.Positions = positions;
        DependencyIndexRebuilds++;
    }

    private DependencyChange CompareDependencies(DependencySnapshot old, EvidenceObject[] rows)
    {
        // Index only when the previous report has hits, matching the original deferred identity validation.
        IndexDependencies(old);
        var shared = Math.Min(old.Rows.Length, rows.Length);
        var unchanged = old.Rows.Length == rows.Length;
        var stable = old.Unique;
        var cutoff = PositiveInfinity;
        for (var index = 0; index < shared; index++)
        {
            if (ReferenceEquals(old.Rows[index], rows[index])) continue;
            unchanged = false;
            if (!old.Keys![index].Equals(DependencyIdentity(rows[index]))) { stable = false; break; }
            cutoff = Min(cutoff, ChangeAt(old.Rows[index], rows[index], Stamp(rows[index])));
        }
        if (unchanged) return new(old, rows, PositiveInfinity);
        if (stable)
        {
            List<EffectSignature> added = [];
            HashSet<EffectSignature> addedKeys = [];
            for (var index = shared; index < rows.Length; index++)
            {
                var key = DependencyIdentity(rows[index]);
                if (old.Positions!.ContainsKey(key) || !addedKeys.Add(key)) { stable = false; break; }
                added.Add(key);
                cutoff = Min(cutoff, Stamp(rows[index]));
            }
            if (stable)
            {
                for (var index = shared; index < old.Rows.Length; index++) cutoff = Min(cutoff, Stamp(old.Rows[index]));
                return new(old, rows, cutoff, added);
            }
        }

        // Changed identities/order and duplicate identities retain the complete original comparison.
        DependencySnapshot next = new(rows);
        IndexDependencies(next);
        cutoff = PositiveInfinity;
        var before = old.Positions!;
        var after = next.Positions!;
        var beforeKeys = old.Keys!.Distinct().ToArray();
        var afterKeys = next.Keys!.Distinct().ToArray();
        if (!beforeKeys.Where(after.ContainsKey).SequenceEqual(afterKeys.Where(before.ContainsKey))) cutoff = NegativeInfinity;
        if (!old.Unique || !next.Unique)
        {
            if (!EvidenceJson.PythonEquals(new EvidenceArray(old.Rows), new EvidenceArray(rows))) cutoff = NegativeInfinity;
        }
        else
            foreach (var key in beforeKeys.Concat(afterKeys).Distinct())
            {
                var a = before.TryGetValue(key, out var first) ? old.Rows[first] : null;
                var b = after.TryGetValue(key, out var last) ? rows[last] : null;
                cutoff = Min(cutoff, ChangeAt(a ?? (EvidenceValue)EvidenceNull.Value, b ?? (EvidenceValue)EvidenceNull.Value,
                    Stamp(b ?? a!)));
            }
        return new(old, rows, cutoff, Replacement: next);
    }
}
