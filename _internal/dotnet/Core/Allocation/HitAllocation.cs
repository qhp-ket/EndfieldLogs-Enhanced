using System.Numerics;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Effects;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Reporting;

namespace EndfieldLogs.Core.Allocation;

public sealed record AllocationEvidenceInput(ReportHitInput Hit, IReadOnlyList<EvidenceObject> Windows,
    IReadOnlyList<EvidenceObject>? ConditionRecords = null,
    IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>>? ConditionsByTarget = null,
    IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>>? ConditionsByUid = null,
    IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>>? ConditionsByActor = null,
    IReadOnlyDictionary<string, IReadOnlyList<EvidenceObject>>? BuffRecordsByUid = null,
    IReadOnlyList<int>? WindowIndices = null, bool IncludeDebug = false)
{
    // Only the ordered ledger knows which windows were evaluated on its preceding hit.
    internal IReadOnlyList<int>? WindowResetIndices { get; init; }
    // The ledger creates this buffer once per report and never exposes an intermediate hit's array.
    internal bool OwnsWindowBuffer { get; init; }
    // Cached live allocation retains the pristine input for comparison; only uncached private reports consume it.
    internal bool ConsumesHit { get; init; }
}

public sealed record ExternalEffectContribution(string Provider, double Rate, EvidenceObject? Evidence);

/// <summary>One ordered hit's owned state. Allocation phases share it; separate hits never share accumulators.</summary>
public sealed class HitAllocation
{
    internal HitAllocation(AllocationEvidenceInput input)
    {
        Input = input;
        Hit = input.ConsumesHit ? input.Hit.Evidence : (EvidenceObject)BuffEvidence.Clone(input.Hit.Evidence);
        Windows = input.OwnsWindowBuffer ? input.Windows : input.Windows.ToArray();
        NumericBaseline = input.ConsumesHit ? input.Hit.Baseline
            : input.Hit.Baseline.ToDictionary(pair => pair.Key, pair => BuffEvidence.Clone(pair.Value));
    }

    public AllocationEvidenceInput Input { get; }
    public bool IncludeDebug => Input.IncludeDebug;
    public EvidenceObject Hit { get; internal set; }
    public IReadOnlyList<EvidenceObject> Windows { get; internal set; }
    public IReadOnlyDictionary<BigInteger, EvidenceValue> NumericBaseline { get; }
    public string Attacker { get; internal set; } = "";
    public string Target { get; internal set; } = "";
    public double HitValue { get; internal set; }
    public long TimestampMs { get; internal set; }
    public int LineNumber { get; internal set; }
    public string? Element { get; internal set; }
    public string? School { get; internal set; }
    public ArtsStrengthDamage ArtsStrength { get; internal set; } = new(false, null, null, 0);
    public AttackDependenceResult Attack { get; internal set; } = new(AttackDependence.Unknown, EvidenceNull.Value);
    public EvidenceObject PacketModifiers { get; internal set; } = new(new Dictionary<string, EvidenceValue>());
    public EvidenceObject PacketAttributes { get; internal set; } = new(new Dictionary<string, EvidenceValue>());
    public IReadOnlySet<string> AttackerModifierUids { get; internal set; } = new HashSet<string>();
    public IReadOnlySet<string> DefenderModifierUids { get; internal set; } = new HashSet<string>();
    public IReadOnlySet<(string Zone, string Element)> DefenderAllowedEffects { get; internal set; } = new HashSet<(string, string)>();
    public int? ResistanceAttribute { get; internal set; }
    public IReadOnlyList<string> ResistanceRows { get; internal set; } = [];
    public double? EffectiveResistance { get; internal set; }
    public double? ResistanceNumerator { get; internal set; }
    public string ResistanceSource { get; internal set; } = "";
    public IReadOnlyList<int> WindowIndices { get; internal set; } = [];
    internal bool RequiresFullWindowReset { get; set; }
    public IReadOnlySet<EffectSignature> MatchedDefenderSignatures { get; internal set; } = new HashSet<EffectSignature>();
    public IReadOnlySet<string> ActiveTargetBuffIds { get; internal set; } = new HashSet<string>();
    public IReadOnlyDictionary<int, IReadOnlyList<EvidenceValue>> EffectsAtHit { get; private set; } = new Dictionary<int, IReadOnlyList<EvidenceValue>>();
    public IReadOnlySet<string> UnresolvedStackZones { get; private set; } = new HashSet<string>();

    public void SelectStackEffects(EffectStackPolicy policy)
    {
        var result = EffectStackSelection.SelectTracked(Hit, Windows,
            new(TimestampMs, LineNumber, (Hit.Get("packet_seq_id") as EvidenceInteger)?.Value,
                (Hit.Get("packet_session_id") as EvidenceText)?.Value), policy, WindowIndices, Input.WindowResetIndices, IncludeDebug,
            Input.OwnsWindowBuffer);
        Hit = result.Hit;
        Windows = result.Windows;
        EffectsAtHit = result.EffectsAtHit;
        UnresolvedStackZones = result.UnresolvedZones;
        IgnoredEffects.AddRange(result.IgnoredEffects);
    }

    internal Dictionary<string, List<ExternalEffectContribution>> ExternalByZone { get; } = new(StringComparer.Ordinal);
    internal Dictionary<string, double> SelfByZone { get; } = new(StringComparer.Ordinal);
    internal Dictionary<string, double> SelfFactorByZone { get; } = new(StringComparer.Ordinal);
    internal Dictionary<BigInteger, double> CapturedByAttribute { get; } = [];
    internal Dictionary<string, List<EvidenceObject>> ContributorsByZone { get; } = new(StringComparer.Ordinal);
    internal List<EvidenceObject> IgnoredEffects { get; } = [];
    internal bool InvalidNumericAllocation { get; set; }
    internal string? AttackBaselineError { get; set; }
    internal Dictionary<string, double> Multipliers { get; } = new(StringComparer.Ordinal);
    internal Dictionary<string, double> ExternalSums { get; } = new(StringComparer.Ordinal);
}
