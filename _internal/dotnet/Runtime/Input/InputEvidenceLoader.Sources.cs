using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.History;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public sealed partial class InputEvidenceLoader
{
    private static IReadOnlyList<string> AssociatedSources(string path, CancellationToken token = default)
    {
        path = Path.GetFullPath(path);
        if (Path.GetExtension(path).Equals(".jsonl", StringComparison.OrdinalIgnoreCase))
            return TraceVolumes.Resolve(path, token).Volumes.Select(volume => volume.FilePath).ToArray();
        if (!Path.GetExtension(path).Equals(".ndjson", StringComparison.OrdinalIgnoreCase)) return [path];
        var session = SessionVolumes.Resolve(path, token);
        var sources = session.Volumes.Select(volume => volume.FilePath).ToList();
        if (!session.IsComplete) throw new InvalidDataException(string.Join('；', session.Issues));
        if (session.Volumes[0].Header is not { } header) return sources;
        var volumes = session.Volumes.Select(volume => volume.Header!.TraceVolume).ToHashSet();
        if (TraceVolumes.Find(Path.GetDirectoryName(path)!, header.TraceRecordingId, token) is { } trace)
            sources.AddRange(trace.Volumes.Where(volume => volumes.Contains(volume.Header.Volume)).Select(volume => volume.FilePath));
        return sources;
    }

    private static string? CompanionSource(string input, IEnumerable<string> sources)
    {
        input = Path.GetFullPath(input);
        return sources.FirstOrDefault(source => string.Equals(input, Path.ChangeExtension(source, ".input.jsonl"), StringComparison.OrdinalIgnoreCase)
            || string.Equals(Path.GetDirectoryName(input), Path.GetDirectoryName(source), StringComparison.OrdinalIgnoreCase)
                && Path.GetFileName(input).StartsWith(Path.GetFileNameWithoutExtension(source) + ".part-", StringComparison.OrdinalIgnoreCase));
    }

    private static IReadOnlyList<InputLoadoutUpdate> EventLoadouts(string path, CancellationToken token)
    {
        List<InputLoadoutUpdate> result = [];
        foreach (var item in TraceVolumes.ReadEvents(TraceVolumes.Resolve(path, token), token))
        {
            if (item.Type == "loadout_group") result.Add(new(item.CapturedAtMs, null, null));
            else if (item.Type == "loadout_slot" && TraceData.Int(item.Data.Get("slot")) is { } slot && slot >= 0 && slot < 4
                && item.Data.Get("template") is EvidenceText { Value.Length: > 0 } name)
                result.Add(new(item.CapturedAtMs, (int)slot, name.Value));
        }
        return result;
    }

    private static IReadOnlyList<InputLoadoutUpdate> SessionLoadouts(string path, CancellationToken token)
    {
        List<InputLoadoutUpdate> result = [];
        foreach (var raw in SessionVolumes.ReadLines(SessionVolumes.Resolve(path, token), token))
        {
            EvidenceValue value; try { value = EvidenceJson.Parse(raw); } catch (FormatException) { continue; }
            if (value is not EvidenceObject row || row.Get("type") is not EvidenceText { Value: "LOADOUT" }) continue;
            var wall = TraceData.Float(row.Fields.GetValueOrDefault("timestamp_ms") ?? new EvidenceInteger(0)) ?? 0;
            result.Add(new(wall, null, null));
            foreach (var item in TraceData.Rows(row.Get("rows")))
                if (item.Get("slot") is EvidenceInteger { Value: var slot } && slot >= 0 && slot < 4 && TraceData.Truth(item.Get("char")))
                    result.Add(new(wall, (int)slot, TraceData.S(item.Get("char"))));
        }
        return result;
    }
}
