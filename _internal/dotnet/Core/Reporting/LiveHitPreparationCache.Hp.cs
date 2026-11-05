using System.Numerics;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

internal sealed partial class LiveHitPreparationCache
{
    private sealed class TargetHp
    {
        internal BigInteger? Previous;
        internal BigInteger Maximum;
        internal BigInteger? AppliedMaximum;
        internal readonly List<int> Indices = [];
    }
    private sealed class HpEntry(ReportHitInput input, string key, BigInteger? previous, BigInteger maximum,
        bool observed, BigInteger? before, bool hasPrevious)
    {
        internal readonly ReportHitInput Input = input;
        internal readonly string Key = key;
        internal readonly BigInteger? Previous = previous, Before = before;
        internal readonly BigInteger Maximum = maximum;
        internal readonly bool Observed = observed, HasPrevious = hasPrevious;
        internal BigInteger? AppliedMaximum;
        internal ReportHitInput? Output;
    }
    private readonly List<HpEntry> hp = [];
    private readonly Dictionary<string, TargetHp> targetHp = new(StringComparer.Ordinal);
    internal long ObservedHpHits { get; private set; }
    internal long ProjectedHpHits { get; private set; }
    internal long RetractedHpHits { get; private set; }

    private static BigInteger? HpInteger(EvidenceValue value) => value switch
    {
        EvidenceInteger integer => integer.Value,
        EvidenceReal real => TraceFields.OptionalInteger(real.Value),
        EvidenceText text => TraceFields.OptionalInteger(text.Value),
        _ => null,
    };
    private static string HpText(EvidenceValue value) => CatalogValues.Text(CatalogValues.Or(value, new EvidenceText("")));

    internal IReadOnlyList<ReportHitInput> Annotate(IReadOnlyList<ReportHitInput> hits)
    {
        var shared = 0;
        while (shared < Math.Min(hp.Count, hits.Count) && ReferenceEquals(hp[shared].Input, hits[shared])) shared++;
        HashSet<string> changed = new(StringComparer.Ordinal);
        // Undo only the invalidated suffix. Each target keeps the predecessor state needed for exact retraction.
        for (var index = hp.Count - 1; index >= shared; index--)
        {
            var entry = hp[index];
            var target = targetHp[entry.Key];
            target.Indices.RemoveAt(target.Indices.Count - 1);
            if (entry.Observed) { target.Previous = entry.Previous; target.Maximum = entry.Maximum; }
            changed.Add(entry.Key);
            RetractedHpHits++;
        }
        hp.RemoveRange(shared, hp.Count - shared);
        for (var index = shared; index < hits.Count; index++)
        {
            var input = hits[index];
            if (!FrozenEvidence.IsFrozenRoot(input.Evidence)) throw new InvalidOperationException("Expected a prepared immutable live hit");
            var row = input.Evidence;
            var key = EnemyHpEvidence.StateKey(row.Get("target_enemy_key"), row.Get("target_actor_id"));
            if (!targetHp.TryGetValue(key, out var target)) targetHp[key] = target = new();
            var after = HpInteger(row.Get("enemy_hp_after"));
            var observed = HpText(row.Get("target_enemy_key")).Length > 0 && after is not null;
            var hasPrevious = observed && target.Previous is { } prior && prior >= after!.Value;
            BigInteger? before = observed ? hasPrevious ? target.Previous : after!.Value + BigInteger.Max(0, HpInteger(row.Get("hit_value")) ?? 0) : null;
            hp.Add(new(input, key, target.Previous, target.Maximum, observed, before, hasPrevious));
            target.Indices.Add(index);
            if (observed)
            {
                target.Maximum = BigInteger.Max(target.Maximum, BigInteger.Max(before!.Value, after!.Value));
                target.Previous = after;
            }
            changed.Add(key);
            ObservedHpHits++;
        }
        foreach (var key in changed)
        {
            var target = targetHp[key];
            BigInteger? maximum = target.Maximum > 0 ? target.Maximum : null;
            var start = maximum != target.AppliedMaximum ? 0 : target.Indices.BinarySearch(shared);
            if (start < 0) start = ~start;
            for (var position = start; position < target.Indices.Count; position++)
            {
                var index = target.Indices[position];
                var entry = hp[index];
                if (entry.Output is not null && entry.AppliedMaximum == maximum) continue;
                Dictionary<string, EvidenceValue> fields = new(StringComparer.Ordinal);
                if (entry.Observed)
                {
                    fields["enemy_hp_before"] = new EvidenceInteger(entry.Before!.Value);
                    fields["enemy_hp_before_source"] = new EvidenceText(entry.HasPrevious ? "previous_enemy_hp" : "enemy_hp_after_plus_hit");
                }
                if (maximum is { } value)
                {
                    fields["target_enemy_observed_max_hp"] = new EvidenceInteger(value);
                    var before = entry.Before ?? HpInteger(entry.Input.Evidence.Get("enemy_hp_before"));
                    if (before is { } hpBefore && HpInteger(entry.Input.Evidence.Get("target_enemy_max_hp")) is { Sign: > 0 } explicitMax)
                        fields["target_enemy_hp_ratio_before"] = new EvidenceReal(PythonIntegerDivision.Divide(hpBefore, explicitMax));
                }
                entry.Output = fields.Count == 0 ? entry.Input : entry.Input with
                {
                    Evidence = FrozenEvidence.MergeRoot(entry.Input.Evidence, (EvidenceObject)snapshots.Capture(new EvidenceObject(fields))),
                };
                entry.AppliedMaximum = maximum;
                ProjectedHpHits++;
            }
            target.AppliedMaximum = maximum;
            if (target.Indices.Count == 0) targetHp.Remove(key);
        }
        return hp.Select(entry => entry.Output!).ToArray();
    }
}
