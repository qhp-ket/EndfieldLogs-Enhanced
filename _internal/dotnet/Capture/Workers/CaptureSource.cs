using System.Runtime.Versioning;
using EndfieldLogs.Native.Capture;

namespace EndfieldLogs.Capture.Workers;

public interface ICaptureSource : IDisposable
{
    NativePacket? Read();
    PcapStatistics? Statistics();
}

[SupportedOSPlatform("windows")]
public sealed class PcapCaptureSource(PcapLibrary api, string device, string filter) : ICaptureSource
{
    private readonly PcapHandle handle = api.Open(device, filter);
    public NativePacket? Read() => api.Read(handle);
    public PcapStatistics? Statistics() => api.Statistics(handle);
    public void Dispose() => handle.Dispose();
}
