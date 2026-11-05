using System.Security.Cryptography;
using System.Runtime.Versioning;
using EndfieldLogs.Capture;
using EndfieldLogs.Capture.Cryptography;
using EndfieldLogs.Capture.Framing;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Cryptography;

namespace EndfieldLogs.Runtime.Capture;

/// <summary>The native boundary; the service owns one backend for its entire lifetime.</summary>
public interface ICaptureBackend : IDisposable
{
    MessageRegistry Registry { get; }
    GameProcessObservation ObserveGame();
    ICaptureDevices OpenCapture(Action<CapturedPacket> onPacket, Action<string, Exception?> diagnostic);
    byte[] DecryptLogin(byte[] encrypted);
    byte[] DecryptKey(byte[] encrypted);
}

[SupportedOSPlatform("windows")]
internal sealed class WindowsCaptureBackend : ICaptureBackend
{
    private readonly RSA key;
    private readonly SrsaBridge bridge;
    private readonly GameProcessMonitor monitor;
    private readonly string device;
    public MessageRegistry Registry { get; }

    public WindowsCaptureBackend(ResourceFiles resources, GameCaptureOptions options)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Game capture requires Windows");
        Registry = new(resources.PathFor("data"));
        monitor = new(options.GameExecutable); device = options.NpcapDevice;
        key = CaptureKey.Load(options.RsaKeyPath);
        try { bridge = new(options.NativeGameDirectory); }
        catch { key.Dispose(); throw; }
    }

    public GameProcessObservation ObserveGame()
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        return monitor.Read();
    }
    public ICaptureDevices OpenCapture(Action<CapturedPacket> onPacket, Action<string, Exception?> diagnostic)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        return CaptureManager.Create(device, onPacket, diagnostic);
    }
    public byte[] DecryptLogin(byte[] encrypted)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException();
        return bridge.DecryptLoginBody(encrypted);
    }
    public byte[] DecryptKey(byte[] encrypted) => CaptureKey.DecryptSessionKey(key, encrypted);
    public void Dispose() { bridge.Dispose(); key.Dispose(); }
}
