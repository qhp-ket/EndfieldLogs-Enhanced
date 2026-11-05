using EndfieldLogs.Native.Capture;

namespace EndfieldLogs.Capture;

public interface ICaptureDevices : IDisposable
{
    void Start();
    CaptureStatistics Statistics();
    IReadOnlyList<DeviceInfo> Devices { get; }
}
