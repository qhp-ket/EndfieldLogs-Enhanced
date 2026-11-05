using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;

namespace EndfieldLogs.Desktop.Windows;

/// <summary>Owns tray and hotkey registrations on the window dispatcher thread.</summary>
internal sealed class ShellIntegration : IDisposable
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] private struct IconData
    {
        internal int Size; internal nint Window; internal uint Id, Flags, Callback; internal nint Icon;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] internal string Tip;
        internal uint State, StateMask;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] internal string Info;
        internal uint Timeout;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 64)] internal string Title;
        internal uint InfoFlags; internal Guid Guid; internal nint BalloonIcon;
    }
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool Shell_NotifyIcon(uint message, ref IconData data);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern nint LoadIcon(nint instance, nint name);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] private static extern uint RegisterWindowMessage(string message);
    [DllImport("user32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool RegisterHotKey(nint handle, int id, uint modifiers, uint key);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool UnregisterHotKey(nint handle, int id);
    [DllImport("user32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool SetForegroundWindow(nint handle);
    private readonly Window window;
    private readonly Action restore, hide, toggle, overlays;
    private readonly Action? recording;
    private readonly Action<string> notify;
    private readonly HwndSource source;
    private readonly nint handle;
    private readonly uint taskbarCreated = RegisterWindowMessage("TaskbarCreated");
    private readonly Dictionary<int, (string Text, uint Mods, uint Key)> bindings = [];
    private const int TrayMessage = 0x8000 + 63, GuiId = 0xB101, OverlayId = 0xB100, RecordingId = 0xB102;
    private bool suspended;
    private bool disposed;
    internal bool TrayAvailable { get; private set; }
    internal int HotkeyCount => bindings.Count;
    internal ShellIntegration(Window window, Action restore, Action hide, Action toggle, Action overlays, Action<string> notify, Action? recording = null)
    {
        this.window = window; this.restore = restore; this.hide = hide; this.toggle = toggle; this.overlays = overlays; this.notify = notify;
        this.recording = recording;
        handle = new WindowInteropHelper(window).Handle; source = HwndSource.FromHwnd(handle) ?? throw new InvalidOperationException("主窗口句柄尚未创建");
        source.AddHook(Hook); AddIcon();
    }
    private IconData Icon() => new() { Size = Marshal.SizeOf<IconData>(), Window = handle, Id = 1, Flags = 1 | 2 | 4, Callback = TrayMessage, Icon = LoadIcon(0, (nint)32512), Tip = "Endfield Logs - Enhanced", Info = "", Title = "" };
    private void AddIcon() { var data = Icon(); TrayAvailable = Shell_NotifyIcon(0, ref data); }
    internal static (uint Modifiers, uint Key)? Parse(string text)
    {
        try
        {
            // Qt's portable names for punctuation differ from WPF KeyConverter names.
            var aliases = new Dictionary<string, Key>(StringComparer.OrdinalIgnoreCase) { ["-"] = Key.OemMinus, ["="] = Key.OemPlus, [","] = Key.OemComma, ["."] = Key.OemPeriod, ["/"] = Key.OemQuestion, [";"] = Key.OemSemicolon, ["'"] = Key.OemQuotes, ["["] = Key.OemOpenBrackets, ["]"] = Key.OemCloseBrackets, ["\\"] = Key.OemBackslash, ["`"] = Key.OemTilde, ["Esc"] = Key.Escape, ["Return"] = Key.Return };
            var parts = text.Split('+', StringSplitOptions.TrimEntries); if (parts.Length == 0) return null; uint modifiers = 0;
            foreach (var part in parts[..^1]) modifiers |= part.ToLowerInvariant() switch { "ctrl" or "control" => 2u, "alt" => 1u, "shift" => 4u, "win" or "meta" => 8u, _ => throw new FormatException() };
            var key = aliases.TryGetValue(parts[^1], out var alias) ? alias : (Key)new KeyConverter().ConvertFromInvariantString(parts[^1])!;
            var vk = KeyInterop.VirtualKeyFromKey(key); return vk > 0 && key is not (Key.LeftCtrl or Key.RightCtrl or Key.LeftAlt or Key.RightAlt or Key.LeftShift or Key.RightShift or Key.LWin or Key.RWin) ? (modifiers, (uint)vk) : null;
        }
        catch (Exception error) when (error is NotSupportedException or FormatException or ArgumentException) { return null; }
    }
    internal void Configure(string gui, string overlay, string record = "Ctrl+I")
    { if (!disposed && !suspended) { Bind(GuiId, gui, "主窗口"); Bind(OverlayId, overlay, "悬浮窗"); if (recording is not null) Bind(RecordingId, record, "记录"); } }
    internal void SuspendHotkeys(bool active)
    {
        suspended = active;
        if (active) { foreach (var id in bindings.Keys) UnregisterHotKey(handle, id); bindings.Clear(); }
    }
    private void Bind(int id, string text, string label)
    {
        if (bindings.TryGetValue(id, out var previous) && previous.Text == text) return;
        var parsed = Parse(text); if (parsed is null) { notify(label + "快捷键格式无效：" + text); return; }
        if (bindings.ContainsKey(id)) UnregisterHotKey(handle, id);
        if (RegisterHotKey(handle, id, parsed.Value.Modifiers | 0x4000, parsed.Value.Key)) bindings[id] = (text, parsed.Value.Modifiers, parsed.Value.Key);
        else
        {
            bindings.Remove(id);
            if (previous.Text is not null && RegisterHotKey(handle, id, previous.Mods | 0x4000, previous.Key)) bindings[id] = previous;
            notify(label + "快捷键冲突：" + text);
        }
    }
    private nint Hook(nint hwnd, int message, nint wParam, nint lParam, ref bool handled)
    {
        if (disposed) return 0;
        if ((uint)message == taskbarCreated) { AddIcon(); return 0; }
        if (message == 0x0312 && bindings.ContainsKey((int)wParam))
        { handled = true; if ((int)wParam == GuiId) toggle(); else if ((int)wParam == RecordingId) recording?.Invoke(); else overlays(); }
        else if (message == TrayMessage)
        {
            if ((int)lParam is 0x0202 or 0x0203) restore();
            else if ((int)lParam is 0x0205 or 0x007b)
            {
                ContextMenu menu = new();
                void Item(string title, Action action) { MenuItem entry = new() { Header = title }; entry.Click += (_, _) => action(); menu.Items.Add(entry); }
                Item("显示主界面", restore); Item("隐藏主界面", hide); Item("隐藏／恢复浮窗", overlays); menu.Items.Add(new Separator()); Item("退出程序", window.Close);
                SetForegroundWindow(handle); menu.Placement = System.Windows.Controls.Primitives.PlacementMode.MousePoint; menu.IsOpen = true;
            }
            handled = true;
        }
        return 0;
    }
    public void Dispose()
    {
        if (disposed) return; disposed = true; source.RemoveHook(Hook);
        foreach (var id in bindings.Keys) UnregisterHotKey(handle, id); bindings.Clear();
        var data = Icon(); Shell_NotifyIcon(2, ref data); TrayAvailable = false;
    }
}
