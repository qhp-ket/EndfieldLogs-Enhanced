using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.Ingestion;

namespace EndfieldLogs.Core.Timing;

public static class TimerEvidenceValidator
{
    public const string StartSource = "SC_GAME_MECHANICS_SYNC_CHALLENGE_START";
    public const string FreezeSource = "SC_GAME_MECHANICS_MODIFY_INST_TIME_FREEZE";

    private static string? Text(EvidenceValue value) => (value as EvidenceText)?.Value;
    private static BigInteger? Integer(EvidenceValue value) => (value as EvidenceInteger)?.Value;
    private static bool Decimal(string? value) => value is { Length: > 0 } && value.EnumerateRunes().All(Rune.IsDigit);
    private static bool AsciiPositive(string? value) => value is not null && Regex.IsMatch(value,@"\A[0-9]+\z") && TraceFields.OptionalInteger(value) > 0;

    public static IReadOnlyList<string> Validate(EvidenceValue evidence,EvidenceValue durationMs,string? gameId)
    {
        if (evidence is not EvidenceObject document || Integer(document.Get("version")) != 1) return ["missing_official_timer_evidence"];
        if (document.Get("start") is not EvidenceObject start) return ["missing_official_start"];
        if (document.Get("complete") is not EvidenceObject complete) return ["missing_official_completion"];
        HashSet<string> errors = new(StringComparer.Ordinal);
        string[] Result(string? extra=null)
        {
            if (extra is not null) errors.Add(extra);
            return errors.Order(StringComparer.Ordinal).ToArray();
        }
        if (Text(start.Get("source")) != StartSource || Text(complete.Get("source")) is not ("SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE" or "SC_SYNC_WEEK_RAID_SETTLEMENT"))
            errors.Add("unsupported_official_timer_source");
        if (!AsciiPositive(Text(start.Get("challengeStartTs")))) errors.Add("missing_official_challenge_identity");
        var startGame = Text(start.Get("gameId"));
        var startGameValue = start.Get("gameId");
        if (string.IsNullOrEmpty(startGame) || Text(complete.Get("gameId")) != startGame || gameId != startGame)
            errors.Add("official_timer_game_id_mismatch");
        if (Integer(start.Get("line")) is not BigInteger startLine || Integer(complete.Get("line")) is not BigInteger completeLine || !(0 < startLine && startLine < completeLine))
            return Result("official_timer_event_order_invalid");
        if (Text(complete.Get("isPass")) != "1") errors.Add("official_challenge_not_passed");
        var rawDuration = Text(complete.Get("passTimeMs"));
        if (!AsciiPositive(rawDuration)) errors.Add("invalid_official_duration");
        else if (Integer(durationMs) != TraceFields.OptionalInteger(rawDuration)) errors.Add("official_duration_payload_mismatch");
        if (document.Get("conflicts") is not EvidenceArray { Items.Count: 0 }) errors.Add("conflicting_official_timer_events");
        if (document.Get("events") is not EvidenceArray events) return Result("invalid_timer_events");
        var previous = startLine;
        Dictionary<BigInteger,BigInteger> freezes = [];
        foreach (var item in events.Items)
        {
            if (item is not EvidenceObject row || Integer(row.Get("line")) is not BigInteger line || !(previous < line && line < completeLine))
            {
                errors.Add("official_timer_event_order_invalid");
                continue;
            }
            previous = line;
            var kind = Text(row.Get("kind"));
            if (kind == "boundary")
            {
                if (row.Get("gameId") is EvidenceNull || Text(row.Get("gameId")) == "" || EvidenceJson.PythonEquals(row.Get("gameId"),startGameValue))
                    errors.Add("official_challenge_interrupted");
            }
            else if (kind == "freeze")
            {
                if (!EvidenceJson.PythonEquals(row.Get("gameId"),startGameValue)) continue;
                var raw = Text(row.Get("freezeInfos"));
                var count = Text(row.Get("count"));
                if (row.Get("freezeInfos") is EvidenceNull && count == "0") raw = "[]";
                if (Text(row.Get("source")) != FreezeSource || raw is null || !Regex.IsMatch(raw,@"\A\[(?:[0-9]+:[0-9]+(?:,[0-9]+:[0-9]+)*)?\]\z") || !Decimal(count))
                {
                    errors.Add("invalid_official_freeze_record");
                    continue;
                }
                var pairs = raw[1..^1].Split(',',StringSplitOptions.RemoveEmptyEntries).Select(token => token.Split(':')
                    .Select(part => TraceFields.OptionalInteger(part)!.Value).ToArray()).ToArray();
                if (pairs.Length != TraceFields.OptionalInteger(count) || pairs.Select(pair => pair[0]).Distinct().Count() != pairs.Length)
                {
                    errors.Add("conflicting_official_freeze_record");
                    continue;
                }
                foreach (var pair in pairs)
                {
                    if (freezes.TryGetValue(pair[0],out var prior) && pair[1] < prior) errors.Add("official_freeze_counter_regressed");
                    freezes[pair[0]] = pair[1];
                }
            }
            else if (kind == "battle_end" && Text(row.Get("source")) == "PacketBattleState")
            {
                var values = new[] { "startMs", "endMs", "packetElapsedMs" }.Select(key => Text(row.Get(key))).ToArray();
                if (values.All(Decimal))
                {
                    var begin = TraceFields.OptionalInteger(values[0])!.Value;
                    var end = TraceFields.OptionalInteger(values[1])!.Value;
                    var elapsed = TraceFields.OptionalInteger(values[2])!.Value;
                    if (end < begin || end-begin != elapsed) errors.Add("packet_stage_timer_arithmetic_conflict");
                }
            }
            else if (kind is not ("battle_start" or "battle_end")) errors.Add("unsupported_timer_event");
        }
        return Result();
    }
}
