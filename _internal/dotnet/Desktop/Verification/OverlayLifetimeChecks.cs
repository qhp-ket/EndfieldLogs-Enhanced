using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Windows;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Runtime.Configuration;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Bounded ownership checks with desktop-transparent, nonactivating product windows. No capture or input.</summary>
internal static class OverlayLifetimeChecks
{
    [DllImport("user32.dll")] private static extern nint GetForegroundWindow();
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(nint window, out uint process);
    [DllImport("user32.dll")] private static extern nint GetCapture();
    [DllImport("user32.dll")] private static extern bool IsWindow(nint window);
    private static OverlayGraphicsDevice? Graphics(OverlayManager manager) => (OverlayGraphicsDevice?)typeof(OverlayManager)
        .GetField("graphics", BindingFlags.NonPublic | BindingFlags.Instance)!.GetValue(manager);

    internal static int Run(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var temporary = Directory.CreateTempSubdirectory("endfield-overlay-lifetime-");
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        Dictionary<string, object?> checks = [];
        List<string> diagnostics = [];
        void Check(string name, bool value) { checks[name] = value; if (!value) throw new InvalidOperationException(name); }
        static bool ContentFills(Size size, Size natural)
        {
            var scale = Math.Min(size.Width / natural.Width, size.Height / natural.Height);
            return size.Width - natural.Width * scale < 1.01 && size.Height - natural.Height * scale < 1.01;
        }
        void InputUntouched(string phase)
        {
            GetWindowThreadProcessId(GetForegroundWindow(), out var process);
            Check(phase + "_no_activation_or_capture", process != Environment.ProcessId && GetCapture() == 0);
        }
        var exit = 1;
        try
        {
            InputUntouched("before");
            SettingsCodec codec = new(new(temporary.FullName));
            var settings = codec.Decode(new(new Dictionary<string, EndfieldLogs.Core.Compatibility.EvidenceValue>())) with
            {
                Overlays = [new() { Id = "damage", Enabled = false, Hidden = true, Theme = "dark" },
                    new() { Id = "mask", SourceValue = "uid_mask", Enabled = false, Hidden = true }],
            };
            SettingsStore store = new(settings, codec);
            using OverlayManager manager = new(store, diagnostics.Add);
            manager.Sync();
            Check("disabled_overlays_allocate_no_factories", Graphics(manager) is null && manager.Windows.Count == 0);
            manager.Receive(OverlayProductProbe.Summary("lifetime", 1));
            store.Update(current => current with { Overlays = current.Overlays.Select(entry => entry with { Enabled = true }).ToArray() });
            manager.Sync();
            var graphics = Graphics(manager)!;
            var windows = manager.Windows.Values.Select(window => window.Handle).ToArray();
            Check("enabled_instances_share_live_factories", windows.Length == 2 && graphics.Shapes.NativePointer != 0 && graphics.Text.NativePointer != 0);
            foreach (var window in manager.Windows.Values)
            {
                var styles = (long)WindowInterop.GetWindowLong(window.Handle, WindowInterop.ExtendedStyle);
                Check(window.Entry.Id + "_desktop_hidden_nonactivating_input_transparent", window.IsVisible && !window.DesktopVisible
                    && (styles & WindowInterop.NoActivate) != 0 && (styles & WindowInterop.Transparent) != 0);
            }
            InputUntouched("enabled");
            var expected = manager.Windows["damage"].Canvas.Arranged.Single().Layout.Hits.ToArray();
            manager.Update("mask", entry => entry with { Enabled = false });
            Check("remaining_window_keeps_shared_factories", manager.Windows.Count == 1 && ReferenceEquals(Graphics(manager), graphics)
                && graphics.Shapes.NativePointer != 0 && graphics.Text.NativePointer != 0);
            manager.Update("damage", entry => entry with { Enabled = false });
            Check("last_disabled_window_releases_factories", manager.Windows.Count == 0 && Graphics(manager) is null
                && graphics.Shapes.NativePointer == 0 && graphics.Text.NativePointer == 0);
            Check("disabled_hwnds_destroyed_and_demand_released", windows.All(window => !IsWindow(window)) && manager.Requirements.Count == 0);
            InputUntouched("disabled");
            manager.Update("damage", entry => entry with { Enabled = true });
            var resumed = Graphics(manager)!;
            Check("reenable_creates_new_factories_and_restores_snapshot", !ReferenceEquals(resumed, graphics) && resumed.Shapes.NativePointer != 0
                && manager.Windows["damage"].Canvas.Arranged.Single().Layout.Hits.SequenceEqual(expected)
                && manager.Requirements.SetEquals(["analysis_summary"]));
            manager.Windows["damage"].UpdateLayout();
            InputUntouched("resumed");
            foreach (var (module, style) in new[] { ("damage", ""), ("combo_skill", "circles"), ("combo_skill", "bars"), ("uid_mask", "") })
            {
                manager.Update("damage", entry => entry with { SourceValue = module,
                    TemplateSettings = (EndfieldLogs.Core.Compatibility.EvidenceObject)EndfieldLogs.Core.Compatibility.EvidenceJson.Parse(
                        "{\"display_style\":\"" + style + "\"}") });
                var window = manager.Windows["damage"]; var natural = window.Canvas.NaturalSize;
                bool Fitted() => ContentFills(new(window.Width, window.Height), natural);
                Check(module + style + "_initial_content_ratio", Fitted());
                window.Width *= .9; window.UpdateLayout();
                Check(module + style + "_width_resize_content_ratio", Fitted());
                window.Height *= 1.1; window.UpdateLayout();
                Check(module + style + "_height_resize_content_ratio", Fitted());
                foreach (var edge in Enumerable.Range(1, 8))
                {
                    var size = OverlayWindow.ConstrainSize(new(window.Width + 35, window.Height + 20),
                        new(window.Width, window.Height), natural, edge, 80, 36);
                    Check(module + style + "_edge_" + edge + "_content_ratio",
                        ContentFills(size, natural));
                }
                InputUntouched(module + style);
            }
            manager.Windows["damage"].Close();
            Check("close_to_hide_retains_capture_window_and_factories", manager.Windows["damage"].IsVisible
                && ReferenceEquals(resumed, Graphics(manager)) && resumed.Shapes.NativePointer != 0);
            manager.Dispose();
            Check("dispose_releases_recreated_factories", Graphics(manager) is null && manager.Windows.Count == 0
                && resumed.Shapes.NativePointer == 0 && resumed.Text.NativePointer == 0);
            InputUntouched("disposed");
            Check("no_diagnostics", diagnostics.Count == 0);
            checks["passed"] = true; exit = 0;
        }
        catch (Exception error) { checks["error"] = error.ToString(); checks["passed"] = false; }
        finally
        {
            checks["scope"] = "Ownership only; desktop alpha zero; no input, capture, forced GC or sustained benchmark. Does not prove active-overlay memory target.";
            checks["assembly_sha256"] = Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(typeof(OverlayLifetimeChecks).Assembly.Location)));
            File.WriteAllText(output, JsonSerializer.Serialize(checks, new JsonSerializerOptions { WriteIndented = true }));
            app.Shutdown(); temporary.Delete(true);
        }
        return exit;
    }
}
