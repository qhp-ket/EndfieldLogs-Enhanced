namespace EndfieldLogs.Native.Input;

/// <summary>Explicitly lossy 8ms compatibility observations, delayed to let raw/hooks take precedence.</summary>
public sealed class InputStateSampler(Action<NativeInputReport> emit)
{
    private readonly object gate = new();
    private Dictionary<(string Code, string Phase), long> delivered = [];
    private HashSet<int>? previous;
    private readonly List<NativeInputReport> pending = [];
    private readonly HashSet<string> announced = [];
    private long? lastSample;
    public long Samples { get; private set; }
    public IReadOnlyList<string> Announced => announced.Order(StringComparer.Ordinal).ToArray();
    public void Note(NativeInputReport report)
    {
        if (report.Type != "input" || report.Fields.GetValueOrDefault("phase") is not string phase || phase is not ("down" or "up" or "repeat")) return;
        var code = (string)report.Fields["code"]!;
        lock (gate) delivered[(code, phase == "repeat" ? "down" : phase)] = (long)report.Fields["mono_ns"]!;
    }
    public void Sample(long mono, long wall, bool focused, Func<int, bool> read)
    {
        if (!focused) { previous = null; pending.Clear(); lock (gate) delivered.Clear(); lastSample = null; return; }
        if (lastSample is { } last && mono - last < 8_000_000) return;
        lastSample = mono; Samples++;
        var values = Enumerable.Range(1, 255).Where(read).ToHashSet();
        if (previous is not null)
            foreach (var vk in values.Except(previous).Concat(previous.Except(values)).Order())
            {
                if (vk is >= 0xa0 and <= 0xa5) continue;
                var mouse = vk switch { 1 => 1, 2 => 2, 4 => 3, 5 => 4, 6 => 5, _ => 0 };
                pending.Add(NativeInputReport.Create("input", ("code", mouse != 0 ? "M:" + mouse : "K:" + RawInputDecoder.KeyCode(vk)),
                    ("phase", values.Contains(vk) ? "down" : "up"), ("value", values.Contains(vk) ? 1 : 0), ("kind", mouse != 0 ? "button" : "key"),
                    ("mono_ns", mono), ("wall_ns", wall), ("raw", NativeInputReport.FieldsOf(("vk", vk), ("observation", "sampled_state"), ("sample_interval_ms", 8)))));
            }
        previous = values;
        for (var at = 0; at < pending.Count;)
        {
            var report = pending[at]; var eventMono = (long)report.Fields["mono_ns"]!;
            if (mono - eventMono < 80_000_000) { at++; continue; }
            pending.RemoveAt(at); var fields = report.Fields;
            lock (gate)
                if (delivered.TryGetValue(((string)fields["code"]!, (string)fields["phase"]!), out var recent) && Math.Abs(recent - eventMono) <= 160_000_000) continue;
            var device = (string)fields["kind"]! == "key" ? "windows:state:keyboard" : "windows:state:mouse";
            if (announced.Add(device))
            {
                emit(NativeInputReport.Create("device", ("device", device), ("backend", "windows_state"), ("device_identity_available", false), ("name", "Windows 状态采样（兼容模式）")));
                emit(NativeInputReport.Create("diagnostic", ("reason", "input_state_sampling_fallback"), ("device", device), ("sample_interval_ms", 8),
                    ("message", "原始报告和事件回调未送达，使用前台按键状态采样；无物理设备身份、自动重复、滚轮及原始鼠标位移，短于采样间隔的点击可能遗漏。")));
            }
            var output = fields.ToDictionary(); output["device"] = device; output["backend"] = "windows_state";
            output["device_identity_available"] = false; output["timing_uncertainty_ms"] = 8; emit(new("input", output));
        }
        lock (gate) delivered = delivered.Where(pair => mono - pair.Value < 1_000_000_000).ToDictionary();
    }
}
