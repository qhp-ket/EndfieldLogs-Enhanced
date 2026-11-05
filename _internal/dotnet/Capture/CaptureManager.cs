using System.Runtime.Versioning;
using EndfieldLogs.Capture.Workers;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;

namespace EndfieldLogs.Capture;

public sealed record CaptureStatistics(ulong Received, ulong Dropped, ulong InterfaceDropped);

public sealed class CaptureManager : ICaptureDevices
{
    private readonly object gate = new();
    private readonly IReadOnlyList<DeviceInfo> defaultDevices;
    private readonly Func<DeviceInfo, string, ICaptureSource> open;
    private readonly Action<CapturedPacket> onPacket;
    private readonly Action<string, Exception?>? diagnostic;
    private readonly IDisposable? owner;
    private List<CaptureWorker> handles;
    private FlowKey? lockedFlow;
    private string? lockedDeviceName;
    private bool disposed;

    public CaptureManager(IReadOnlyList<DeviceInfo> devices, Func<DeviceInfo, string, ICaptureSource> open,
        Action<CapturedPacket> onPacket, Action<string, Exception?>? diagnostic=null, IDisposable? owner=null)
    {
        defaultDevices=devices.ToArray(); this.open=open; this.onPacket=onPacket; this.diagnostic=diagnostic; this.owner=owner;
        handles=Build(defaultDevices, DeviceSelection.DiscoveryFilter);
    }

    [SupportedOSPlatform("windows")]
    public static CaptureManager Create(string requestedDevice, Action<CapturedPacket> onPacket,
        Action<string, Exception?>? diagnostic=null)
    {
        var api = new PcapLibrary();
        try
        {
            var devices = DeviceSelection.Select(api.ListDevices(), requestedDevice);
            if (devices.Count == 0) throw new IOException("no Npcap devices matched "+requestedDevice);
            return new(devices, (device, filter) => new PcapCaptureSource(api, device.Name, filter), onPacket, diagnostic, api);
        }
        catch { api.Dispose(); throw; }
    }

    private List<CaptureWorker> Build(IEnumerable<DeviceInfo> devices, string filter)
    {
        List<CaptureWorker> workers = [];
        List<string> failures = [];
        foreach (var device in devices)
        {
            try { workers.Add(new(open(device, filter), device, onPacket, diagnostic)); }
            catch (Exception error)
            {
                failures.Add($"{device.Name} ({device.Description ?? "-"}) -> {error.GetType().Name}: {error.Message}");
                diagnostic?.Invoke("failed to open capture device "+device.Name, error);
            }
        }
        if (workers.Count == 0 && failures.Count > 0) throw new IOException("failed to open any selected Npcap devices:\n"+string.Join('\n', failures));
        return workers;
    }

    private CaptureWorker[] Snapshot()
    {
        lock (gate) return handles.ToArray();
    }

    private void StartHandles(IEnumerable<CaptureWorker> workers)
    {
        var rows = workers.ToArray();
        try { foreach (var worker in rows) worker.Start(); }
        catch { StopHandles(rows); throw; }
    }

    private void StopHandles(IEnumerable<CaptureWorker> workers)
    {
        foreach (var worker in workers)
            try { worker.Stop(); }
            catch (Exception error) { diagnostic?.Invoke("failed to stop capture device "+worker.Device.Name, error); }
    }

    public void Start()
    {
        lock (gate) ObjectDisposedException.ThrowIf(disposed, this);
        StartHandles(Snapshot());
    }

    public void Stop()
    {
        CaptureWorker[] old;
        lock (gate)
        {
            old=handles.ToArray(); handles=[]; lockedFlow=null; lockedDeviceName=null;
        }
        StopHandles(old);
    }

    public void LockToFlow(FlowKey flow, IReadOnlySet<string> observedDevices)
    {
        List<CaptureWorker> next;
        CaptureWorker[] old;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (lockedFlow == flow && lockedDeviceName is not null) return;
            var device = DeviceSelection.ChooseForFlow(defaultDevices, flow, observedDevices);
            if (device is null) { diagnostic?.Invoke("could not determine capture device for flow; keeping broad capture", null); return; }
            next=Build([device], DeviceSelection.FlowFilter(flow)); old=handles.ToArray(); handles=next;
            lockedFlow=flow; lockedDeviceName=device.Name;
        }
        try { StartHandles(next); }
        finally { StopHandles(old); }
    }

    public void RestoreDiscovery()
    {
        List<CaptureWorker> next;
        CaptureWorker[] old;
        lock (gate)
        {
            ObjectDisposedException.ThrowIf(disposed, this);
            if (lockedFlow is null && handles.Count == defaultDevices.Count) return;
            next=Build(defaultDevices, DeviceSelection.DiscoveryFilter); old=handles.ToArray(); handles=next;
            lockedFlow=null; lockedDeviceName=null;
        }
        try { StartHandles(next); }
        finally { StopHandles(old); }
    }

    public CaptureStatistics Statistics()
    {
        ulong received=0, dropped=0, interfaceDropped=0;
        foreach (var handle in Snapshot())
            if (handle.Statistics() is { } value)
            { received+=value.Received; dropped+=value.Dropped; interfaceDropped+=value.InterfaceDropped; }
        return new(received, dropped, interfaceDropped);
    }

    public IReadOnlyList<DeviceInfo> Devices => Snapshot().Select(worker => worker.Device).ToArray();
    public void Dispose()
    {
        lock (gate) { if (disposed) return; disposed=true; }
        try { Stop(); }
        finally { owner?.Dispose(); }
    }
}
