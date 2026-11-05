using System.Diagnostics;
using System.Collections.Concurrent;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Runtime.Vision;

internal static class VisionSpecs
{
    private static string Status(EvidenceObject value) => ((EvidenceText)value.Get("status")).Value;
    private static EvidenceObject[] Slots(EvidenceObject value) => ((EvidenceArray)value.Get("slots")).Items.Cast<EvidenceObject>().ToArray();
    public static void Run(Action<bool, string> check)
    {
        VisionSlotTracker tracker = new();
        check(Status(tracker.Payload(0)) == "unknown", "A visual slot starts unknown without inventing ready/cooldown evidence");
        for (var at = 0; at < 21; at++) tracker.Feed(new(true, .1 + at * .05 * .1), at * .05, at);
        var estimate = tracker.Payload(1);
        check(estimate.Get("estimated_remaining_ms") is EvidenceReal { Value: > 7000 and < 9000 }, "Sustained observed progress establishes a remaining-time estimate");
        tracker.Invalid(2); var held = tracker.Payload(2);
        check(held.Get("held") is EvidenceBoolean { Value: true } && held.Get("progress") is EvidenceReal { Value: > .2 and < .4 },
            "Unreadable frames retain and advance a previously established estimate");
        check(Status(tracker.Payload(50)) == "ready", "A held established estimate reaches ready without requiring fabricated raw observations");
        tracker.Feed(new(true, .1), 51, 100); var jump = tracker.Feed(new(true, .05), 51.1, 101);
        check(jump.Get("estimated_remaining_ms") is EvidenceNull, "Reverse progress invalidates velocity immediately");
        var ready = tracker.Feed(new(true, 1, Ready: true), 52, 102); tracker.Feed(new(false), 52.1, 103);
        check(Status(tracker.Payload(52.1)) == "ready", "Ambiguous dimming cannot consume a latched ready state");
        var dead = tracker.Feed(new(true, null, Dead: true), 53, 104);
        check(Status(dead) == "dead" && dead.Get("progress") is EvidenceNull, "A death observation remains distinct from cooldown and an empty slot");

        const int width = 512, height = 288; byte[] bytes = new byte[width * height * 4]; Array.Fill(bytes, (byte)30);
        var pixels = new VisionPixels(bytes, width, height, width * 4); PixelArea client = new(0, 0, width, height);
        var regions = VisionLayout.Presets().Single(row => row.Name == "keyboard").Regions;
        void Paint(HudRegion rect, byte a, byte b, byte c)
        {
            var x = (int)Math.Round(rect.X * width); var y = (int)Math.Round(rect.Y * height); var endX = (int)Math.Round((rect.X + rect.Width) * width); var endY = (int)Math.Round((rect.Y + rect.Height) * height);
            for (var row = y; row < Math.Max(y + 1, endY); row++) for (var col = x; col < Math.Max(x + 1, endX); col++)
            { var at = row * width * 4 + col * 4; bytes[at] = a; bytes[at + 1] = b; bytes[at + 2] = c; }
        }
        foreach (var region in regions) { Paint(region.Energy, 235, 235, 235); Paint(region.Hp, 30, 150, 210); Paint(region.Portrait, 40, 40, 40); }
        VisionEngine engine = new(); var initial = engine.Analyze(pixels, client, 0, 0); var confirmed = engine.Analyze(pixels, client, .1, 1);
        check(initial.Get("frame_valid") is EvidenceBoolean { Value: false } && Status(initial) == "确认布局中"
            && confirmed.Get("frame_valid") is EvidenceBoolean { Value: true } && Slots(confirmed).All(row => Status(row) == "ready"),
            "Two supported frames establish the layout before publishing four recognized slots");
        foreach (var region in regions.Skip(1)) { Paint(region.Energy, 0, 0, 0); Paint(region.Hp, 0, 0, 0); }
        var obscured = engine.Analyze(pixels, client, .2, 2);
        check(obscured.Get("frame_valid") is EvidenceBoolean { Value: true } && Slots(obscured).Skip(1).All(row => row.Get("held") is EvidenceBoolean { Value: true }),
            "A confirmed geometry can update one visible slot while retaining obscured slots");
        var stale = engine.Invalid(2, "画面未更新");
        check(stale.Get("frame_valid") is EvidenceBoolean { Value: false } && Slots(stale).All(row => row.Get("stale") is EvidenceBoolean { Value: true }),
            "Missing frames publish explicit invalid/stale state rather than silently discarding the last slot evidence");
        check(VisionLayout.GameArea(new(new byte[400], 10, 10, 40), new(0, 0, 10, 10)) == new PixelArea(0, 0, 10, 10),
            "A completely dark image does not manufacture a different viewport");
        check(VisionConfiguration.Normalize(EvidenceJson.Parse("""{"layout":"custom","regions":[{}, {}, {}, {}]}""")).Regions.Count == 0,
            "Incomplete custom calibration does not become valid four-slot geometry");
    }
    private sealed class Capture : IVisionCaptureBackend
    {
        private readonly object gate = new();
        public readonly ConcurrentQueue<long?> Targets = new();
        public volatile bool Disposed;
        public long? Foreground = 123;
        public long[] Windows = [123, 456];
        public Action? Acquired;
        private VisionCaptureFrame? frame;
        public VisionTargets Discover(string executable) => new(Windows, Foreground);
        public void SetTarget(long? window) => Targets.Enqueue(window);
        public VisionCaptureFrame? AcquireLatest()
        {
            VisionCaptureFrame? value; lock (gate) { value = frame; frame = null; }
            if (value is not null) Acquired?.Invoke(); return value;
        }
        public void Offer(long window, long token, Action released)
        {
            const int width = 512, height = 288; byte[] pixels = new byte[width * height * 4];
            Array.Fill(pixels, (byte)30);
            foreach (var row in VisionLayout.Presets().Single(row => row.Name == "keyboard").Regions)
            {
                void Fill(HudRegion rect, byte a, byte b, byte c)
                {
                    var left = (int)Math.Round(rect.X * width); var top = (int)Math.Round(rect.Y * height);
                    for (var y = top; y < Math.Max(top + 1, (int)Math.Round((rect.Y + rect.Height) * height)); y++)
                        for (var x = left; x < Math.Max(left + 1, (int)Math.Round((rect.X + rect.Width) * width)); x++)
                        { var at = (y * width + x) * 4; pixels[at] = a; pixels[at + 1] = b; pixels[at + 2] = c; }
                }
                Fill(row.Energy, 235, 235, 235); Fill(row.Hp, 30, 150, 210); Fill(row.Portrait, 40, 40, 40);
            }
            lock (gate)
            {
                frame?.Dispose(); frame = new(new(pixels, width, height, width * 4), new(0, 0, width, height), token,
                    Stopwatch.GetTimestamp() / (double)Stopwatch.Frequency, window, released);
            }
        }
        public void Dispose() { lock (gate) { frame?.Dispose(); frame = null; Disposed = true; } }
    }
    private static void Until(Func<bool> predicate)
    { var started = Stopwatch.GetTimestamp(); while (!predicate()) { if (Stopwatch.GetElapsedTime(started).TotalSeconds > 10) throw new TimeoutException("Visual worker did not reach its expected state"); Thread.Sleep(10); } }
    public static void Service(Action<bool, string> check)
    {
        ConcurrentQueue<Capture> created = new();
        IVisionCaptureBackend Factory() { Capture backend = new(); created.Enqueue(backend); return backend; }
        VisionService service = new(Factory, "missing-game.exe");
        try
        {
            check(!service.Running && created.IsEmpty, "Visual capture allocates no backend until a consumer enables it");
            service.SetEnabledAsync(true).GetAwaiter().GetResult(); Until(() => created.TryPeek(out var capture) && !capture.Targets.IsEmpty);
            created.TryPeek(out var backend); var capture = backend!; var released = 0;
            var targets = service.Targets;
            check(targets.Windows.SequenceEqual([123L, 456L]) && targets.Foreground == 123, "Calibration discovers game windows without another native capture owner");
            ((long[])targets.Windows)[0] = 999;
            check(service.Targets.Windows[0] == 123, "Target discovery returns an owned copy rather than exposing worker state");
            capture.Offer(999, 0, () => Interlocked.Increment(ref released)); Until(() => Volatile.Read(ref released) == 1);
            check(service.State.Get("frame_valid") is EvidenceBoolean { Value: false }, "A late frame for another window is released and cannot enter the current visual state");
            capture.Offer(123, 1, () => Interlocked.Increment(ref released)); Until(() => Status(service.State) == "确认布局中");
            capture.Offer(123, 2, () => Interlocked.Increment(ref released)); Until(() => service.State.Get("frame_valid") is EvidenceBoolean { Value: true });
            service.SetIdentity([new(0, "chr_0001_test", "测试角色")]);
            var snapshot = service.TakeSnapshot()!; var payload = (EvidenceObject)snapshot.Get("snapshot");
            check(Volatile.Read(ref released) == 3 && Slots(payload)[0].Get("character_key") is EvidenceText { Value: "chr_0001_test" }
                && snapshot.Get("source") is EvidenceText { Value: "vision" }, "Recognition disposes each acquired capture frame and merges explicit squad identities into schema-v2 snapshots");
            check(service.TakeSnapshot() is null && !payload.Fields.ContainsKey("diagnostics"), "Unchanged content and timing-only diagnostics do not produce redundant overlay snapshots");
            service.SetPreview(true); capture.Offer(123, 3, () => Interlocked.Increment(ref released));
            VisionPreview? preview = null; Until(() => (preview = service.TakePreview()) is not null);
            check(preview!.Width == 960 && preview.Height == 540 && preview.Bgra.Length == 960 * 540 * 4, "Preview is owned, bounded presentation data rather than a live native frame");
            Thread.Sleep(300); // Let the bounded 4 Hz preview sampler accept the deliberately blocked next frame.
            using ManualResetEventSlim acquired = new(), resume = new(), frameReleased = new();
            capture.Acquired = () => { acquired.Set(); if (!resume.Wait(TimeSpan.FromSeconds(5))) throw new TimeoutException("Preview race test was not released"); };
            capture.Offer(123, 30, () => { Interlocked.Increment(ref released); frameReleased.Set(); });
            try
            {
                if (!acquired.Wait(TimeSpan.FromSeconds(5))) throw new TimeoutException("Visual worker did not acquire the preview frame");
                service.SetPreview(false);
            }
            finally { resume.Set(); }
            if (!frameReleased.Wait(TimeSpan.FromSeconds(5))) throw new TimeoutException("Visual worker did not release the preview frame");
            capture.Acquired = null;
            check(service.TakePreview() is null && service.Running, "Disabling preview discards even an in-flight thumbnail while recognition remains enabled");
            service.SetPreview(true); capture.Offer(123, 31, () => Interlocked.Increment(ref released));
            Until(() => Volatile.Read(ref released) == 6);
            // Preview sampling is deliberately slower than recognition; do not depend on whether this frame produced a thumbnail.
            service.Configure(EvidenceJson.Parse("""{"layout":"keyboard","target_hwnd":456}""")); Until(() => capture.Targets.Contains(456));
            check(service.TakePreview() is null, "Changing calibration or target discards cached images from the previous configuration");
            capture.Offer(456, 4, () => Interlocked.Increment(ref released)); Until(() => Status(service.State) == "确认布局中");
            capture.Offer(456, 5, () => Interlocked.Increment(ref released)); Until(() => service.State.Get("frame_valid") is EvidenceBoolean { Value: true });
            snapshot = service.TakeSnapshot()!;
            check(Slots((EvidenceObject)snapshot.Get("snapshot")).All(row => row.Get("character_key") is EvidenceNull), "Changing the target window clears stale character identity and requires fresh geometry confirmation");
            service.SetEnabledAsync(false).GetAwaiter().GetResult();
            check(capture.Disposed && !service.Running && Status(service.State) == "已停止", "Disabling visual demand waits for native backend release without involving capture or input services");
            var stream = (EvidenceText)snapshot.Get("stream_id"); service.SetEnabledAsync(true).GetAwaiter().GetResult(); Until(() => created.Count == 2);
            check(service.TakeSnapshot()!.Get("stream_id") is EvidenceText restarted && restarted.Value != stream.Value, "Restarted visual capture has a distinct stream for sequence isolation");
        }
        finally { service.DisposeAsync().AsTask().GetAwaiter().GetResult(); }
        check(created.All(capture => capture.Disposed), "Disposing the visual service releases its final backend and worker");
    }
}
