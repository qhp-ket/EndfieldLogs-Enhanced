using System.Runtime.CompilerServices;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;

namespace EndfieldLogs.Core.Reporting;

/// <summary>One live calculation's immutable static preparation; source revisions have distinct input identities.</summary>
internal sealed partial class LiveHitPreparationCache
{
    private object? owner;
    private EvidenceObject? loadouts;
    private readonly FrozenEvidence.Context snapshots = new();
    private ConditionalWeakTable<ReportHitInput, ReportHitInput> prepared = new();
    internal long PreparedHits { get; private set; }
    internal long ReusedHits { get; private set; }
    internal long ContextChanges { get; private set; }

    internal void Begin(object builder, IReadOnlyDictionary<string, EvidenceObject> selected)
    {
        EvidenceObject next = new(selected.ToDictionary(pair => pair.Key, pair => (EvidenceValue)pair.Value, StringComparer.Ordinal));
        if (ReferenceEquals(owner, builder) && loadouts is not null && EffectRecordCache.Same(loadouts, next)) return;
        owner = builder;
        snapshots.Clear();
        loadouts = (EvidenceObject)FrozenEvidence.Capture(next);
        prepared = new();
        ContextChanges++;
    }

    internal EvidenceObject? Loadout(string character) => loadouts?.Get(character) as EvidenceObject;

    internal ReportHitInput Prepare(ReportHitInput input, Func<ReportHitInput> calculate)
    {
        var immutable = FrozenEvidence.IsFrozenRoot(input.Evidence) && FrozenEvidence.IsFrozenNumbers(input.Baseline)
            && FrozenEvidence.IsFrozenNumbers(input.BasicAttributes) && FrozenEvidence.IsFrozenNumbers(input.Attributes);
        if (immutable && prepared.TryGetValue(input, out var saved)) { ReusedHits++; return saved; }
        var result = calculate();
        result = result with
        {
            Evidence = (EvidenceObject)snapshots.Capture(result.Evidence),
            Baseline = FrozenEvidence.CaptureNumbers(result.Baseline),
            BasicAttributes = FrozenEvidence.CaptureNumbers(result.BasicAttributes), Attributes = FrozenEvidence.CaptureNumbers(result.Attributes),
        };
        if (immutable) prepared.Add(input, result);
        PreparedHits++;
        return result;
    }
}
