using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using System.Security.Cryptography;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Core.History;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.History;

public sealed partial class HistoryCatalog(TimeZoneInfo? timeZone = null)
{
    private readonly TimeZoneInfo timeZone = timeZone ?? TimeZoneInfo.Local;
    private static readonly UTF8Encoding Utf8 = new(false, true);
    [GeneratedRegex(@"(20\d{6})")]
    private static partial Regex FileDate();
    private DateTime Local(long stamp) => TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds(stamp), timeZone).DateTime;
    public IReadOnlyList<HistoryRecord> Read(string path, bool trace, CancellationToken cancellationToken = default)
    {
        path = Path.GetFullPath(path); var signature = HistoryFileSignature.Read(path);
        if (trace && Path.GetExtension(path).Equals(".jsonl", StringComparison.OrdinalIgnoreCase))
            return ReadStructured(path, cancellationToken);
        if (!trace && SessionVolumes.Resolve(path, cancellationToken) is { } session && session.Volumes[0].Header is not null)
            return ReadSession(session, cancellationToken);
        using FileStream stream = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        var bom = 0;
        if (trace && stream.Length >= 3)
        {
            Span<byte> prefix = stackalloc byte[3]; stream.ReadExactly(prefix);
            if (prefix.SequenceEqual(new byte[] { 0xef, 0xbb, 0xbf })) bom = 3;
            else stream.Position = 0;
        }
        using StreamReader reader = new(stream, Utf8, detectEncodingFromByteOrderMarks: false);
        var records = trace ? ParseTraceLines(path, PythonTextLines.ReadKeepEnds(reader, cancellationToken).ToArray(), bom, signature, cancellationToken)
            : ParseEvents(path, reader.ReadToEnd(), signature, cancellationToken);
        if (HistoryFileSignature.Read(path) != signature) throw new InvalidDataException("日志在建立索引时发生变化，请刷新记录后重试");
        return records;
    }
    internal static IReadOnlyList<HistoryRecord> ReadSession(SessionVolumeChain chain, CancellationToken token)
    {
        var first = chain.Volumes[0]; var offset = chain.Volumes[0].Header!.TimeZoneOffsetMinutes;
        var zone = TimeZoneInfo.CreateCustomTimeZone("session-recording", TimeSpan.FromMinutes(offset), "session-recording", "session-recording");
        // Reuse the existing battle/list semantics with one continuous sequence of business rows.
        var text = string.Join('\n', SessionVolumes.ReadLines(chain, token, allowAppend: true)) + "\n";
        return new HistoryCatalog(zone).ParseEvents(first.FilePath, text, first.Signature, token)
            .Select(row => row with { SessionSource = chain }).ToArray();
    }
    private static IReadOnlyList<HistoryRecord> ReadStructured(string path, CancellationToken token) =>
        ReadStructured(TraceVolumes.Resolve(path, token), token);

    internal static IReadOnlyList<HistoryRecord> ReadStructured(TraceVolumeChain chain, CancellationToken token)
    {
        var first = chain.Volumes[0]; var offset = TimeSpan.FromMinutes(first.Header.TimeZoneOffsetMinutes);
        return TraceBattleSplitter.FindEventBounds(TraceVolumes.ReadEvents(chain, token), first.Header.TimeZoneOffsetMinutes,
            cancellationToken: token).Select(segment =>
        {
            var bounds = segment.Bounds;
            var local = DateTimeOffset.FromUnixTimeMilliseconds(segment.FirstHitCapturedAtMs).ToOffset(offset);
            return new HistoryRecord(first.FilePath, bounds.BattleIndex, segment.FirstHitCapturedAtMs,
                $"trace · {local:yyyy-MM-dd HH:mm:ss} · {Path.GetFileName(first.FilePath)} #{bounds.BattleIndex}",
                [], 0, 0, bounds.StartLineIndex, bounds.EndLineIndex, false, true, first.Signature,
                LastHitHint: bounds.LastHitHint, ReferenceDate: local.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture), StructuredSource: chain);
        }).ToArray();
    }

    public static bool SourcesUnchanged(HistoryRecord record)
    {
        try
        {
            return record.StructuredSource is { } chain
                ? TraceVolumes.SameSources(chain, TraceVolumes.Resolve(record.FilePath))
                : record.SessionSource is { } session ? SessionVolumes.SameSources(session, SessionVolumes.Resolve(record.FilePath))
                : HistoryFileSignature.Read(record.FilePath) == record.SourceSignature;
        }
        catch (Exception error) when (error is IOException or InvalidDataException or UnauthorizedAccessException or FormatException or ArgumentException) { return false; }
    }
    public IReadOnlyList<HistoryRecord> ParseTrace(string path, byte[] bytes, HistoryFileSignature signature, CancellationToken cancellationToken = default)
    {
        var bom = bytes.AsSpan().StartsWith(new byte[] { 0xef, 0xbb, 0xbf }) ? 3 : 0;
        var lines = PythonTextLines.SplitKeepEnds(Utf8.GetString(bytes.AsSpan(bom))).ToArray();
        return ParseTraceLines(path, lines, bom, signature, cancellationToken);
    }
    private IReadOnlyList<HistoryRecord> ParseTraceLines(string path, string[] lines, int bom,
        HistoryFileSignature signature, CancellationToken cancellationToken)
    {
        List<long> offsets = [bom];
        foreach (var line in lines)
        { cancellationToken.ThrowIfCancellationRequested(); offsets.Add(offsets[^1] + Utf8.GetByteCount(line)); }
        var match = FileDate().Match(Path.GetFileName(path));
        var reference = match.Success && DateOnly.TryParseExact(match.Groups[1].Value, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out var parsed)
            ? parsed : DateOnly.FromDateTime(Local(signature.ModifiedNanoseconds / 1_000_000));
        return TraceBattleSplitter.FindBounds(lines, cancellationToken: cancellationToken).Select(segment =>
        {
            var time = TimeOnly.ParseExact(segment.FirstHitHint, "HH-mm-ss-fff", CultureInfo.InvariantCulture);
            var local = reference.ToDateTime(time); var stamp = new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(local, timeZone)).ToUnixTimeMilliseconds();
            var start = segment.StartLineIndex; var end = start + segment.ContentLineCount;
            return new HistoryRecord(path, segment.BattleIndex, stamp, $"trace · {local:yyyy-MM-dd HH:mm:ss} · {Path.GetFileName(path)} #{segment.BattleIndex}",
                [], 0, 0, start, end, false, true, signature, offsets[start], offsets[end], segment.LastHitHint, reference.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
        }).ToArray();
    }

    private sealed class Accumulator(string path, int index, long started, int startLine, Dictionary<BigInteger, HistoryPlayer> squad)
    {
        public Dictionary<BigInteger, HistoryPlayer> Players { get; } = squad.ToDictionary(pair => pair.Key, pair => pair.Value with { TotalDamage = 0, MaxDamage = 0, HitCount = 0, CritCount = 0 });
        public long? First, Last;
        public double Total;
        public void Damage(BigInteger attacker, EvidenceArray details, long stamp)
        {
            var damage = 0.0; var maximum = 0.0; var count = 0; var crit = 0;
            foreach (var row in details.Items.OfType<EvidenceObject>())
            {
                var value = row.Fields.GetValueOrDefault("abs_value") ?? row.Fields.GetValueOrDefault("value") ?? new EvidenceReal(0);
                var hit = Math.Abs(TraceData.Float(TraceData.Truth(value) ? value : new EvidenceReal(0)) ?? throw new FormatException("伤害数值无效"));
                if (hit <= 0) continue;
                damage += hit; maximum = Math.Max(maximum, hit); count++; if (TraceData.Truth(row.Get("is_crit"))) crit++;
            }
            if (damage <= 0) return;
            var player = Players[attacker]; Players[attacker] = player with
            { TotalDamage = player.TotalDamage + damage, MaxDamage = Math.Max(player.MaxDamage, maximum), HitCount = player.HitCount + Math.Max(count, 1), CritCount = player.CritCount + crit };
            Total += damage; First = First is null ? stamp : Math.Min(First.Value, stamp); Last = Last is null ? stamp : Math.Max(Last.Value, stamp);
        }
        public HistoryRecord? Finish(int end, HistoryFileSignature signature, Func<long, DateTime> local)
        {
            if (Total <= 0) return null;
            var stamp = First is not null and not 0 ? First.Value : started;
            var players = Players.Values.OrderByDescending(row => row.TotalDamage).ThenBy(row => row.SquadIndex).ThenBy(row => row.DisplayName, PythonDisplay.CodePointComparer).ToArray();
            return new(path, index, stamp, $"{local(stamp):yyyy-MM-dd HH:mm:ss} #{index}", players, Total,
                First is not null && Last is not null ? Math.Max(1, Last.Value - First.Value) : 0, startLine, end, true, false, signature,
                ReferenceDate: DateOnly.FromDateTime(local(stamp)).ToString("yyyy-MM-dd", CultureInfo.InvariantCulture));
        }
    }

    public IReadOnlyList<HistoryRecord> ParseEvents(string path, string text, HistoryFileSignature signature, CancellationToken cancellationToken = default)
    {
        List<HistoryRecord> records = []; Dictionary<BigInteger, HistoryPlayer> squad = []; Accumulator? current = null;
        var index = 0; var lines = PythonTextLines.Split(text).ToArray();
        (string Game, string Start)? activeOfficial = null;
        void Finish(int line) { if (current?.Finish(line, signature, Local) is { } record) records.Add(record); }
        for (var line = 0; line < lines.Length; line++)
        {
            cancellationToken.ThrowIfCancellationRequested(); EvidenceValue value;
            try { value = EvidenceJson.Parse(lines[line]); } catch (FormatException) { continue; }
            if (value is not EvidenceObject row) throw new InvalidDataException("日志事件应为对象");
            var type = TraceData.Present(row.Get("type"), ""); var stamp = (long)(TraceData.Int(TraceData.Truth(row.Get("timestamp_ms")) ? row.Get("timestamp_ms") : new EvidenceInteger(0)) ?? throw new FormatException("事件时间无效"));
            if (type == "SC_GAME_MECHANICS_SYNC_CHALLENGE_START")
            {
                var identity = (TraceData.Text(row.Get("game_id")), TraceData.Present(row.Get("challenge_start_ts"), ""));
                if (activeOfficial != identity || identity.Item2 is "" or "0")
                { Finish(line); current = null; activeOfficial = identity; }
            }
            else if (type is "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE" or "SC_GAME_MECHANICS_SYNC_LEAVE_GAME_INST" or "SC_GAME_MECHANICS_SYNC_RESTART_GAME_INST")
            {
                var game = TraceData.Text(row.Get("game_id"));
                if (activeOfficial is { } active && (game.Length == 0 || game == active.Game))
                {
                    if (type == "SC_GAME_MECHANICS_SYNC_CHALLENGE_COMPLETE") { Finish(line + 1); current = null; }
                    activeOfficial = null;
                }
            }
            EvidenceArray? members = null;
            if (type == "squad_update") members = row.Get("members") as EvidenceArray;
            if (type == "SC_SELF_SCENE_INFO") members = row.Get("char_list") as EvidenceArray ?? new EvidenceArray([]);
            if (members is not null)
            {
                Dictionary<BigInteger, HistoryPlayer> next = [];
                for (var slot = 0; slot < members.Items.Count; slot++)
                {
                    if (members.Items[slot] is not EvidenceObject member || member.Get("battle_inst_id") is EvidenceNull) continue;
                    var id = TraceData.Int(member.Get("battle_inst_id")) ?? throw new FormatException("角色实例无效");
                    var template = member.Get("templateid") is EvidenceNull ? null : TraceData.S(member.Get("templateid"));
                    var display = TraceData.Text(member.Get("display_name"), type == "SC_SELF_SCENE_INFO" && !string.IsNullOrEmpty(template) ? template : "#" + id);
                    var position = (int)(TraceData.Int(member.Fields.GetValueOrDefault("squad_index") ?? new EvidenceInteger(type == "SC_SELF_SCENE_INFO" ? slot : 0)) ?? throw new FormatException("队伍位置无效"));
                    next[id] = new(id, display, template, position);
                }
                if (!squad.Keys.ToHashSet().SetEquals(next.Keys)) { Finish(line); current = null; }
                squad = next; continue;
            }
            if (type == "BattleOpModifyBattleState" && TraceData.Truth(row.Get("is_in_battle")))
            { if (activeOfficial is null || current is null)
                { if (squad.Count > 0) { Finish(line); current = new(path, ++index, stamp, line, squad); } }
                continue; }
            EvidenceObject? damage = type == "damage" ? row : NormalizeDamage(row, type);
            if (damage is null || damage.Get("attacker") is not EvidenceObject attacker || TraceData.Int(attacker.Get("battle_inst_id")) is not { } attackerId || !squad.ContainsKey(attackerId)) continue;
            current ??= new(path, ++index, stamp, line, squad);
            if (damage.Get("details") is EvidenceArray details) current.Damage(attackerId, details, stamp);
        }
        Finish(lines.Length);
        using var digest = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        var ends = records.Select((record, at) => (record.SourceEndLine, at)).GroupBy(pair => pair.SourceEndLine).ToDictionary(group => group.Key, group => group.Select(pair => pair.at).ToArray());
        for (var line = 0; line < lines.Length; line++)
        {
            digest.AppendData(Utf8.GetBytes(lines[line].TrimEnd('\r') + "\n"));
            if (ends.TryGetValue(line + 1, out var positions))
                foreach (var at in positions) records[at] = records[at] with { SourcePrefixSha256 = Convert.ToHexStringLower(digest.GetCurrentHash()) };
        }
        return records;
    }

    private static EvidenceObject? NormalizeDamage(EvidenceObject row, string type)
    {
        if (type != "BattleOpTriggerAction" || row.Get("action") is not EvidenceObject action
            || !(action.Get("action_type") is EvidenceText { Value: "BattleActionDamage" } || EvidenceJson.PythonEquals(action.Get("action_type"), new EvidenceInteger(1)))
            || action.Get("damage_action") is not EvidenceObject damage || damage.Get("details") is not EvidenceArray rows) return null;
        List<EvidenceValue> details = [];
        foreach (var detail in rows.Items.OfType<EvidenceObject>())
        {
            var value = TraceData.Float(TraceData.Truth(detail.Get("value")) ? detail.Get("value") : new EvidenceReal(0)) ?? throw new FormatException("伤害数值无效");
            var raw = detail.Fields.GetValueOrDefault("abs_value") ?? new EvidenceReal(Math.Abs(value));
            var absolute = TraceData.Float(TraceData.Truth(raw) ? raw : new EvidenceReal(Math.Abs(value))) ?? throw new FormatException("伤害数值无效");
            details.Add(TraceData.Make(("value", value), ("abs_value", absolute), ("is_crit", TraceData.Truth(detail.Get("is_crit")))));
        }
        return details.Count == 0 ? null : TraceData.Make(("attacker", TraceData.Make(("battle_inst_id", TraceData.Int(damage.Get("attacker_id")) is { IsZero: false } id ? id : null))), ("details", new EvidenceArray(details)));
    }
}
