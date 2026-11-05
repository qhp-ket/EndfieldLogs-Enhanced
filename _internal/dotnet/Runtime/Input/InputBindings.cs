using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Storage;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public sealed record InputBinding(string? SourcePath, bool Visible, double OffsetMs, double? StartOverride,
    IReadOnlyDictionary<int, string> ManualSlots, bool Manual, IReadOnlyList<string>? SourcePaths = null);

public static class InputBindings
{
    public static InputBinding Read(EvidenceValue? value, string trace)
    {
        var data = TraceData.Obj(value); var directory = Path.GetDirectoryName(Path.GetFullPath(trace))!;
        var source = data.Get("path") is EvidenceText { Value.Length: > 0 } path ? PhysicalPaths.Resolve(Path.GetFullPath(path.Value, directory)) : null;
        var sources = data.Get("paths") is EvidenceArray paths ? paths.Items.OfType<EvidenceText>().Where(item => item.Value.Length > 0)
            .Select(item => PhysicalPaths.Resolve(Path.GetFullPath(item.Value, directory))).Distinct(StringComparer.OrdinalIgnoreCase).ToArray() : null;
        double? Finite(string key, double? fallback) => data.Get(key) is EvidenceInteger or EvidenceReal
            && TraceData.Float(data.Get(key)) is { } number && double.IsFinite(number) ? number : fallback;
        var slots = TraceData.Obj(data.Get("manual_slots")).Fields.Where(pair => pair.Key is "0" or "1" or "2" or "3" && pair.Value is EvidenceText)
            .ToDictionary(pair => int.Parse(pair.Key), pair => ((EvidenceText)pair.Value).Value);
        return new(source, data.Get("visible") is EvidenceBoolean { Value: true }, Finite("offset_ms", 0)!.Value, Finite("start_override", null), slots,
            data.Get("manual") is EvidenceBoolean { Value: true }, sources);
    }
    public static EvidenceObject Write(string trace, InputBinding binding)
    {
        var source = binding.SourcePath is null ? null : Path.GetRelativePath(Path.GetDirectoryName(PhysicalPaths.Resolve(trace))!, PhysicalPaths.Resolve(binding.SourcePath));
        var slots = new EvidenceObject(binding.ManualSlots.ToDictionary(pair => pair.Key.ToString(System.Globalization.CultureInfo.InvariantCulture), pair => (EvidenceValue)new EvidenceText(pair.Value)));
        var result = TraceData.Make(("path", source), ("visible", binding.Visible), ("offset_ms", binding.OffsetMs), ("start_override", binding.StartOverride),
            ("manual_slots", slots), ("manual", binding.Manual));
        if (binding.SourcePaths is not { Count: > 1 } sources) return result;
        var fields = result.Fields.ToDictionary();
        fields["paths"] = new EvidenceArray(sources.Select(path => (EvidenceValue)new EvidenceText(
            Path.GetRelativePath(Path.GetDirectoryName(PhysicalPaths.Resolve(trace))!, PhysicalPaths.Resolve(path)))).ToArray());
        return new(fields);
    }
}
