using System.Numerics;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Reporting;

/// <summary>File context and display metadata captured before dispatch to the report worker.</summary>
public sealed record ReportMetadataInput(DateOnly ReferenceDate)
{
    public BigInteger? FirstContextMs { get; init; }
    public BigInteger? LastContextMs { get; init; }
    public bool? HasIdentityInference { get; init; }
    public IReadOnlyList<BigInteger> ContractTagIds { get; init; } = [];
    public BigInteger? ContractTagScore { get; init; }
    public IReadOnlyDictionary<string, IReadOnlyDictionary<string, BigInteger>> CharacterSkills { get; init; }
        = new Dictionary<string, IReadOnlyDictionary<string, BigInteger>>();

    public static ReportMetadataInput Capture(BattleIngestionStream stream, DateOnly referenceDate) => new(referenceDate)
    {
        FirstContextMs = stream.FirstContextMs, LastContextMs = stream.LastContextMs,
        HasIdentityInference = stream.HasIdentityInference,
        ContractTagIds = stream.Timers.ContractTagIds.ToArray(), ContractTagScore = stream.Timers.ContractTagScore,
        CharacterSkills = stream.Loadouts.CharacterSkills.ToDictionary(pair => pair.Key,
            pair => (IReadOnlyDictionary<string, BigInteger>)new Dictionary<string, BigInteger>(pair.Value, StringComparer.Ordinal), StringComparer.Ordinal),
    };
}
