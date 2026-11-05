using System.Numerics;
using EndfieldLogs.Core.Allocation;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Realtime;

/// <summary>One shared immutable-hit frontier for finalization, contributions and hit-local readiness.</summary>
internal sealed class LiveHitAccountingCache
{
    private sealed record Entry(EvidenceObject Source, EvidenceObject Contributions, int BlockerCount,
        bool IntegerTimes, BigInteger Latest, int FirstLatest, int FirstUnresolved);
    private readonly List<Entry> rows = [];
    private struct BasisCheckpoint
    {
        internal DamageBasis.Accumulator Basis;
        internal PythonNumericSum.Accumulator Total;
    }
    private readonly List<BasisCheckpoint> basis = [];
    internal int UnchangedPrefix { get; private set; }
    internal long PreparedHits { get; private set; }
    internal long BasisPreparedHits { get; private set; }
    internal IEnumerable<EvidenceObject> Contributions => rows.Select(row => row.Contributions);
    internal int BlockerCount => rows.Count == 0 ? 0 : rows[^1].BlockerCount;
    // Diagnostic/full-evidence callers can still request rows; summaries retain only counts.
    internal IEnumerable<EvidenceObject> Blockers => rows.SelectMany(row => AllocationPreflight.HitBlockers(row.Source));

    internal void Clear() { rows.Clear(); basis.Clear(); UnchangedPrefix = 0; }

    internal void Update(IReadOnlyList<ReportHitInput> hits)
    {
        var first = 0;
        while (first < Math.Min(rows.Count, hits.Count) && ReferenceEquals(rows[first].Source, hits[first].Evidence)) first++;
        UnchangedPrefix = first;
        rows.RemoveRange(first, rows.Count - first);
        if (basis.Count > first) basis.RemoveRange(first, basis.Count - first);
        for (var index = first; index < hits.Count; index++)
        {
            var hit = hits[index].Evidence;
            if (!FrozenEvidence.IsFrozenRoot(hit)) throw new InvalidOperationException("Live hit accounting requires an immutable root");
            var previous = index == 0 ? null : rows[index - 1];
            var timestamp = CatalogValues.Or(hit.Get("ts_ms"), new EvidenceInteger(0));
            var integer = timestamp is EvidenceInteger && (previous?.IntegerTimes ?? true);
            var latest = previous?.Latest ?? BigInteger.Zero;
            var firstLatest = previous?.FirstLatest ?? 0;
            if (integer && (index == 0 || ((EvidenceInteger)timestamp).Value > latest))
            {
                latest = ((EvidenceInteger)timestamp).Value; firstLatest = index;
            }
            var unresolved = previous?.FirstUnresolved ?? -1;
            if (unresolved < 0 && hit.Fields.Any(pair => pair.Key.StartsWith("rdps_unresolved_", StringComparison.Ordinal)
                && pair.Key != "rdps_unresolved_static_multiplier_sources" && CatalogValues.Truth(pair.Value))) unresolved = index;
            var contributions = hit.Get("rdps_contributions") as EvidenceObject
                ?? (EvidenceObject)FrozenEvidence.Capture(new EvidenceObject(new Dictionary<string, EvidenceValue>()));
            var blockers = (previous?.BlockerCount ?? 0) + AllocationPreflight.HitBlockerCount(hit);
            rows.Add(new(hit, contributions, blockers, integer, latest, firstLatest, unresolved));
            PreparedHits++;
        }
    }

    // The immutable frontier already identifies the changed suffix. Keep sum compensation,
    // counts and conservation verdicts there instead of reading every old hit again.
    internal EvidenceObject BuildBasis(IReadOnlyDictionary<string, double> totals)
    {
        while (basis.Count < rows.Count)
        {
            var next = basis.Count == 0 ? new BasisCheckpoint() : basis[^1];
            var hit = rows[basis.Count].Source;
            next.Total.Add(hit.Fields["hit_value"]);
            next.Basis.Add(hit);
            basis.Add(next);
            BasisPreparedHits++;
        }
        var last = basis.Count == 0 ? new BasisCheckpoint() : basis[^1];
        return last.Basis.Build(totals.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value), StringComparer.Ordinal),
            EffectIdentity.Integer(last.Total.Value));
    }

    // Noninteger and nonfinite public timestamp semantics retain the original comparison path.
    internal int? FinalizedCount => rows.Count == 0 ? 0 : rows[^1].IntegerTimes
        ? Math.Min(rows[^1].FirstLatest, rows[^1].FirstUnresolved < 0 ? rows.Count : rows[^1].FirstUnresolved) : null;
}
