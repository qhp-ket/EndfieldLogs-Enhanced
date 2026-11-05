using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public sealed record InputEvidenceRequest(IReadOnlyList<string> Paths, string TracePath, EvidenceObject Battle, EvidenceObject Settings,
    double OffsetMs = 0, IReadOnlyDictionary<int, string>? ManualSlots = null, double? StartOverride = null, bool Verify = true);
public sealed record InputLoadoutUpdate(double WallMs, int? Slot, string? Character);

/// <summary>Disposable sidecar cache and battle-local display projection, independent of report calculations.</summary>
public sealed partial class InputEvidenceLoader(TimeZoneInfo? timeZone = null)
{
    private sealed record CacheKey(string Path, HistoryFileSignature Signature, string Settings);
    private readonly object gate = new();
    private readonly LinkedList<(CacheKey Key, InputArchive Archive)> cache = new();
    private readonly TimeZoneInfo timeZone = timeZone ?? TimeZoneInfo.Local;
    [GeneratedRegex(@"(20\d{6})")]
    private static partial Regex FileDate();
    [GeneratedRegex(@"(\d{2}):(\d{2}):(\d{2})\.(\d{3})")]
    private static partial Regex Stamp();
    [GeneratedRegex(@"\bLOADOUT slot=(\d+) char=([^\s]+)")]
    private static partial Regex Loadout();
    [GeneratedRegex(@"\bLOADOUT reason=")]
    private static partial Regex ResetLoadout();
    [GeneratedRegex(@"(?:[+-]\d{2}:?\d{2}|Z)$")]
    private static partial Regex Offset();
    public static IReadOnlyList<string> Discover(string trace)
    {
        return AssociatedSources(trace).SelectMany(source =>
        {
            var companion = Path.ChangeExtension(source, ".input.jsonl"); var prefix = Path.GetFileNameWithoutExtension(source);
            return (File.Exists(companion) ? new[] { companion } : []).Concat(Directory.EnumerateFiles(Path.GetDirectoryName(source)!, prefix + ".part-*.input.jsonl")
                .Order(StringComparer.Ordinal));
        }).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }
    private InputArchive Archive(string path, InputInterpretationSettings settings, CancellationToken token)
    {
        path = Path.GetFullPath(path); CacheKey key = new(path, HistoryFileSignature.Read(path), PythonSortedJson.Serialize(settings.ToEvidence()));
        lock (gate)
        {
            for (var node = cache.First; node is not null; node = node.Next)
                if (node.Value.Key == key) { var entry = node.Value; cache.Remove(node); cache.AddLast(entry); return entry.Archive; }
        }
        var value = new InputArchive(path, settings.ToEvidence(), token);
        lock (gate) { cache.AddLast((key, value)); while (cache.Count > 2) cache.RemoveFirst(); }
        return value;
    }
    public void ClearCache() { lock (gate) cache.Clear(); }
    private double UnixMs(DateTime value) => (TimeZoneInfo.ConvertTimeToUtc(DateTime.SpecifyKind(value, DateTimeKind.Unspecified), timeZone).Ticks - DateTime.UnixEpoch.Ticks) / 10_000.0;
    public double BattleStartWallMs(EvidenceObject battle)
    {
        var iso = TraceData.Text(battle.Get("battle_start_at"));
        if (iso.Length == 0) throw new InvalidDataException("战斗日期不明确，请手动指定日期和起点");
        var explicitOffset = Offset().IsMatch(iso);
        var local = DateTime.Parse(iso, CultureInfo.InvariantCulture, DateTimeStyles.RoundtripKind);
        DateTimeOffset? offset = explicitOffset ? DateTimeOffset.Parse(iso, CultureInfo.InvariantCulture) : null;
        var start = offset is { } dated ? (dated.UtcTicks - DateTime.UnixEpoch.Ticks) / 10_000.0 : UnixMs(local);
        if (iso.Split('T').Last().Contains('.')) return start;
        var observed = TraceData.Obj(TraceData.Obj(battle.Get("timer_evidence")).Get("start")).Get("observedMs");
        if (battle.Get("timeline_zero_source") is EvidenceText { Value: "official_timer_start" } && observed is EvidenceInteger or EvidenceReal)
        {
            var observedValue = observed is EvidenceInteger number ? PythonIntegerDivision.Divide(number.Value, BigInteger.One) : ((EvidenceReal)observed).Value;
            var midnight = offset is { } value ? (new DateTimeOffset(value.Date, value.Offset).UtcTicks - DateTime.UnixEpoch.Ticks) / 10_000.0 : UnixMs(local.Date);
            var candidate = midnight + (observedValue % 86_400_000 + 86_400_000) % 86_400_000;
            start = new[] { candidate - 86_400_000, candidate, candidate + 86_400_000 }.OrderBy(value => Math.Abs(value - start)).First();
        }
        return start;
    }
    public IReadOnlyList<InputLoadoutUpdate> LoadoutHistory(string path, double startMs, CancellationToken token = default)
    {
        if (Path.GetExtension(path).Equals(".jsonl", StringComparison.OrdinalIgnoreCase)) return EventLoadouts(path, token);
        if (Path.GetExtension(path).Equals(".ndjson", StringComparison.OrdinalIgnoreCase)) return SessionLoadouts(path, token);
        List<InputLoadoutUpdate> result = [];
        var reference = TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds((long)startMs), timeZone);
        var match = FileDate().Match(Path.GetFileName(path)); var day = match.Success ? DateOnly.ParseExact(match.Groups[1].Value, "yyyyMMdd", CultureInfo.InvariantCulture) : DateOnly.FromDateTime(reference.DateTime);
        long? lastTime = null;
        using FileStream stream = new(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
        using StreamReader reader = new(stream, new UTF8Encoding(false, true), detectEncodingFromByteOrderMarks: false);
        var first = true;
        while (reader.ReadLine() is { } raw)
        {
            token.ThrowIfCancellationRequested(); var line = first ? raw.TrimStart('\uFEFF') : raw; first = false;
            var stamp = Stamp().Match(line); if (!stamp.Success) continue;
            var parts = stamp.Groups.Cast<Group>().Skip(1).Select(group => long.Parse(group.Value, CultureInfo.InvariantCulture)).ToArray();
            var tod = ((parts[0] * 60 + parts[1]) * 60 + parts[2]) * 1000 + parts[3];
            if (lastTime is { } previous && tod < previous - 12 * 3_600_000) day = day.AddDays(1); lastTime = tod;
            var at = UnixMs(day.ToDateTime(TimeOnly.MinValue)) + tod;
            if (ResetLoadout().IsMatch(line)) result.Add(new(at, null, null));
            var entry = Loadout().Match(line); if (entry.Success && int.TryParse(entry.Groups[1].Value, out var position) && position < 4) result.Add(new(at, position, entry.Groups[2].Value));
        }
        return result;
    }
    public Task<EvidenceObject> LoadAsync(InputEvidenceRequest request, CancellationToken token = default)
    {
        var owned = request with { Paths = request.Paths.ToArray(), Battle = (EvidenceObject)EvidenceJson.Clone(request.Battle),
            Settings = (EvidenceObject)EvidenceJson.Clone(request.Settings), ManualSlots = request.ManualSlots is null ? null : new Dictionary<int, string>(request.ManualSlots) };
        return Task.Run(() => Load(owned, token), token);
    }
    public EvidenceObject Load(InputEvidenceRequest request, CancellationToken token = default)
    {
        token.ThrowIfCancellationRequested(); var settings = InputInterpretationSettings.Normalize(request.Settings);
        var start = request.StartOverride ?? BattleStartWallMs(request.Battle); var duration = TraceData.Float(request.Battle.Get("duration_ms")) ?? 0;
        var updates = LoadoutHistory(request.TracePath, start, token);
        IReadOnlyList<string> associated = request.Verify ? AssociatedSources(request.TracePath, token) : [];
        List<(double Time, EvidenceObject Value)> actions = []; List<EvidenceValue> raw = []; List<string> warnings = [];
        Dictionary<string, int> inputCounts = new(StringComparer.Ordinal), recordingCounts = new(StringComparer.Ordinal);
        foreach (var path in request.Paths)
        {
            token.ThrowIfCancellationRequested(); var data = Archive(path, settings, token); warnings.AddRange(data.Warnings);
            foreach (var (key, value) in data.InputCounts) recordingCounts[key] = recordingCounts.GetValueOrDefault(key) + value;
            if (request.Verify) warnings.Add(data.VerifyTrace(CompanionSource(path, associated) ?? request.TracePath, token));
            foreach (var action in InputInterpreter.Project(data.Actions, start, duration, offsetMs: request.OffsetMs))
            {
                Dictionary<int, string> slots = [];
                var stamp = PythonIntegerDivision.Divide(action.Intention.StartWallNs, BigInteger.One) / 1e6 + request.OffsetMs;
                foreach (var update in updates)
                { if (update.WallMs > stamp) break; if (update.Slot is { } slot) slots[slot] = update.Character!; else slots.Clear(); }
                if (request.ManualSlots is not null) foreach (var (slot, key) in request.ManualSlots) slots[slot] = key;
                var projected = action with { CharacterKey = action.Intention.Slot is { } position ? slots.GetValueOrDefault(position) : null };
                var fields = projected.ToEvidence().Fields.ToDictionary(); fields["tooltip"] = new EvidenceText(projected.Tooltip); actions.Add((projected.StartMs, new(fields)));
            }
            var from = new BigInteger(Math.Round((start - request.OffsetMs) * 1e6, MidpointRounding.ToEven));
            var to = new BigInteger(Math.Round((start + duration - request.OffsetMs) * 1e6, MidpointRounding.ToEven));
            foreach (var e in data.RawRange(from, to, settings, inputCounts, token))
            {
                var fields = e.Fields.ToDictionary(); var stamp = TraceData.Int(e.Get("wall_ns")) ?? 0;
                fields["time_ms"] = new EvidenceReal(PythonIntegerDivision.Divide(stamp, BigInteger.One) / 1e6 - start + request.OffsetMs); raw.Add(new EvidenceObject(fields));
            }
        }
        return TraceData.Make(("actions", new EvidenceArray(actions.OrderBy(item => item.Time).Select(item => item.Value).ToArray())), ("raw", new EvidenceArray(raw)),
            ("warnings", warnings.Distinct(StringComparer.Ordinal).ToArray()), ("manual_alignment", request.OffsetMs != 0 || request.StartOverride is not null),
            ("start_wall_ms", start), ("settings", settings.ToEvidence()), ("paths", request.Paths),
            ("input_counts", new EvidenceObject(inputCounts.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceInteger(pair.Value)))),
            ("recording_counts", new EvidenceObject(recordingCounts.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceInteger(pair.Value)))));
    }
}
