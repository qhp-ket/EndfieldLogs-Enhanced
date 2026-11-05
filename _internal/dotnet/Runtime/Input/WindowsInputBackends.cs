using System.Runtime.Versioning;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Native.Input;
using EndfieldLogs.Runtime.Tracing;

namespace EndfieldLogs.Runtime.Input;

[SupportedOSPlatform("windows")]
public sealed class WindowsInputForeground(string executable) : IInputForeground
{
    private readonly GameForeground foreground = new(executable);
    public bool Active => foreground.Active;
    public IReadOnlyList<string> HeldKeys() => GameForeground.HeldKeys();
}
[SupportedOSPlatform("windows")]
public sealed class WindowsInputBackend : IInputBackend
{
    private readonly WindowsInputSource source;
    public WindowsInputBackend(string executable, Action<string, EvidenceObject> emit) => source = new(executable, report => emit(report.Type, TraceData.Obj(TraceData.Value(report.Fields))));
    public void Pump() => source.Pump();
    public EvidenceObject Health => TraceData.Obj(TraceData.Value(source.Health));
    public EvidenceObject Received => TraceData.Obj(TraceData.Value(source.Received));
    public IReadOnlyList<string> FallbackDevices => source.FallbackDevices;
    public void Dispose() => source.Dispose();
}
public sealed class SdlInputBackend : IInputBackend
{
    private readonly SdlInputSource source;
    public SdlInputBackend(string nativeDirectory, Action<string, EvidenceObject> emit) => source = new(Path.Combine(nativeDirectory, "SDL3.dll"), report => emit(report.Type, TraceData.Obj(TraceData.Value(report.Fields))));
    public void Pump() => source.Pump();
    public EvidenceObject Health => TraceData.Make();
    public EvidenceObject Received => TraceData.Make();
    public IReadOnlyList<string> FallbackDevices => [];
    public void Dispose() => source.Dispose();
}
