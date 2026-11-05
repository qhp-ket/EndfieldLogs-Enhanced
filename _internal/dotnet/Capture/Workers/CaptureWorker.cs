using EndfieldLogs.Capture.Transport;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;

namespace EndfieldLogs.Capture.Workers;

public sealed class CaptureWorker : IDisposable
{
    private readonly ICaptureSource source;
    private readonly Action<CapturedPacket> onPacket;
    private readonly Action<string, Exception?>? diagnostic;
    private readonly object lifecycle = new();
    private readonly Thread thread;
    private volatile bool stopping;
    private bool started, closed;
    private Exception? error;
    public DeviceInfo Device { get; }

    public CaptureWorker(ICaptureSource source, DeviceInfo device, Action<CapturedPacket> onPacket,
        Action<string, Exception?>? diagnostic=null)
    {
        this.source=source; Device=device; this.onPacket=onPacket; this.diagnostic=diagnostic;
        thread = new Thread(Run) { Name="pcap:"+device.Name, IsBackground=true };
    }

    public void Start()
    {
        lock (lifecycle)
        {
            if (stopping || closed) throw new InvalidOperationException("capture handle has been stopped");
            if (started) return;
            thread.Start();
            started=true;
        }
    }

    public void Stop(TimeSpan? timeout=null)
    {
        bool wasStarted;
        lock (lifecycle) { stopping=true; wasStarted=started; }
        if (!wasStarted) { CloseOnce(); return; }
        if (Thread.CurrentThread == thread) return;
        if (!thread.Join(timeout ?? TimeSpan.FromSeconds(2)))
        {
            diagnostic?.Invoke("capture thread is still stopping; native close deferred: "+Device.Name, null);
            return;
        }
        CloseOnce();
    }

    public PcapStatistics? Statistics()
    {
        lock (lifecycle)
        {
            if (stopping) return null;
            if (error is not null) throw new IOException($"capture failed on {Device.Name}: {error.Message}", error);
            if (started && !thread.IsAlive) throw new IOException("capture worker exited unexpectedly on "+Device.Name);
            return closed ? null : source.Statistics();
        }
    }

    private void CloseOnce()
    {
        lock (lifecycle)
        {
            if (closed) return;
            closed=true;
            source.Dispose();
        }
    }

    private void Run()
    {
        try
        {
            while (!stopping)
            {
                var raw = source.Read();
                if (stopping) break;
                if (raw is null) continue;
                if (PacketDecoder.Decode(raw.TimestampMs, raw.Data, Device.Name) is { } packet) onPacket(packet);
            }
        }
        catch (Exception failure)
        {
            lock (lifecycle) { if (!stopping) error=failure; }
            if (!stopping) diagnostic?.Invoke("capture worker failed on "+Device.Name, failure);
        }
        finally
        {
            try { CloseOnce(); }
            catch (Exception failure)
            {
                lock (lifecycle) error ??= failure;
                diagnostic?.Invoke("failed to close capture device "+Device.Name, failure);
            }
        }
    }

    public void Dispose() => Stop();
}
