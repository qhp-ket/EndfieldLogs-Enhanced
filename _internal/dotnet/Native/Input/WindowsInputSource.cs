using System.Buffers.Binary;
using System.ComponentModel;
using System.Diagnostics;
using System.Numerics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;

namespace EndfieldLogs.Native.Input;

/// <summary>Message-only window and passive low-level hook compatibility, owned by one message thread.</summary>
[SupportedOSPlatform("windows")]
public sealed class WindowsInputSource : IDisposable
{
    private readonly GameForeground target;
    private readonly Action<NativeInputReport> emit;
    private readonly InputStateSampler sampler;
    private readonly RawInputDecoder decoder;
    private readonly object gate = new();
    private readonly Queue<NativeInputReport> mailbox = new();
    private readonly Queue<NativeInputReport> hooksPending = new();
    private readonly Dictionary<(string Kind, string Code, string? Phase), long> rawTimes = [];
    private readonly HashSet<string> known = [], hookDevices = [];
    private readonly HashSet<uint> hookPressed = [];
    private readonly ManualResetEventSlim ready = new(), stop = new();
    private readonly Thread thread;
    private readonly WindowProc windowProc;
    private readonly HookProc keyboardProc, mouseProc;
    private nint window, keyboardHook, mouseHook, foreground;
    private Exception? failure;
    private long pumps, rawKeyboard, rawMouse, rawHid, acceptedKey, acceptedButton, acceptedMotion, acceptedWheel, filtered, dropped, dropStart, dropEnd;
    private bool disposed;
    public WindowsInputSource(string gameExecutable, Action<NativeInputReport> emit)
    {
        target = new(gameExecutable); this.emit = emit; sampler = new(Enqueue); decoder = new(Raw);
        windowProc = Message; keyboardProc = Keyboard; mouseProc = Mouse;
        thread = new(MessageLoop) { Name = "windows-input", IsBackground = true }; thread.Start();
        if (!ready.Wait(TimeSpan.FromSeconds(5))) { stop.Set(); throw new TimeoutException("Windows 输入线程启动超时"); }
        if (failure is { } error) { thread.Join(TimeSpan.FromSeconds(3)); throw new IOException("Windows 输入启动失败", error); }
    }
    public IReadOnlyDictionary<string, object?> Health => NativeInputReport.FieldsOf(("version", 2), ("message_thread_alive", thread.IsAlive),
        ("message_pumps", Interlocked.Read(ref pumps)), ("state_samples", sampler.Samples), ("raw_received", Received),
        ("foreground_received", NativeInputReport.FieldsOf(("key", Interlocked.Read(ref acceptedKey)), ("button", Interlocked.Read(ref acceptedButton)),
            ("motion", Interlocked.Read(ref acceptedMotion)), ("wheel", Interlocked.Read(ref acceptedWheel)))), ("foreground_filtered", Interlocked.Read(ref filtered)));
    public IReadOnlyDictionary<string, object?> Received => NativeInputReport.FieldsOf(("keyboard", Interlocked.Read(ref rawKeyboard)), ("mouse", Interlocked.Read(ref rawMouse)), ("hid", Interlocked.Read(ref rawHid)));
    public IReadOnlyList<string> FallbackDevices { get { lock (gate) return hookDevices.Concat(sampler.Announced).Distinct().Order(StringComparer.Ordinal).ToArray(); } }
    private static (long Mono, long Wall) Clock() => ((long)((BigInteger)Stopwatch.GetTimestamp() * 1_000_000_000 / Stopwatch.Frequency),
        (DateTime.UtcNow.Ticks - DateTime.UnixEpoch.Ticks) * 100);
    private bool Foreground() => Volatile.Read(ref foreground) is var handle && handle != 0 && GameForeground.GetForegroundWindow() == handle;
    private void Publish(NativeInputReport report)
    {
        var fields = report.Fields.ToDictionary(); var now = Clock(); fields.TryAdd("mono_ns", now.Mono); fields.TryAdd("wall_ns", now.Wall); report = new(report.Type, fields);
        if (report.Type == "input")
        {
            if (!Foreground()) { Interlocked.Increment(ref filtered); return; }
            sampler.Note(report);
            switch (fields.GetValueOrDefault("kind"))
            { case "key": Interlocked.Increment(ref acceptedKey); break; case "button": Interlocked.Increment(ref acceptedButton); break;
                case "motion": Interlocked.Increment(ref acceptedMotion); break; case "wheel": Interlocked.Increment(ref acceptedWheel); break; }
        }
        Enqueue(report);
    }
    private NativeInputReport Gap() => NativeInputReport.Create("gap", ("reason", "windows_input_overflow"), ("count", 1),
        ("missing_events", dropped), ("start_mono_ns", dropStart), ("end_mono_ns", dropEnd));
    private void Enqueue(NativeInputReport report)
    {
        var now = Clock();
        lock (gate)
        {
            if (mailbox.Count >= 32768) { if (dropped++ == 0) dropStart = now.Mono; dropEnd = now.Mono; return; }
            if (dropped > 0)
            {
                mailbox.Enqueue(Gap()); dropped = 0; dropStart = dropEnd = 0;
                if (mailbox.Count >= 32768) { dropped = 1; dropStart = dropEnd = now.Mono; return; }
            }
            mailbox.Enqueue(report);
        }
    }
    private void Raw(NativeInputReport report)
    {
        if (report.Type == "input" && Foreground()) rawTimes[Group(report)] = Clock().Mono;
        Publish(report);
    }
    private static (string Kind, string Code, string? Phase) Group(NativeInputReport report) => ((string)report.Fields["kind"]!, (string)report.Fields["code"]!, report.Fields.GetValueOrDefault("phase") as string);
    private void QueueHook(NativeInputReport report)
    {
        if (!Foreground()) return;
        var now = Clock(); var fields = report.Fields.ToDictionary(); fields["mono_ns"] = now.Mono; fields["wall_ns"] = now.Wall; report = new(report.Type, fields);
        if (hooksPending.Count >= 8192)
        { var lost = hooksPending.Count; hooksPending.Clear(); Publish(NativeInputReport.Create("gap", ("reason", "windows_fallback_overflow"), ("count", 1), ("missing_events", lost))); }
        hooksPending.Enqueue(report); sampler.Note(report);
    }
    private void DrainHooks()
    {
        var now = Clock().Mono;
        while (hooksPending.TryPeek(out var item) && now - (long)item.Fields["mono_ns"]! >= 60_000_000)
        {
            hooksPending.Dequeue(); var group = Group(item);
            if (rawTimes.TryGetValue(group, out var raw) && Math.Abs(raw - (long)item.Fields["mono_ns"]!) <= 120_000_000 || !Foreground()) continue;
            var device = group.Kind == "key" ? "windows:keyboard" : "windows:mouse"; bool announce;
            lock (gate) announce = hookDevices.Add(device);
            if (announce)
            {
                Publish(NativeInputReport.Create("device", ("device", device), ("backend", "windows_hook"), ("name", "Windows 输入（设备身份不可用）"), ("device_identity_available", false)));
                Publish(NativeInputReport.Create("diagnostic", ("reason", "raw_input_delivery_fallback"), ("device", device), ("message", "未收到对应 Raw Input 报告，使用 Windows 输入事件；无法区分物理设备")));
            }
            var fields = item.Fields.ToDictionary(); fields["device"] = device; fields["backend"] = "windows_hook"; fields["device_identity_available"] = false; Publish(new("input", fields));
        }
        foreach (var key in rawTimes.Where(p => now - p.Value > 1_000_000_000).Select(p => p.Key).ToArray()) rawTimes.Remove(key);
    }
    public void Pump()
    {
        ObjectDisposedException.ThrowIf(disposed, this);
        var active = target.Active; Volatile.Write(ref foreground, active ? target.Window : 0);
        var now = Clock(); sampler.Sample(now.Mono, now.Wall, active, vk => (GameForeground.ReadState(vk) & 0x8000) != 0);
        for (var i = 0; i < 32768; i++)
        { NativeInputReport? report; lock (gate) report = mailbox.TryDequeue(out var item) ? item : null; if (report is null) break; emit(report); }
        if (Volatile.Read(ref failure) is { } error) throw new IOException("Windows 输入后端失败", error);
    }
    private void MessageLoop()
    {
        var name = "EndfieldInput_" + Guid.NewGuid().ToString("N"); var instance = GetModuleHandle(null); var registered = false;
        try
        {
            WindowClass cls = new() { Proc = windowProc, Instance = instance, Name = name };
            if (RegisterClass(ref cls) == 0) throw new Win32Exception(); registered = true;
            window = CreateWindowEx(0, name, "", 0, 0, 0, 0, 0, -3, 0, instance, 0); if (window == 0) throw new Win32Exception();
            RawDevice[] devices = [new() { Page = 1, Usage = 6, Flags = 0x2100, Target = window }, new() { Page = 1, Usage = 2, Flags = 0x2100, Target = window }];
            if (!RegisterRawInputDevices(devices, 2, (uint)Marshal.SizeOf<RawDevice>())) throw new Win32Exception();
            try
            {
                keyboardHook = SetWindowsHookEx(13, keyboardProc, instance, 0); if (keyboardHook == 0) throw new Win32Exception();
                mouseHook = SetWindowsHookEx(14, mouseProc, instance, 0); if (mouseHook == 0) throw new Win32Exception();
            }
            catch (Exception error)
            {
                if (keyboardHook != 0) { UnhookWindowsHookEx(keyboardHook); keyboardHook = 0; }
                if (mouseHook != 0) { UnhookWindowsHookEx(mouseHook); mouseHook = 0; }
                Publish(NativeInputReport.Create("error", ("message", "键鼠事件兼容采集不可用：" + error.Message)));
            }
            ready.Set();
            while (!stop.IsSet)
            {
                var started = Stopwatch.GetTimestamp();
                while (Stopwatch.GetElapsedTime(started).TotalMilliseconds < 4 && PeekMessage(out var msg, 0, 0, 0, 1))
                { TranslateMessage(ref msg); DispatchMessage(ref msg); }
                Interlocked.Increment(ref pumps); DrainHooks(); MsgWaitForMultipleObjectsEx(0, 0, 50, 0x04ff, 4);
            }
        }
        catch (Exception error) { Volatile.Write(ref failure, error); }
        finally
        {
            if (keyboardHook != 0) UnhookWindowsHookEx(keyboardHook); if (mouseHook != 0) UnhookWindowsHookEx(mouseHook);
            if (window != 0) DestroyWindow(window); if (registered) UnregisterClass(name, instance); ready.Set();
        }
    }
    private string Device(nint handle)
    {
        var device = $"raw:{(nuint)handle:x}";
        if (known.Add(device))
        {
            uint size = 0; GetRawInputDeviceInfo(handle, 0x20000007, null, ref size);
            StringBuilder name = new(checked((int)size + 1)); GetRawInputDeviceInfo(handle, 0x20000007, name, ref size);
            Publish(NativeInputReport.Create("device", ("device", device), ("backend", "raw_input"), ("name", name.ToString())));
        }
        return device;
    }
    private nint Message(nint hwnd, uint message, nuint wParam, nint lParam)
    {
        try
        {
            if (message == 0xff)
            {
                uint size = 0; if (GetRawInputData(lParam, 0x10000003, null, ref size, 24) == uint.MaxValue) throw new Win32Exception();
                if (size != 0)
                {
                    byte[] data = new byte[size]; var got = GetRawInputData(lParam, 0x10000003, data, ref size, 24);
                    if (got == uint.MaxValue) throw new Win32Exception(); if (got < 24) throw new InvalidDataException("Raw Input 返回了不完整的报告头");
                    var type = BinaryPrimitives.ReadUInt32LittleEndian(data); var handle = (nint)BinaryPrimitives.ReadInt64LittleEndian(data.AsSpan(8));
                    if (type == 0) Interlocked.Increment(ref rawMouse); else if (type == 1) Interlocked.Increment(ref rawKeyboard); else Interlocked.Increment(ref rawHid);
                    decoder.Decode(type, Device(handle), data.AsSpan(24, checked((int)got - 24)));
                }
            }
            else if (message == 0xfe)
            {
                var device = Device(lParam); Publish(NativeInputReport.Create("device_change", ("device", device), ("connected", wParam == 1)));
                if (wParam == 2) { decoder.Disconnect(device); known.Remove(device); }
            }
        }
        catch (Exception error) { Volatile.Write(ref failure, error); }
        return DefWindowProc(hwnd, message, wParam, lParam);
    }
    private nint Keyboard(int code, nuint message, nint data)
    {
        try
        {
            if (code >= 0)
            {
                var item = Marshal.PtrToStructure<KeyboardData>(data); var up = message is 0x101 or 0x105; var repeat = !up && hookPressed.Contains(item.Vk);
                if (up) hookPressed.Remove(item.Vk); else hookPressed.Add(item.Vk);
                QueueHook(NativeInputReport.Create("input", ("kind", "key"), ("code", "K:" + RawInputDecoder.KeyCode((int)item.Vk)),
                    ("phase", up ? "up" : repeat ? "repeat" : "down"), ("value", up ? 0 : 1),
                    ("raw", NativeInputReport.FieldsOf(("vk", item.Vk), ("scan", item.Scan), ("flags", item.Flags), ("native_time_ms", item.Time), ("injected", (item.Flags & 0x10) != 0)))));
            }
        }
        catch (Exception error) { Volatile.Write(ref failure, error); }
        return CallNextHookEx(0, code, message, data);
    }
    private nint Mouse(int code, nuint message, nint data)
    {
        try
        {
            if (code >= 0)
            {
                var item = Marshal.PtrToStructure<MouseData>(data); var raw = NativeInputReport.FieldsOf(("flags", item.Flags), ("native_time_ms", item.Time), ("injected", (item.Flags & 1) != 0));
                if (message == 0x200)
                { raw["coordinate_space"] = "screen_absolute"; QueueHook(NativeInputReport.Create("input", ("kind", "motion"), ("code", "M:MOVE"), ("value", new[] { item.X, item.Y }), ("raw", raw))); }
                else if (message is 0x20a or 0x20e)
                    QueueHook(NativeInputReport.Create("input", ("kind", "wheel"), ("code", message == 0x20a ? "M:WHEEL" : "M:HWHEEL"), ("value", (short)(item.Data >> 16)), ("raw", raw)));
                else
                {
                    var (button, up) = message switch
                    { 0x201 => (1, false), 0x202 => (1, true), 0x204 => (2, false), 0x205 => (2, true), 0x207 => (3, false), 0x208 => (3, true), 0x20b => (3 + (int)(item.Data >> 16), false), 0x20c => (3 + (int)(item.Data >> 16), true), _ => (0, false) };
                    if (button != 0) QueueHook(NativeInputReport.Create("input", ("kind", "button"), ("code", "M:" + button), ("phase", up ? "up" : "down"), ("value", up ? 0 : 1), ("raw", raw)));
                }
            }
        }
        catch (Exception error) { Volatile.Write(ref failure, error); }
        return CallNextHookEx(0, code, message, data);
    }
    public void Dispose()
    {
        if (disposed) return; disposed = true; stop.Set();
        if (!thread.Join(TimeSpan.FromSeconds(3))) throw new IOException("Windows 输入线程未能结束");
        List<NativeInputReport> final; lock (gate) { final = mailbox.ToList(); mailbox.Clear(); if (dropped > 0) final.Add(Gap()); }
        foreach (var report in final) emit(report); ready.Dispose(); stop.Dispose();
    }
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] private delegate nint WindowProc(nint hwnd, uint message, nuint param, nint data);
    [UnmanagedFunctionPointer(CallingConvention.Winapi)] private delegate nint HookProc(int code, nuint message, nint data);
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct WindowClass
    { public uint Style; public WindowProc Proc; public int ClassExtra, WindowExtra; public nint Instance, Icon, Cursor, Background; public string? Menu; public string Name; }
    [StructLayout(LayoutKind.Sequential)] private struct RawDevice { public ushort Page, Usage; public uint Flags; public nint Target; }
    [StructLayout(LayoutKind.Sequential)] private struct MessageData { public nint Window; public uint Message; public nuint Param; public nint Data; public uint Time; public int X, Y; public uint Private; }
    [StructLayout(LayoutKind.Sequential)] private struct KeyboardData { public uint Vk, Scan, Flags, Time; public nuint Extra; }
    [StructLayout(LayoutKind.Sequential)] private struct MouseData { public int X, Y; public uint Data, Flags, Time; public nuint Extra; }
    [DllImport("kernel32.dll", EntryPoint = "GetModuleHandleW", CharSet = CharSet.Unicode)] private static extern nint GetModuleHandle(string? name);
    [DllImport("user32.dll", EntryPoint = "RegisterClassW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern ushort RegisterClass(ref WindowClass cls);
    [DllImport("user32.dll", EntryPoint = "UnregisterClassW", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool UnregisterClass(string name, nint instance);
    [DllImport("user32.dll", EntryPoint = "CreateWindowExW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern nint CreateWindowEx(uint extended, string cls, string title, uint style, int x, int y, int width, int height, nint parent, nint menu, nint instance, nint parameter);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool DestroyWindow(nint window);
    [DllImport("user32.dll", EntryPoint = "DefWindowProcW")] private static extern nint DefWindowProc(nint window, uint message, nuint param, nint data);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool RegisterRawInputDevices(RawDevice[] devices, uint count, uint size);
    [DllImport("user32.dll", SetLastError = true)] private static extern uint GetRawInputData(nint input, uint command, [Out] byte[]? data, ref uint size, uint headerSize);
    [DllImport("user32.dll", EntryPoint = "GetRawInputDeviceInfoW", CharSet = CharSet.Unicode)] private static extern uint GetRawInputDeviceInfo(nint input, uint command, StringBuilder? data, ref uint size);
    [DllImport("user32.dll", EntryPoint = "PeekMessageW")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool PeekMessage(out MessageData msg, nint window, uint min, uint max, uint flags);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool TranslateMessage(ref MessageData msg);
    [DllImport("user32.dll", EntryPoint = "DispatchMessageW")] private static extern nint DispatchMessage(ref MessageData msg);
    [DllImport("user32.dll")] private static extern uint MsgWaitForMultipleObjectsEx(uint count, nint handles, uint milliseconds, uint mask, uint flags);
    [DllImport("user32.dll", EntryPoint = "SetWindowsHookExW", SetLastError = true)] private static extern nint SetWindowsHookEx(int kind, HookProc proc, nint instance, uint thread);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool UnhookWindowsHookEx(nint hook);
    [DllImport("user32.dll")] private static extern nint CallNextHookEx(nint hook, int code, nuint message, nint data);
}
