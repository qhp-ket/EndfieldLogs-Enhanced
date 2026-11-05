using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Text;

namespace EndfieldLogs.Native.Input;

/// <summary>Read-only executable identity; never opens the target for memory access.</summary>
[SupportedOSPlatform("windows")]
public sealed class GameForeground(string executable)
{
    private readonly string path = Path.GetFullPath(executable);
    private readonly Dictionary<uint, (long Checked, bool Match)> cache = [];
    public nint Window { get; private set; }
    public bool Active
    {
        get { var window = GetForegroundWindow(); Window = IsTarget(window) ? window : 0; return Window != 0; }
    }
    public bool IsTarget(nint window)
    {
        if (window == 0) return false; GetWindowThreadProcessId(window, out var pid); if (pid == 0) return false;
        if (cache.TryGetValue(pid, out var known) && Stopwatch.GetElapsedTime(known.Checked).TotalSeconds < 1) return known.Match;
        var result = false; var process = OpenProcess(0x1000, false, pid);
        if (process != 0)
        {
            try { var length = 32768u; StringBuilder name = new((int)length); result = QueryFullProcessImageName(process, 0, name, ref length) && string.Equals(Path.GetFullPath(name.ToString()), path, StringComparison.OrdinalIgnoreCase); }
            finally { CloseHandle(process); }
        }
        if (cache.Count >= 256) cache.Clear(); cache[pid] = (Stopwatch.GetTimestamp(), result); return result;
    }
    public static IReadOnlyList<string> HeldKeys() => Enumerable.Range(0, 256).Where(vk => (ReadState(vk) & 0x8000) != 0)
        .Select(vk => "K:" + RawInputDecoder.KeyCode(vk)).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
    public static short ReadState(int vk) => GetAsyncKeyState(vk);
    [DllImport("user32.dll")] public static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint window, out uint pid);
    [DllImport("user32.dll")] private static extern short GetAsyncKeyState(int vk);
    [DllImport("kernel32.dll", SetLastError = true)] private static extern nint OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inherit, uint pid);
    [DllImport("kernel32.dll", EntryPoint = "QueryFullProcessImageNameW", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)] private static extern bool QueryFullProcessImageName(nint process, uint flags, StringBuilder name, ref uint size);
    [DllImport("kernel32.dll")] [return: MarshalAs(UnmanagedType.Bool)] private static extern bool CloseHandle(nint handle);
}
