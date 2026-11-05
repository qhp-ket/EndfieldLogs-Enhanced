using System.Numerics;
using System.Text.RegularExpressions;

namespace EndfieldLogs.Core.Ingestion;

public sealed record DungeonContext(string Key, string Name);

/// <summary>Ordered timer evidence. Explicit challenge starts reset completion for the new scope.</summary>
public sealed partial class TimerObservationState(Func<string, DungeonContext?> resolveDungeon)
{
    public long? GameStartMs { get; private set; }
    public long? GameEndMs { get; private set; }
    public BigInteger? GameElapsedMs { get; private set; }
    public BigInteger? GameWindowElapsedMs { get; private set; }
    public long? OfficialStartMs { get; private set; }
    public long? OfficialEndMs { get; private set; }
    public BigInteger? OfficialElapsedMs { get; private set; }
    public BigInteger? LiveElapsedMs { get; private set; }
    public BigInteger? PacketElapsedMs { get; private set; }
    public bool StartSeen { get; private set; }
    public bool EndSeen { get; private set; }
    public bool WindowValid { get; private set; } = true;
    public bool ChallengePassConfirmed { get; private set; }
    public bool OfficialPassConfirmed { get; private set; }
    public string CompletionSource { get; private set; } = "";
    public string? DungeonId { get; private set; }
    public DungeonContext? Dungeon { get; private set; }
    public IReadOnlyList<BigInteger> ContractTagIds { get; private set; } = [];
    public BigInteger? ContractTagScore { get; private set; }

    [GeneratedRegex(@"\b(OFFICIAL_TIMER_START|LIVE_TIMER_TICK|OFFICIAL_TIMER_END|GAME_TIMER_START|GAME_TIMER_END)\b")]
    private static partial Regex TimerMarker();

    public void SetDungeonContext(string? value)
    {
        var id = value?.Trim();
        if (string.IsNullOrEmpty(id)) return;
        DungeonId = id;
        Dungeon = resolveDungeon(id);
    }

    private static BigInteger Integer(IReadOnlyDictionary<string, string> fields, string key, int fallback=0) =>
        TraceFields.OptionalInteger(fields.GetValueOrDefault(key)) ?? fallback;

    private static string? Either(IReadOnlyDictionary<string, string> fields, string first, string second) =>
        fields.GetValueOrDefault(first) is { Length: > 0 } value ? value : fields.GetValueOrDefault(second);

    private static bool Authoritative(IReadOnlyDictionary<string, string> fields)
    {
        if (!Integer(fields, "fallback").IsZero || fields.GetValueOrDefault("source")?.EndsWith("Fallback", StringComparison.Ordinal) == true)
            return false;
        return fields.ContainsKey("official") ? !Integer(fields, "official", 1).IsZero
            : fields.GetValueOrDefault("source") != "BattleOpModifyBattleState";
    }

    public bool ObserveTimer(string line, long timestampMs)
    {
        var markers = TimerMarker().Matches(line).Select(match => match.Value).ToHashSet(StringComparer.Ordinal);
        if (markers.Count == 0) return false;
        // The Python dispatcher gives these markers priority even if a malformed line contains several.
        var marker = new[] { "OFFICIAL_TIMER_START", "LIVE_TIMER_TICK", "OFFICIAL_TIMER_END", "GAME_TIMER_START", "GAME_TIMER_END" }.First(markers.Contains);
        return ObserveTimer(marker, TraceFields.Extract(line), timestampMs);
    }

    public bool ObserveTimer(string marker, IReadOnlyDictionary<string, string> fields, long timestampMs)
    {
        if (marker == "OFFICIAL_TIMER_START")
        {
            SetDungeonContext(Either(fields, "gameId", "game_id"));
            OfficialElapsedMs = null;
            OfficialEndMs = null;
            LiveElapsedMs = null;
            GameEndMs = null;
            GameElapsedMs = null;
            GameWindowElapsedMs = null;
            PacketElapsedMs = null;
            EndSeen = false;
            WindowValid = true;
            ChallengePassConfirmed = false;
            OfficialPassConfirmed = false;
            CompletionSource = "";
            OfficialStartMs = timestampMs;
            GameStartMs = timestampMs;
            StartSeen = true;
        }
        else if (marker == "LIVE_TIMER_TICK")
        {
            var elapsed = Integer(fields, "elapsedMs");
            if (elapsed > 0)
            {
                LiveElapsedMs = elapsed;
                GameEndMs = timestampMs;
                GameElapsedMs = elapsed;
                GameWindowElapsedMs = elapsed;
            }
        }
        else if (marker == "OFFICIAL_TIMER_END")
        {
            SetDungeonContext(Either(fields, "gameId", "game_id"));
            OfficialEndMs = timestampMs;
            if (Integer(fields, "isPass") == 1)
            {
                ChallengePassConfirmed = true;
                OfficialPassConfirmed = true;
                CompletionSource = "official_timer_end";
            }
            var elapsed = Integer(fields, "passTime");
            if (elapsed > 0)
            {
                GameEndMs = timestampMs;
                GameElapsedMs = elapsed;
                GameWindowElapsedMs = elapsed;
                OfficialElapsedMs = elapsed;
                EndSeen = true;
            }
        }
        else if (marker == "GAME_TIMER_START")
        {
            if (OfficialStartMs is null && Authoritative(fields) && Integer(fields, "startMs") >= 0)
            {
                GameStartMs = timestampMs;
                StartSeen = true;
            }
        }
        else if (marker == "GAME_TIMER_END")
        {
            var authoritative = Authoritative(fields);
            if (authoritative && Integer(fields, "isPass") == 1)
            {
                ChallengePassConfirmed = true;
                CompletionSource = fields.GetValueOrDefault("source") is { Length: > 0 } source ? source : "game_timer_end";
            }
            var elapsed = Integer(fields, "elapsedMs");
            var wall = Integer(fields, "wallElapsedMs");
            var packet = Integer(fields, "packetElapsedMs");
            if (packet > 0) PacketElapsedMs = packet;
            if (OfficialElapsedMs is null && authoritative && !Integer(fields, "sane", 1).IsZero && elapsed > 0)
            {
                GameEndMs = timestampMs;
                GameElapsedMs = wall > 0 ? wall : elapsed;
                GameWindowElapsedMs = GameElapsedMs;
                EndSeen = true;
            }
        }
        else return false;
        return true;
    }

    public bool ObserveStage(string line)
    {
        var marker = new[] { "DUNGEON_CONTEXT", "BATTLE_RESULT", "CONTRACT_TAGS" }
            .FirstOrDefault(value => line.Contains(" " + value + " ", StringComparison.Ordinal));
        return marker is not null && ObserveStage(marker, TraceFields.Extract(line));
    }

    public bool ObserveStage(string marker, IReadOnlyDictionary<string, string> fields, IReadOnlyList<BigInteger>? tagIds = null)
    {
        if (marker == "DUNGEON_CONTEXT")
            SetDungeonContext(Either(fields, "dungeonId", "dungeon_id"));
        else if (marker == "BATTLE_RESULT")
        {
            SetDungeonContext(Either(fields, "dungeonId", "dungeon_id"));
            if (Integer(fields, "isPass") == 1)
            {
                ChallengePassConfirmed = true;
                CompletionSource = fields.GetValueOrDefault("source") is { Length: > 0 } source ? source : "battle_result";
            }
        }
        else if (marker == "CONTRACT_TAGS")
        {
            SetDungeonContext(Either(fields, "dungeonId", "dungeon_id"));
            var ids = tagIds ?? TraceFields.ContractTagIds(Either(fields, "tagIds", "tag_ids"));
            if (ids.Count > 0) ContractTagIds = ids;
            if (fields.ContainsKey("score")) ContractTagScore = Integer(fields, "score");
        }
        else return false;
        return true;
    }
}
