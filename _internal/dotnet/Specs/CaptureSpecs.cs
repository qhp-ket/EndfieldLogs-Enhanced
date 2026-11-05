using EndfieldLogs.Capture;
using EndfieldLogs.Capture.Workers;
using EndfieldLogs.Core.Models;
using EndfieldLogs.Native.Capture;

internal static class CaptureSpecs
{
    private sealed class Source(Func<NativePacket?> read, PcapStatistics? statistics=null) : ICaptureSource
    {
        public ManualResetEventSlim Closed { get; } = new(false);
        public int CloseCount;
        public NativePacket? Read() => read();
        public PcapStatistics? Statistics() => statistics;
        public void Dispose() { Interlocked.Increment(ref CloseCount); Closed.Set(); }
    }
    private sealed class Owner : IDisposable
    {
        public int Count;
        public void Dispose() => Count++;
    }

    private static readonly DeviceInfo First = new("ethernet", "Ethernet", ["192.0.2.1"], 0);
    private static readonly DeviceInfo Second = new("wifi", "Wi-Fi", ["192.0.2.2"], 0);
    private static readonly byte[] IpPacket = Convert.FromHexString(
        "4500002f0001000040060000c0000201cb00710a75317530ffffffff0000000050180400000000007061796c6f6164");

    public static void Run(Action<bool, string> check)
    {
        var unusedSource = new Source(() => null);
        using (var unused = new CaptureWorker(unusedSource, First, _ => { }))
        {
            unused.Stop(); unused.Stop();
            check(unusedSource.CloseCount == 1, "Unstarted native source closes exactly once");
            try { unused.Start(); throw new InvalidOperationException("Stopped worker restarted"); }
            catch (InvalidOperationException error) when (error.Message == "capture handle has been stopped")
            { check(true, "Stopped worker rejects restart"); }
        }

        var failingSource = new Source(() => throw new IOException("synthetic pcap read failure"));
        using (var failing = new CaptureWorker(failingSource, First, _ => { }))
        {
            failing.Start();
            check(failingSource.Closed.Wait(TimeSpan.FromSeconds(2)), "Failed worker closes native handle");
            try { failing.Statistics(); throw new InvalidOperationException("Worker failure was hidden"); }
            catch (IOException error)
            { check(error.InnerException?.Message == "synthetic pcap read failure", "Worker failure reaches health reader"); }
        }
        check(failingSource.CloseCount == 1, "Failed worker and stop share close ownership");

        using ManualResetEventSlim entered = new(false), release = new(false);
        var blockingSource = new Source(() => { entered.Set(); release.Wait(); return null; });
        using (var blocking = new CaptureWorker(blockingSource, First, _ => { }))
        {
            blocking.Start(); blocking.Start();
            check(entered.Wait(TimeSpan.FromSeconds(2)), "Capture starts one reader");
            blocking.Stop(TimeSpan.Zero);
            check(blockingSource.CloseCount == 0, "Native close is deferred while read remains active");
            release.Set();
            check(blockingSource.Closed.Wait(TimeSpan.FromSeconds(2)), "Worker closes after deferred read returns");
        }
        check(blockingSource.CloseCount == 1, "Deferred close occurs once");

        var selfStopSource = new Source(() => new(123, IpPacket));
        CaptureWorker? selfStop = null;
        selfStop = new(selfStopSource, First, _ => selfStop!.Stop());
        using (selfStop)
        {
            selfStop.Start();
            check(selfStopSource.Closed.Wait(TimeSpan.FromSeconds(2)), "Stop from packet callback avoids self-join");
            check(selfStop.Statistics() is null, "Stopping capture reports no stale statistics");
        }

        var managerFailureSource = new Source(() => throw new IOException("manager failure"));
        Owner owner = new();
        using (var manager = new CaptureManager([First], (_, _) => managerFailureSource, _ => { }, owner:owner))
        {
            manager.Start();
            check(managerFailureSource.Closed.Wait(TimeSpan.FromSeconds(2)), "Manager observes terminal worker");
            try { manager.Statistics(); throw new InvalidOperationException("Manager hid worker error"); }
            catch (IOException error) { check(error.InnerException?.Message == "manager failure", "Capture manager propagates read failure"); }
            manager.Stop();
            check(manager.Devices.Count == 0, "Stopped manager clears active devices");
        }
        check(owner.Count == 1, "Capture library ownership is released once");

        var source = new Source(() => null, new() { Received=uint.MaxValue, Dropped=2, InterfaceDropped=3 });
        using (var manager = new CaptureManager([First, Second], (device, _) => device == First
                   ? throw new IOException("unavailable device") : source, _ => { }))
        {
            check(manager.Devices.Select(row => row.Name).SequenceEqual([Second.Name]), "One unavailable device preserves successful devices");
            check(manager.Statistics() == new CaptureStatistics(uint.MaxValue,2,3), "Statistics preserve unsigned native counters");
        }
        check(source.CloseCount == 1, "Manager closes unstarted successful device");

        var reopened = new List<Source>();
        var filters = new List<string>();
        using AutoResetEvent pulse = new(false);
        ICaptureSource Open(DeviceInfo device, string filter)
        {
            filters.Add(device.Name+":"+filter);
            var item = new Source(() => { pulse.WaitOne(5); return null; });
            reopened.Add(item);
            return item;
        }
        using (var manager = new CaptureManager([First, Second], Open, _ => { }))
        {
            manager.Start();
            manager.LockToFlow(new(new("192.0.2.2",30001), new("203.0.113.10",30000)), new HashSet<string> { First.Name });
            check(manager.Devices.Count == 1 && manager.Devices[0] == Second, "Exact client IP takes precedence over observed device");
            check(reopened.Take(2).All(item => item.CloseCount == 1), "Locking capture releases discovery handles");
            manager.RestoreDiscovery();
            check(manager.Devices.Count == 2 && filters.Skip(3).All(row => row.EndsWith(DeviceSelection.DiscoveryFilter, StringComparison.Ordinal)),
                "Discovery restores original devices and filter");
        }
        check(reopened.Count == 5 && reopened.All(item => item.CloseCount == 1), "Every replaced capture closes exactly once");
    }
}
