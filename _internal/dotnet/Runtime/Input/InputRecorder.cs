using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

public sealed record InputRecordingOptions(string GameExecutable, string LogDirectory, string NativeDirectory, string? Trace = null);
public interface IInputForeground
{
    bool Active { get; }
    IReadOnlyList<string> HeldKeys();
}
public interface IInputBackend : IDisposable
{
    void Pump();
    EvidenceObject Health { get; }
    EvidenceObject Received { get; }
    IReadOnlyList<string> FallbackDevices { get; }
}

/// <summary>Owned by the recorder control thread. Backend callbacks enter through its bounded mailbox.</summary>
public sealed class InputRecorder : IDisposable
{
    private readonly InputRecordingOptions options;
    private readonly IInputForeground target;
    private readonly Func<InputTimestamp> clock;
    private readonly bool administrator;
    private readonly Dictionary<string, EvidenceObject> states = new(StringComparer.Ordinal), devices = new(StringComparer.Ordinal);
    private readonly Dictionary<string, long> received = new(StringComparer.Ordinal), filtered = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> routes = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (string Family, string Backend)> deviceRoutes = new(StringComparer.Ordinal);
    private readonly List<string> errors = [];
    private long backendLost;
    private bool focus, closed;
    private InputLogWriter? writer;
    public string? Trace { get; private set; }
    public string? Path => writer?.Path;
    public bool Focused => focus;
    public Exception? WriterError => writer?.Error;
    public InputRecorder(InputRecordingOptions options, IInputForeground target, bool administrator = false, Func<InputTimestamp>? clock = null)
    { this.options = options; this.target = target; this.administrator = administrator; this.clock = clock ?? InputTimestamp.Now; }

    public void Emit(string type, EvidenceObject fields)
    {
        ObjectDisposedException.ThrowIf(closed, this);
        fields = (EvidenceObject)EvidenceJson.Clone(fields);
        var device = TraceData.S(fields.Get("device"));
        if (type == "gap") backendLost += (long)(TraceData.Int(fields.Fields.GetValueOrDefault("missing_events") ?? fields.Get("count")) ?? 0);
        if (type == "backend_baseline")
        {
            states[device] = TraceData.Obj(fields.Get("values"));
            writer?.Put("baseline", TraceData.Make(("states", new EvidenceObject(new Dictionary<string, EvidenceValue> { [device] = states[device] })),
                ("device", device), ("reason", "device_baseline"))); return;
        }
        if (type == "device") { devices[device] = fields; writer?.Put(type, fields); return; }
        if (type == "error")
        { errors.Add(TraceData.Text(fields.Get("message"), "设备错误")); if (errors.Count > 4) errors.RemoveAt(0); }
        if (type == "device_change" && !TraceData.Truth(fields.Get("connected")))
        { states.Remove(device); devices.Remove(device); writer?.Put("interrupt", TraceData.Make(("reason", "device_disconnected"), ("device", device))); }
        CheckFocus();
        if (type == "input")
        {
            var backend = TraceData.S(fields.Get("backend")); var kind = TraceData.Text(fields.Get("kind"), "other");
            if (backend is "raw_input" or "windows_hook" or "windows_state")
            {
                var family = kind == "key" ? "keyboard" : "mouse";
                if (routes.TryGetValue(family, out var previous) && previous != backend)
                    foreach (var (key, route) in deviceRoutes)
                        if (route == (family, previous))
                        { if (focus) writer?.Put("interrupt", TraceData.Make(("reason", "input_backend_changed"), ("device", key))); states.Remove(key); }
                routes[family] = backend; deviceRoutes[device] = (family, backend);
            }
            received[kind] = received.GetValueOrDefault(kind) + 1;
            var values = states.GetValueOrDefault(device)?.Fields.ToDictionary() ?? new Dictionary<string, EvidenceValue>();
            var code = TraceData.S(fields.Get("code")); values[code] = fields.Get("value");
            if (fields.Get("phase") is EvidenceText { Value: "up" }) values.Remove(code); states[device] = new(values);
            if (!focus) { filtered[kind] = filtered.GetValueOrDefault(kind) + 1; return; }
        }
        writer?.Put(type, fields);
    }
    private EvidenceObject States() => new(states.ToDictionary(pair => pair.Key, pair => (EvidenceValue)pair.Value, StringComparer.Ordinal));
    public void CheckFocus()
    {
        var active = target.Active; if (active == focus) return; focus = active;
        writer?.Put("focus", TraceData.Make(("active", active)));
        if (!active) writer?.Put("interrupt", TraceData.Make(("reason", "focus_lost")));
        else writer?.Put("baseline", TraceData.Make(("states", States()), ("keyboard_vks", target.HeldKeys())));
    }
    public void Rotate(string? trace = null)
    {
        ObjectDisposedException.ThrowIf(closed, this);
        if (writer is not null) { writer.Put("interrupt", TraceData.Make(("reason", "recording_boundary"))); writer.Close("rotation"); writer = null; }
        Trace = trace;
        var now = DateTime.Now;
        var path = trace is not null ? InputLogWriter.Companion(trace) : System.IO.Path.Combine(options.LogDirectory, now.ToString("yyyyMMdd"), $"input_{now:yyyyMMdd_HHmmss_ffffff}.input.jsonl");
        // CreateNew is the authority even if another recorder races the existence check.
        for (var attempt = 0; ; attempt++)
        {
            var candidate = attempt == 0 ? path : path[..^".input.jsonl".Length] + $".part-{clock().WallNs}-{attempt}.input.jsonl";
            try { writer = new(candidate, trace, clock: clock); break; }
            catch (IOException) when (File.Exists(candidate) && attempt < 16) { }
        }
        writer.Put("diagnostic", TraceData.Make(("reason", "input_process_privilege"), ("administrator", administrator)));
        foreach (var fields in devices.Values) writer.Put("device", fields);
        writer.Put("focus", TraceData.Make(("active", focus))); writer.Put("baseline", TraceData.Make(("states", States())));
    }
    public EvidenceObject Status(IInputBackend? windows = null) => TraceData.Make(("status", focus ? "recording" : "waiting_game"),
        ("path", Path), ("count", writer?.Count ?? 0), ("lost", (writer?.Lost ?? 0) + backendLost),
        ("input_received", Counts(received)), ("input_filtered", Counts(filtered)),
        ("raw_received", windows?.Received ?? TraceData.Make()), ("fallback_devices", windows?.FallbackDevices ?? []),
        ("capture_health", windows?.Health ?? TraceData.Make()), ("administrator", administrator), ("errors", errors.ToArray()),
        ("devices", new EvidenceArray(devices.Values.Cast<EvidenceValue>().ToArray())));
    private static EvidenceObject Counts(Dictionary<string, long> source) => new(source.ToDictionary(pair => pair.Key, pair => (EvidenceValue)new EvidenceInteger(pair.Value)));
    public void Close(string reason = "stopped")
    {
        if (closed) return; closed = true;
        if (writer is not null) { writer.Put("interrupt", TraceData.Make(("reason", "stopped"))); writer.Close(reason); }
    }
    public void Dispose() => Close();
}
