using System.Numerics;
using EndfieldLogs.Core.Ingestion;
using EndfieldLogs.Core.Timing;

namespace EndfieldLogs.Core.Reporting;

/// <summary>Timer and roster evidence copied with the calculation input on the ingestion owner.</summary>
public sealed record ReportTimingInput
{
    public BigInteger? GameStartMs { get; init; }
    public BigInteger? GameEndMs { get; init; }
    public BigInteger? GameElapsedMs { get; init; }
    public BigInteger? GameWindowElapsedMs { get; init; }
    public BigInteger? OfficialStartMs { get; init; }
    public BigInteger? OfficialEndMs { get; init; }
    public BigInteger? OfficialElapsedMs { get; init; }
    public BigInteger? LiveElapsedMs { get; init; }
    public BigInteger? PacketElapsedMs { get; init; }
    public BigInteger? FirstHitHintMs { get; init; }
    public BigInteger? LastHitHintMs { get; init; }
    public BigInteger? FirstPartyActionMs { get; init; }
    public bool StartSeen { get; init; }
    public bool EndSeen { get; init; }
    public bool WindowValid { get; init; } = true;
    public bool ChallengePassConfirmed { get; init; }
    public bool OfficialPassConfirmed { get; init; }
    public string CompletionSource { get; init; } = "";
    public string? DungeonId { get; init; }
    public DungeonContext? Dungeon { get; init; }
    public IReadOnlyDictionary<int, long>? ObservedTimes { get; init; }
    public IReadOnlyList<KeyValuePair<string, BigInteger>> EnemyCounts { get; init; } = [];
    public bool HasCollectedOfficialEvidence { get; init; }
    public OfficialTimerEvidence? CollectedOfficialEvidence { get; init; }
    public int? EvidenceCount { get; init; }

    public static ReportTimingInput Capture(BattleIngestionStream stream, BigInteger? firstHitHintMs = null,
        BigInteger? lastHitHintMs = null)
    {
        var timer = stream.Timers;
        return new()
        {
            GameStartMs = timer.GameStartMs, GameEndMs = timer.GameEndMs, GameElapsedMs = timer.GameElapsedMs,
            GameWindowElapsedMs = timer.GameWindowElapsedMs, OfficialStartMs = timer.OfficialStartMs,
            OfficialEndMs = timer.OfficialEndMs, OfficialElapsedMs = timer.OfficialElapsedMs,
            LiveElapsedMs = timer.LiveElapsedMs, PacketElapsedMs = timer.PacketElapsedMs,
            FirstHitHintMs = firstHitHintMs, LastHitHintMs = lastHitHintMs, FirstPartyActionMs = stream.Skills.FirstPartyActionMs,
            StartSeen = timer.StartSeen, EndSeen = timer.EndSeen, WindowValid = timer.WindowValid,
            ChallengePassConfirmed = timer.ChallengePassConfirmed, OfficialPassConfirmed = timer.OfficialPassConfirmed,
            CompletionSource = timer.CompletionSource, DungeonId = timer.DungeonId, Dungeon = timer.Dungeon,
            ObservedTimes = new Dictionary<int, long>(stream.TimerObservedTimes), EnemyCounts = stream.Hits.EnemyCounts.ToArray(),
            HasCollectedOfficialEvidence = true, CollectedOfficialEvidence = stream.OfficialTimerCollector.Evidence?.Copy(), EvidenceCount = stream.EvidenceCount,
        };
    }
}
