using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Effects;

internal sealed record EffectRecordAnalysis(EvidenceObject Record, IReadOnlyList<string> Labels,
    IReadOnlyList<EvidenceObject> StaticEffects, IReadOnlyList<EvidenceObject> DynamicEffects)
{
    internal EffectWindowMemo? WindowMemo { get; init; }
    internal EffectRecordReadiness? Readiness { get; init; }
}

internal sealed record EffectRecordReadiness(int CheckedExternal = 0, int Accepted = 0, int NonDamage = 0,
    EvidenceObject? Blocker = null, bool TracksWindowInclusion = false, EvidenceValue? IncludedReason = null);

internal sealed class EffectWindowMemo
{
    internal BigInteger End;
    internal EvidenceValue EndLine = EvidenceNull.Value;
    internal long StrengthBits;
    internal EvidenceObject? Window;
    internal bool Prepared;
    internal EffectStackPolicy? Limits;
}

/// <summary>One live engine's exact record analyses; report boundaries and loadouts remain outside this cache.</summary>
public sealed class EffectRecordCache
{
    private sealed record Entry(EvidenceObject Input, EffectRecordAnalysis Output);
    private readonly Dictionary<EffectSignature, List<Entry>> entries = [];
    private readonly FrozenEvidence.Context snapshots = new();
    private object? owner;
    public long AnalyzedRecords { get; private set; }
    public long ReusedRecords { get; private set; }
    public long AssembledWindows { get; private set; }
    public long ReusedWindows { get; private set; }

    private static EvidenceObject Copy(EvidenceObject value) => (EvidenceObject)EvidenceJson.Clone(value);
    private static EffectRecordAnalysis Copy(EffectRecordAnalysis value) => new(Copy(value.Record), value.Labels.ToArray(),
        value.StaticEffects.Select(Copy).ToArray(), value.DynamicEffects.Select(Copy).ToArray())
        {
            Readiness = value.Readiness is not { } readiness ? null : readiness with
            {
                Blocker = readiness.Blocker is null ? null : Copy(readiness.Blocker),
                IncludedReason = readiness.IncludedReason is null ? null : EvidenceJson.Clone(readiness.IncludedReason),
            },
        };

    private static bool SamePairs(IReadOnlyList<KeyValuePair<string, EvidenceValue>>? left,
        IReadOnlyList<KeyValuePair<string, EvidenceValue>>? right) => left is null ? right is null
        : right is not null && left.Count == right.Count && left.Zip(right).All(pair => pair.First.Key == pair.Second.Key
            && Same(pair.First.Value, pair.Second.Value));

    internal static bool Same(EvidenceValue left, EvidenceValue right)
    {
        if (ReferenceEquals(left, right)) return true;
        if (left is EvidenceObject a && right is EvidenceObject b)
            return a.Fields.Count == b.Fields.Count && SamePairs(a.SourcePairs, b.SourcePairs)
                && a.Fields.Zip(b.Fields).All(pair => pair.First.Key == pair.Second.Key && Same(pair.First.Value, pair.Second.Value));
        if (left is EvidenceArray rows && right is EvidenceArray updates)
            return rows.Items.Count == updates.Items.Count && rows.Items.Zip(updates.Items).All(pair => Same(pair.First, pair.Second));
        if (left is EvidenceReal real && right is EvidenceReal otherReal)
            return BitConverter.DoubleToInt64Bits(real.Value) == BitConverter.DoubleToInt64Bits(otherReal.Value);
        return left.GetType() == right.GetType() && left.Equals(right);
    }

    // Cache descendants are immutable. Public reads detach them; live report owners only copy the record root.
    private EffectRecordAnalysis Store(EffectRecordAnalysis result, EvidenceObject savedInput)
    {
        var record = new EvidenceObject(result.Record.Fields.ToDictionary(pair => pair.Key,
            pair => savedInput.Fields.TryGetValue(pair.Key, out var saved) && Same(saved, pair.Value)
                ? saved : snapshots.Capture(pair.Value), StringComparer.Ordinal))
        {
            SourcePairs = SamePairs(savedInput.SourcePairs, result.Record.SourcePairs) ? savedInput.SourcePairs
                : result.Record.SourcePairs?.Select(pair => new KeyValuePair<string, EvidenceValue>(pair.Key, EvidenceJson.Clone(pair.Value))).ToArray(),
        };
        return new((EvidenceObject)snapshots.Capture(record), Array.AsReadOnly(result.Labels.ToArray()),
            Array.AsReadOnly(result.StaticEffects.Select(value => (EvidenceObject)snapshots.Capture(value)).ToArray()),
            Array.AsReadOnly(result.DynamicEffects.Select(value => (EvidenceObject)snapshots.Capture(value)).ToArray()))
            {
                WindowMemo = new(),
                Readiness = result.Readiness is not { } readiness ? null : readiness with
                {
                    Blocker = readiness.Blocker is null ? null : (EvidenceObject)snapshots.Capture(readiness.Blocker),
                    IncludedReason = readiness.IncludedReason is null ? null : snapshots.Capture(readiness.IncludedReason),
                },
            };
    }

    internal EffectRecordAnalysis Analyze(object analyzer, EvidenceObject source,
        Func<EvidenceObject, EffectRecordAnalysis> calculate)
        => AnalyzeCore(analyzer, source, calculate, ownsEvidence: false);

    internal EffectRecordAnalysis AnalyzeOwned(object analyzer, EvidenceObject source,
        Func<EvidenceObject, EffectRecordAnalysis> calculate)
        => AnalyzeCore(analyzer, source, calculate, ownsEvidence: true);

    // Summary consumers only read records. Materialize a writable root only on an actual miss.
    internal EffectRecordAnalysis AnalyzeFrozen(object analyzer, EvidenceObject source,
        Func<EvidenceObject, EffectRecordAnalysis> calculate)
        => AnalyzeCore(analyzer, source, value => calculate(FrozenEvidence.OwnedMutableRoot(value)),
            ownsEvidence: true, frozenOutput: true);

    private static EffectRecordAnalysis ReadOwned(EffectRecordAnalysis value)
        => value with { Record = FrozenEvidence.MutableRoot(value.Record) };

    // Record equality already covers lifetimes, observations and effect evidence. Report-dependent
    // end/line and loadout strength remain outside that identity; an open window must keep advancing.
    internal EvidenceObject? AssembleWindow(EffectRecordAnalysis analysis, BigInteger end, EvidenceValue endLine,
        double strength, Func<EvidenceObject> calculate, EffectStackPolicy? limits = null)
    {
        var memo = analysis.WindowMemo ?? throw new InvalidOperationException("Expected an owned cached record analysis");
        var bits = BitConverter.DoubleToInt64Bits(strength);
        if (memo.Prepared && memo.End == end && Same(memo.EndLine, endLine) && memo.StrengthBits == bits
            && ReferenceEquals(memo.Limits, limits))
        {
            ReusedWindows++;
            return memo.Window;
        }
        var raw = calculate();
        var window = limits is null ? raw : EffectWindowSet.ApplyLimit(raw, limits);
        memo.End = end; memo.EndLine = snapshots.Capture(endLine); memo.StrengthBits = bits;
        memo.Window = window is null ? null : (EvidenceObject)snapshots.Capture(window);
        memo.Prepared = true; memo.Limits = limits;
        AssembledWindows++;
        return memo.Window;
    }

    private EffectRecordAnalysis AnalyzeCore(object analyzer, EvidenceObject source,
        Func<EvidenceObject, EffectRecordAnalysis> calculate, bool ownsEvidence, bool frozenOutput = false)
    {
        if (!ReferenceEquals(owner, analyzer)) { entries.Clear(); snapshots.Clear(); owner = analyzer; }
        var identity = new EffectSignature([source.Get("uid"), source.Get("event_key"), source.Get("ts_ms"),
            source.Get("line_no"), source.Get("target_actor_id")]);
        if (!entries.TryGetValue(identity, out var variants)) entries[identity] = variants = [];
        foreach (var entry in variants)
            if (Same(entry.Input, source))
            {
                ReusedRecords++;
                return frozenOutput ? entry.Output : ownsEvidence ? ReadOwned(entry.Output) : Copy(entry.Output);
            }
        var savedInput = (EvidenceObject)snapshots.Capture(source);
        var result = calculate(source);
        var savedOutput = Store(result, savedInput);
        variants.Add(new(savedInput, savedOutput));
        if (variants.Count > 4) variants.RemoveAt(0);
        AnalyzedRecords++;
        return frozenOutput ? savedOutput : ownsEvidence ? ReadOwned(savedOutput) : result;
    }
}
