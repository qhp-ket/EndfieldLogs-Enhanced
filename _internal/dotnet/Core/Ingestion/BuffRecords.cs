using System.Numerics;
using EndfieldLogs.Core.Compatibility;

namespace EndfieldLogs.Core.Ingestion;

public sealed record BuffAttributeModifier(string AttributeType, string BlackboardKey, string UseKey, double? Value);
public sealed record BuffOperationContext(string SessionId, string OwnerId, EvidenceValue Generation)
{
    public bool Equals(BuffOperationContext? other) => other is not null && SessionId == other.SessionId && OwnerId == other.OwnerId
        && (ReferenceEquals(Generation, other.Generation) || EvidenceJson.PythonEquals(Generation, other.Generation));
    public override int GetHashCode() => HashCode.Combine(SessionId, OwnerId, Generation switch
    {
        EvidenceBoolean flag => new BigInteger(flag.Value ? 1 : 0).GetHashCode(),
        EvidenceInteger integer => integer.Value.GetHashCode(),
        EvidenceReal real when double.IsFinite(real.Value) && Math.Truncate(real.Value) == real.Value => new BigInteger(real.Value).GetHashCode(),
        EvidenceReal real => real.Value.GetHashCode(),
        EvidenceText text => text.Value.GetHashCode(StringComparison.Ordinal),
        EvidenceNull => 0,
        _ => throw new FormatException("Unhashable operation generation"),
    });
}
public sealed record BuffCreationKey(BuffOperationContext Context, BigInteger Sequence, string Uid);
public sealed record BuffCreationHistory(BuffObservation Observation, BuffRecord Record, int InstanceStartLineNumber);
public sealed record BuffKeywordUpdate(BigInteger Generation, BigInteger AddedBuff, EvidenceValue Rows)
{
    public bool SameAs(BuffKeywordUpdate other) => Generation == other.Generation && AddedBuff == other.AddedBuff
        && EvidenceJsonSignature.Sorted(Rows) == EvidenceJsonSignature.Sorted(other.Rows);
}

public sealed record BuffDynamicOperation(int ActionType, BigInteger ActionId, string Key, double? Value, EvidenceObject Identity)
{
    public bool SameAs(BuffDynamicOperation other) => ActionType == other.ActionType && ActionId == other.ActionId && Key == other.Key
        && (Value is null && other.Value is null || Value is double value && other.Value is double right
            && BitConverter.DoubleToUInt64Bits(value) == BitConverter.DoubleToUInt64Bits(right))
        && EvidenceJsonSignature.Sorted(Identity) == EvidenceJsonSignature.Sorted(other.Identity);
}

public sealed class BuffResistanceState
{
    public Dictionary<string, double?> Values { get; } = new(StringComparer.Ordinal);
    public Dictionary<BigInteger, (BigInteger Action, string Key, double? Value)> Seen { get; } = [];
    public BigInteger LastSequence { get; set; } = -1;
    public HashSet<string> Invalid { get; } = new(StringComparer.Ordinal);
}

/// <summary>Open-schema packet evidence; mutations invalidate all views holding the same observation.</summary>
public sealed class BuffObservation
{
    private readonly Dictionary<string, EvidenceValue> fields;
    public BuffObservation(EvidenceObject payload) => fields = new(payload.Fields, StringComparer.Ordinal);
    public EvidenceValue Get(string key) => fields.GetValueOrDefault(key) ?? EvidenceNull.Value;
    public void Set(string key, EvidenceValue value) => fields[key] = value;
    public EvidenceObject Evidence => new(fields);
    public BuffObservation Copy() => new((EvidenceObject)BuffEvidence.Clone(Evidence));
}

public sealed class BuffDynamicState(BuffOperationContext context)
{
    public BuffOperationContext Context { get; } = context;
    public Dictionary<string, double> Values { get; } = new(StringComparer.Ordinal);
    public Dictionary<string, EvidenceValue> ValueSources { get; } = new(StringComparer.Ordinal);
    public BigInteger LastSequence { get; set; } = -1;
    public Dictionary<BigInteger, BuffDynamicOperation> Operations { get; } = [];
    public HashSet<string> InvalidKeys { get; } = new(StringComparer.Ordinal);

    public BuffDynamicState Copy()
    {
        var copy = new BuffDynamicState(Context) { LastSequence = LastSequence };
        foreach (var (key, value) in Values) copy.Values[key] = value;
        foreach (var (key, value) in ValueSources) copy.ValueSources[key] = BuffEvidence.Clone(value);
        foreach (var (key, value) in Operations) copy.Operations[key] = value;
        copy.InvalidKeys.UnionWith(InvalidKeys);
        return copy;
    }
}

public sealed class BuffRecord(string uid, int lineNumber, long timestampMs, string eventKey, string rawEventKey)
{
    public string Uid { get; } = uid;
    public bool ObservationOnly { get; init; }
    public int LineNumber { get; } = lineNumber;
    public long TimestampMs { get; } = timestampMs;
    public string EventKey { get; set; } = eventKey;
    public string RawEventKey { get; } = rawEventKey;
    public string? SourceCharacterKey { get; set; }
    public string? SourceCharacterName { get; init; }
    public string? SourceWeaponTemplate { get; set; }
    public string? SourceSkillKey { get; set; }
    public string? SourceSkillFamilyKey { get; set; }
    public string? RawSourceCharacterKey { get; init; }
    public string? RawSourceCharacterName { get; init; }
    public string? RawSource { get; init; }
    public string? TargetCharacterKey { get; set; }
    public string? TargetCharacterName { get; init; }
    public string? TargetEnemyKey { get; set; }
    public string? TargetEnemyName { get; init; }
    public string OwnerRaw { get; init; } = "";
    public string? TargetActorId { get; set; }
    public string? SourceActorId { get; set; }
    public EvidenceObject? PacketMapping { get; init; }
    public bool PacketMappingRejected { get; init; }
    public BigInteger? RawDurationMs { get; set; }
    public string? RawDurationSource { get; set; }
    public string? LifetimeMode { get; set; }
    public long? EndTimestampMs { get; set; }
    public int? EndLineNumber { get; set; }
    public List<string> BlackboardKeys { get; set; } = [];
    public Dictionary<string, double> BlackboardValues { get; set; } = new(StringComparer.Ordinal);
    public List<string> AttributeTypes { get; set; } = [];
    public List<BuffAttributeModifier> AttributeModifiers { get; set; } = [];
    public bool IsWeaponBuff { get; init; }
    public int InstanceStartLineNumber { get; set; } = lineNumber;
    public List<BuffObservation> EnableObservations { get; set; } = [];
    public List<BuffObservation> CreationObservations { get; set; } = [];
    public List<BuffObservation> AttributeRefreshSnapshots { get; set; } = [];
    public List<BuffObservation>? OriginObservations { get; set; }
    public List<BuffObservation>? RepeatedCreationObservations { get; set; }
    public List<BuffObservation>? PacketCreationContexts { get; set; }
    public List<BuffObservation>? ResistanceParameterSnapshots { get; set; }
    public Dictionary<BigInteger, BuffKeywordUpdate>? KeywordSeenUpdates { get; set; }
    public List<BuffObservation>? KeywordRateSnapshots { get; set; }
    public BuffResistanceState? ResistanceState { get; set; }
    public Dictionary<string, double> ObservedBlackboardValues { get; set; } = new(StringComparer.Ordinal);
    public BuffDynamicState? DynamicState { get; set; }
    public HashSet<BuffOperationContext> DynamicSeenContexts { get; set; } = [];
    public HashSet<string> DynamicUnresolvedKeys { get; set; } = new(StringComparer.Ordinal);
    public bool LiveIdentityConflict { get; set; }
    public bool DynamicIdentityConflict { get; set; }
    public bool ConflictingEnableState { get; set; }
    public bool SnapshotUpdate { get; set; }
    public long? SnapshotEndTimestampMs { get; set; }
    public int? SnapshotEndLineNumber { get; set; }
    public BuffRecord? PreviousSnapshot { get; set; }
    public (long? Time, int? Line)? PreviousSnapshotBoundary { get; set; }
}

internal static class BuffEvidence
{
    public static EvidenceValue Hook(EvidenceValue value) => value switch
    {
        EvidenceObject { SourcePairs: { } pairs } => new EvidenceArray(pairs.Select(pair => (EvidenceValue)new EvidenceArray([new EvidenceText(pair.Key), Hook(pair.Value)])).ToArray()),
        EvidenceObject obj => new EvidenceObject(obj.Fields.ToDictionary(pair => pair.Key, pair => Hook(pair.Value), StringComparer.Ordinal)),
        EvidenceArray array => new EvidenceArray(array.Items.Select(Hook).ToArray()),
        _ => value,
    };
    public static EvidenceValue Clone(EvidenceValue value) => EvidenceJson.Clone(value);

    public static EvidenceObject Object(params (string Key, EvidenceValue Value)[] fields) => new(fields.ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.Ordinal));
    public static EvidenceValue Text(string? value) => value is null ? EvidenceNull.Value : new EvidenceText(value);
    public static EvidenceValue Number(BigInteger? value) => value is BigInteger number ? new EvidenceInteger(number) : EvidenceNull.Value;
    public static EvidenceObject Blackboard(IReadOnlyDictionary<string, double> values) => new(values.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceReal(pair.Value), StringComparer.Ordinal));
    public static BigInteger? Integer(EvidenceValue value) => value is EvidenceInteger integer ? integer.Value : null;
    public static string? String(EvidenceValue value) => (value as EvidenceText)?.Value;
    public static EvidenceObject Pairs(EvidenceValue value)
    {
        // object_pairs_hook=list also represents an empty object as an empty list.
        if (value is EvidenceArray { Items.Count: 0 }) return new(new Dictionary<string, EvidenceValue>());
        if (value is not EvidenceObject obj || obj.SourcePairs is { } pairs && pairs.Count != obj.Fields.Count)
            throw new FormatException("Invalid or duplicate observation fields");
        return new(obj.Fields);
    }
    public static EvidenceObject ParseObject(string text)
    {
        if (!text.StartsWith('{')) throw new FormatException("Observation must begin with an object");
        return Pairs(EvidenceJson.ParseWithPairs(text));
    }
    public static double? FiniteNumber(EvidenceValue value) => value switch
    {
        EvidenceInteger integer when double.IsFinite((double)integer.Value) => (double)integer.Value,
        EvidenceReal real when double.IsFinite(real.Value) => real.Value,
        _ => null,
    };
    public static double? OptionalFloat(EvidenceValue value) => value is EvidenceText text ? TraceFields.OptionalFloat(text.Value) : FiniteNumber(value);
}
