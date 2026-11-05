using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Desktop.Vision;
using EndfieldLogs.Native.Windows;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Real product windows and drawing with synthetic snapshots. WGC observes only this process's overlays.</summary>
internal static partial class OverlayProductProbe
{
    [DllImport("user32.dll")] private static extern nint SendMessage(nint hwnd, int msg, nint wParam, nint lParam);
    [DllImport("user32.dll")] private static extern uint GetGuiResources(nint process, uint flags);
    private static EvidenceObject Object(string value) => (EvidenceObject)EvidenceJson.Parse(value);
    internal static EvidenceObject Summary(string stream, int sequence, int damage = 300) => Object($$$$"""
        {"type":"analysis_summary","schema_version":1,"stream_id":"{{{{stream}}}}","sequence":{{{{sequence}}}},"snapshot":{
        "battle":{"total_damage":{{{{damage}}}},"total_dps":150,"duration_ms":2000},
        "participants":[{"character_key":"chr_0001_test","character_name":"角色甲（长名称）","total_damage":200,"total_rd":80,"crit_rate":0.5},
        {"character_key":"chr_0002_test","character_name":"角色乙","total_damage":100,"total_rd":220,"crit_rate":0}],
        "quality_summary":{"status":"verified","rdps":{"status":"verified","reasons":[]},"timing":{"status":"verified","reasons":[]} } } }
        """);
    internal static EvidenceObject Combo(string stream, int sequence) => Object($$$$"""
        {"type":"combo_snapshot","schema_version":2,"stream_id":"{{{{stream}}}}","sequence":{{{{sequence}}}},"snapshot":{"status":"观测中","slots":[
        {"slot":0,"character_key":"chr_0001_test","display_name":"角色甲","status":"ready","progress":1},
        {"slot":1,"display_name":"角色乙","status":"cooldown","progress":0.45,"estimated_remaining_ms":12500,"held":true},
        {"slot":2,"status":"dead"},{"slot":3,"status":"empty"}]}}
        """);
    private static void SaveCanvas(OverlayCanvas canvas, string path)
    {
        var bitmap = new RenderTargetBitmap((int)Math.Ceiling(canvas.ActualWidth), (int)Math.Ceiling(canvas.ActualHeight), 96, 96, PixelFormats.Pbgra32);
        OverlayCanvasReference.Render(bitmap, canvas); PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(bitmap)); using var output = File.Create(path); encoder.Save(output);
    }
    internal static void VerifyAppearance(string root, string output, Action<string, bool> check)
    {
        foreach (var module in new[] { "damage", "combo_skill" })
        {
            var entry = new OverlaySettings { Theme = "dark", SourceValue = module };
            var skin = NativeSkins.Builtin(module);
            OverlayWindow window = new(entry, skin, new AvatarCache(root), _ => { });
            try
            {
                window.Show(); window.Canvas.Receive(Summary("appearance", 1)); window.Canvas.Receive(Combo("appearance", 1)); window.UpdateLayout();
                var original = window.Canvas.Arranged.Single().Layout.Hits.Select(hit => hit.Text).ToArray();
                foreach (var mode in new[] { "dark", "light" })
                {
                    window.Canvas.Apply(entry with { Theme = mode }, skin); window.UpdateLayout();
                    var canvas = window.Canvas;
                    var bitmap = new RenderTargetBitmap((int)Math.Ceiling(canvas.ActualWidth), (int)Math.Ceiling(canvas.ActualHeight), 96, 96, PixelFormats.Pbgra32); OverlayCanvasReference.Render(bitmap, canvas);
                    var stride = bitmap.PixelWidth * 4; byte[] pixels = new byte[stride * bitmap.PixelHeight]; bitmap.CopyPixels(pixels, stride, 0);
                    var palette = new OverlayPalette(Object($$"""{"theme":"{{mode}}"}"""), Object("{}"));
                    var color = ((SolidColorBrush)palette["background"]).Color;
                    var backgroundPixels = 0; var textPixels = 0;
                    for (var index = 0; index < pixels.Length; index += 4)
                    {
                        if (pixels[index + 3] != 255) continue;
                        if (pixels[index] == color.B && pixels[index + 1] == color.G && pixels[index + 2] == color.R) backgroundPixels++;
                        if (mode == "dark" ? pixels[index] > 210 && pixels[index + 1] > 210 && pixels[index + 2] > 210
                            : pixels[index] < 100 && pixels[index + 1] < 100 && pixels[index + 2] < 100) textPixels++;
                    }
                    check(mode + "_" + module + "_overlay_contrast", backgroundPixels > 100 && textPixels > 30);
                    check(mode + "_" + module + "_overlay_evidence_retained", original.SequenceEqual(canvas.Arranged.Single().Layout.Hits.Select(hit => hit.Text)));
                    if (module == "combo_skill")
                    {
                        var ready = canvas.Arranged.Single().Layout.Hits[0].Area; var scale = canvas.ActualHeight / canvas.NaturalSize.Height;
                        var index = (int)((ready.Y + ready.Height - 8) * scale) * stride + (int)((ready.X + 8) * scale) * 4;
                        check(mode + "_combo_ready_background_green", pixels[index + 1] > pixels[index + 2] + 20 && pixels[index + 1] > pixels[index] + 10);
                    }
                    SaveCanvas(canvas, Path.ChangeExtension(output, "." + mode + "-" + module + ".png"));
                }
            }
            finally { window.DisposeWindow(); }
        }
    }
    internal static void WriteImage(string path)
    {
        byte[] pixels = new byte[16 * 16 * 4];
        for (var i = 0; i < pixels.Length; i += 4) { pixels[i] = 180; pixels[i + 1] = 90; pixels[i + 2] = 35; pixels[i + 3] = 255; }
        var bitmap = BitmapSource.Create(16, 16, 96, 96, PixelFormats.Bgra32, null, pixels, 16 * 4);
        PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(bitmap)); using var stream = File.Create(path); encoder.Save(stream);
    }
    internal static int Run(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        var temporary = Directory.CreateTempSubdirectory("endfield-wpf-overlays-");
        Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
        SettingsContext context = new(temporary.FullName); SettingsCodec codec = new(context);
        var portraits = Path.Combine(temporary.FullName, "_internal", "data", "ui", "characters"); Directory.CreateDirectory(portraits);
        WriteImage(Path.Combine(portraits, "portrait.png")); WriteImage(Path.Combine(portraits, "placeholder.png")); WriteImage(Path.Combine(temporary.FullName, "background.png"));
        File.WriteAllText(Path.Combine(portraits, "manifest.json"), """{"version":"synthetic","portraits":{"chr_0001_test":{"path":"portrait.png"}},"aliases":{"chr_0002_test":"chr_0001_test"}}""");
        var config = codec.Decode(Object("{}")) with { Overlays = [new() { Id = "damage", Theme = "endfield" }, new() { Id = "combo", SourceValue = "combo_skill", Name = "连携 CD" }, new() { Id = "uid", SourceValue = "uid_mask", Name = "UID 遮挡" }] };
        SettingsStore store = new(config, codec); List<string> diagnostics = []; using OverlayManager manager = new(store, diagnostics.Add);
        Window host = new() { Title = "Endfield Logs · 浮窗产品验证", Width = 840, Height = 660, Left = 20, Top = 20, Content = new OverlaysPage(store, manager, diagnostics.Add) };
        Dictionary<string, object?> results = []; var exit = 1;
        void Check(string key, bool valid) { results[key] = valid; if (!valid) throw new InvalidOperationException(key); }
        host.Loaded += async (_, _) =>
        {
            try
            {
                manager.Sync(); await Task.Delay(150);
                Check("three_native_product_windows", manager.Windows.Count == 3 && manager.Windows.Values.All(window => window.IsVisible));
                results["renderers"] = manager.Windows.ToDictionary(pair => pair.Key, pair => pair.Value.HardwareRendering ? "Direct2D hardware" : "Direct2D software fallback");
                Check("minimal_subscriptions", manager.Requirements.SetEquals(["analysis_summary", "combo_snapshot"]));
                var avatars = new AvatarCache(temporary.FullName);
                Check("portrait_cache_alias_and_unknown_identity", avatars.Get("chr_0002_test") is { PixelWidth: 16 } && ReferenceEquals(avatars.Get("chr_0001_test"), avatars.Get("chr_0001_test")) && avatars.Get("enemy") is null);
                manager.Receive(Summary("live-a", 1)); manager.Receive(Combo("vision-a", 1));
                foreach (var window in manager.Windows.Values) window.UpdateLayout();
                var damage = manager.Windows["damage"]; var combo = manager.Windows["combo"]; var uid = manager.Windows["uid"];
                var damageLayout = damage.Canvas.Arranged.Single().Layout;
                Check("damage_defaults_rdmg_sort", damageLayout.Hits[2].Text.StartsWith("角色乙", StringComparison.Ordinal));
                Check("exact_numeric_tooltip", damageLayout.Hits.Any(hit => hit.Text.Contains("220.00", StringComparison.Ordinal)));
                var revision = damage.Canvas.LayoutRevision;
                manager.Receive(Summary("live-a", 0, 999)); manager.Receive(Summary("live-a", 1));
                Check("stale_and_duplicate_no_repaint", damage.Canvas.LayoutRevision == revision);
                var historical = (EvidenceObject)Summary("unused", 1, 123).Get("snapshot");
                ((Dictionary<string, EvidenceValue>)historical.Fields)["timeline_events"] = new EvidenceArray([Object("""{"evidence":"only used by the analysis page"}""")]);
                manager.ShowHistory(historical, "合成历史");
                Check("history_overlay_receives_summary_without_raw_evidence", (manager.Feed.Damage?.Get("snapshot") as EvidenceObject)?.Get("timeline_events") is EvidenceNull
                    && historical.Get("timeline_events") is EvidenceArray { Items.Count: 1 }
                    && damage.Canvas.Arranged.Single().Layout.Hits.Any(hit => hit.Text.Contains("220.00", StringComparison.Ordinal)));
                manager.Receive(Summary("live-a", 2, 400));
                Check("history_not_replaced_by_live", (manager.Feed.Damage?.Get("source") as EvidenceObject)?.Get("label") is EvidenceText { Value: "合成历史" }
                    && ((manager.Feed.Damage?.Get("snapshot") as EvidenceObject)?.Get("battle") as EvidenceObject)?.Get("total_damage") is EvidenceInteger { Value: var total } && total == 123);
                manager.ReturnLive();
                Check("return_live_uses_latest", ((manager.Feed.Damage?.Get("snapshot") as EvidenceObject)?.Get("battle") as EvidenceObject)?.Get("total_damage") is EvidenceInteger { Value: var live } && live == 400);
                manager.Receive(Summary("live-b", 0, 500)); manager.Receive(Summary("live-a", 3, 999));
                Check("retired_stream_rejected", ((manager.Feed.Damage?.Get("snapshot") as EvidenceObject)?.Get("battle") as EvidenceObject)?.Get("total_damage") is EvidenceInteger { Value: var newest } && newest == 500);
                manager.Update("damage", entry => entry with { TemplateSettings = new(entry.TemplateSettings.Fields.ToDictionary(pair => pair.Key, pair => pair.Value)) });
                Check("combo_four_semantic_states", combo.Canvas.Arranged.Single().Layout.Hits.Take(4).Select(hit => hit.Text).Zip(new[] { "CD 就绪", "≈12.5s", "阵亡", "空位" }).All(pair => pair.First.Contains(pair.Second, StringComparison.Ordinal)));
                foreach (var window in manager.Windows.Values) window.UpdateLayout();
                var comboArea = combo.Canvas.Arranged.Single().Layout.Hits[0].Area;
                var comboScale = combo.Canvas.ActualHeight / combo.Canvas.NaturalSize.Height;
                var comboBitmap = new RenderTargetBitmap((int)combo.Canvas.ActualWidth, (int)combo.Canvas.ActualHeight, 96, 96, PixelFormats.Pbgra32); OverlayCanvasReference.Render(comboBitmap, combo.Canvas);
                byte[] readyPixel = new byte[4]; comboBitmap.CopyPixels(new Int32Rect((int)((comboArea.X + 8) * comboScale), (int)((comboArea.Y + comboArea.Height - 8) * comboScale), 1, 1), readyPixel, 4, 0);
                Check("ready_colors_entire_slot_green", readyPixel[1] > readyPixel[2] + 20 && readyPixel[1] > readyPixel[0] + 10);
                SaveCanvas(damage.Canvas, Path.ChangeExtension(output, ".damage.png")); SaveCanvas(combo.Canvas, Path.ChangeExtension(output, ".combo.png")); SaveCanvas(uid.Canvas, Path.ChangeExtension(output, ".uid.png"));
                VerifyClipRendering(output, Check);
                VerifyLayoutReuse(temporary.FullName, output, Check);
                var point = damage.PointToScreen(new(damage.ActualWidth / 2, damage.ActualHeight / 2));
                nint Packed(Point p) => (nint)(((int)p.Y & 0xffff) << 16 | ((int)p.X & 0xffff));
                Check("native_drag_hit_target", SendMessage(damage.Handle, 0x84, 0, Packed(point)) == 2);
                manager.Update("damage", entry => entry with { Locked = true, ClickThrough = true });
                var styles = (long)WindowInterop.GetWindowLong(damage.Handle, WindowInterop.ExtendedStyle);
                Check("clickthrough_noactivate_capture_style", (styles & WindowInterop.Transparent) != 0 && (styles & WindowInterop.NoActivate) != 0 && (styles & WindowInterop.ToolWindow) == 0);
                manager.Update("damage", entry => entry with { Locked = false, ClickThrough = false });
                damage.Width = 700; damage.Height = 300; damage.CommitGeometry();
                Check("geometry_persisted_on_commit", store.Current.Overlays.Single(entry => entry.Id == "damage").Geometry?.Width == 700 && File.Exists(context.DefaultPath));
                var second = new OverlaySettings { Id = "second", Name = "第二伤害浮窗", BarMode = "dps", Geometry = new(30, 40, 500, 240) };
                store.Update(current => current with { Overlays = [.. current.Overlays, second] }); manager.Sync(); manager.Windows["second"].UpdateLayout();
                Check("instance_settings_independent", manager.Windows["second"].Canvas.Arranged.Single().Layout.Hits[2].Text.StartsWith("角色甲", StringComparison.Ordinal)
                    && damage.Canvas.Arranged.Single().Layout.Hits[2].Text.StartsWith("角色乙", StringComparison.Ordinal));
                var skin = Path.Combine(temporary.FullName, "combined.json");
                File.WriteAllText(skin, """{"schema_version":2,"name":"组合","modules":[{"type":"damage"},{"type":"combo_skill"},{"type":"uid_mask"}],"layout":{"direction":"vertical"},"theme":{"background":"transparent","padding":4,"spacing":6,"image":"background.png"}}""");
                store.Update(current => current with { Overlays = [.. current.Overlays, new OverlaySettings { Id = "combined", Name = "组合", SourceType = "file", SourceValue = skin }] }); manager.Sync();
                var combined = manager.Windows["combined"]; combined.UpdateLayout();
                Check("combined_v2_skin_draws_three_modules", combined.Canvas.Arranged.Count == 3 && combined.Canvas.Arranged.Zip(combined.Canvas.Arranged.Skip(1)).All(pair => pair.First.Area.Bottom < pair.Second.Area.Top));
                SaveCanvas(combined.Canvas, Path.ChangeExtension(output, ".combined.png"));
                var originalHandle = combined.Handle;
                var editedSkin = File.ReadAllText(skin).Replace("\"vertical\"", "\"horizontal\"", StringComparison.Ordinal);
                File.WriteAllText(skin, editedSkin); File.SetLastWriteTimeUtc(skin, DateTime.UtcNow.AddSeconds(2)); manager.Sync(); combined.UpdateLayout();
                Check("edited_skin_reloads_in_same_window", combined.Handle == originalHandle && combined.Canvas.Arranged.Count == 3
                    && combined.Canvas.Arranged.Zip(combined.Canvas.Arranged.Skip(1)).All(pair => pair.First.Area.Right < pair.Second.Area.Left));
                Check("skin_reload_retains_snapshot", combined.Canvas.Arranged[0].Layout.Hits.Any(hit => hit.Text.Contains("角色乙", StringComparison.Ordinal)));
                manager.Update("combo", entry => NativeSkins.WithValue(entry, NativeSkins.Builtin("combo_skill"), "display_style", new EvidenceText("bars")));
                combo.UpdateLayout(); var barWidth = combo.Width;
                manager.Receive(Combo("vision", 100)); combo.UpdateLayout();
                Check("combo_bar_mode_preserves_window_width", combo.Canvas.Bars && Math.Abs(combo.Width - barWidth) < 1);
                damage.Close();
                Check("close_hides_keeps_hwnd", damage.IsVisible && WindowInterop.IsWindowVisible(damage.Handle) && !damage.DesktopVisible && store.Current.Overlays.Single(entry => entry.Id == "damage").Hidden);
                manager.Update("damage", entry => entry with { Hidden = false });
                Check("restore_same_window", ReferenceEquals(manager.Windows["damage"], damage) && damage.DesktopVisible);
                manager.Update("uid", entry => entry with { Hidden = true });
                manager.ToggleVisible();
                Check("bulk_hidden_state_saved", manager.Windows.Values.All(window => !window.DesktopVisible) && store.Current.OverlayRestoreIds.Contains("damage") && !store.Current.OverlayRestoreIds.Contains("uid"));
                manager.ToggleVisible();
                Check("bulk_restore_preserves_individually_hidden", damage.DesktopVisible && !uid.DesktopVisible && store.Current.OverlayRestoreIds.Count == 0);
                // This is a real WGC test, separate from screenshot rendering and HWND visibility.
                var capturePassed = false;
                try
                {
                using (WgcCaptureBackend capture = new())
                {
                    capture.SetTarget(damage.Handle); damage.UpdateLayout(); var normal = await Fingerprint(capture, imagePath: Path.ChangeExtension(output, ".gpu-visible.png"));
                    manager.Update("damage", entry => entry with { Hidden = true }); await Task.Delay(150);
                    manager.Receive(Summary("live-b", 1, 600));
                    var hidden = await Fingerprint(capture, normal.Hash, Path.ChangeExtension(output, ".gpu-hidden.png")); results["capture_samples"] = new { normal, hidden };
                    Check("wgc_pixels_survive_desktop_hidden", normal.Nonzero > 0 && hidden.Nonzero > normal.Nonzero * .8);
                    manager.Update("damage", entry => entry with { Hidden = false });
                }
                capturePassed = true;
                }
                catch (Exception error)
                {
                    // Keep the capture failure visible, but still run independent reset/disposal checks.
                    results["wgc_pixels_survive_desktop_hidden"] = false;
                    results["capture_error"] = error.ToString();
                }
                manager.Update("combo", entry => entry with { Enabled = false });
                Check("disable_removes_vision_requirement", !manager.Windows.ContainsKey("combo") && manager.Requirements.Contains("combo_snapshot")); // combined still needs vision
                manager.ClearLive();
                Check("capture_reset_clears_damage_only", manager.Feed.Damage?.Get("snapshot") is EvidenceNull && manager.Feed.Combo is not null);
                var handles = manager.Windows.Values.Select(window => window.Handle).ToArray(); manager.Dispose();
                Check("disposed_native_windows_destroyed", handles.All(handle => !WindowInterop.IsWindowVisible(handle)));
                void Cycle()
                {
                    var entry = new OverlaySettings { Theme = "dark" }; var skin = NativeSkins.Builtin("damage");
                    OverlayWindow trial = new(entry, skin, new AvatarCache(temporary.FullName), _ => { }); trial.Show(); trial.Canvas.Receive(Summary("cycle", 0)); trial.UpdateLayout(); trial.DisposeWindow();
                }
                for (var i = 0; i < 3; i++) Cycle();
                async Task Settle()
                {
                    GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
                    await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
                    await Task.Delay(300);
                    GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
                    await Task.Delay(100);
                }
                await Settle();
                using var process = Process.GetCurrentProcess();
                var beforeGdi = GetGuiResources(process.Handle, 0);
                List<uint[]> batches = [];
                List<uint> settled = [];
                for (var batch = 0; batch < 12; batch++)
                {
                    List<uint> samples = [];
                    for (var i = 0; i < 16; i++)
                    {
                        Cycle();
                        await System.Windows.Threading.Dispatcher.Yield(System.Windows.Threading.DispatcherPriority.ApplicationIdle);
                        await Task.Delay(30);
                        samples.Add(GetGuiResources(process.Handle, 0));
                    }
                    await Settle(); batches.Add(samples.ToArray()); settled.Add(GetGuiResources(process.Handle, 0));
                }
                var afterGdi = GetGuiResources(process.Handle, 0);
                results["gdi_cycles"] = new { cycles = 192, beforeGdi, afterGdi, batches, settled };
                // WPF releases render resources asynchronously: short in-flight batches
                // sample different phases of a bounded sawtooth. Compare settled envelopes
                // over two longer windows after warm-up, retaining every raw measurement.
                var earlier = settled.Skip(2).Take(5).ToArray(); var later = settled.Skip(7).Take(5).ToArray();
                Check("native_window_gdi_bounded", beforeGdi > 0 && settled.All(count => count > 0)
                    && later.Max() <= earlier.Max() && later.Min() <= earlier.Min());
                var beforeSurface = GetGuiResources(process.Handle, 0);
                for (var cycle = 0; cycle < 8; cycle++) { using LayeredSurface trial = new(); trial.Resize(160, 80); trial.Resize(320, 160); }
                var afterSurface = GetGuiResources(process.Handle, 0);
                results["native_surface_gdi"] = new { beforeSurface, afterSurface };
                Check("native_dib_and_dc_release_exactly", afterSurface == beforeSurface);
                Check("no_window_diagnostics", diagnostics.Count == 0);
                exit = capturePassed ? 0 : 1;
            }
            catch (Exception error) { results["error"] = error.ToString(); results["diagnostics"] = diagnostics; }
            finally
            {
                manager.Dispose(); results["all_windows_closed"] = manager.Windows.Count == 0;
                File.WriteAllText(output, JsonSerializer.Serialize(results, new JsonSerializerOptions { WriteIndented = true }));
                host.Close(); app.Shutdown(exit); temporary.Delete(true);
            }
        };
        host.Show(); return app.Run();
    }
    private sealed record CaptureSample(int Width, int Height, long Nonzero, string Hash);
    private static async Task<CaptureSample> Fingerprint(WgcCaptureBackend capture, string? previousHash = null, string? imagePath = null)
    {
        var watch = Stopwatch.StartNew();
        while (watch.Elapsed.TotalSeconds < 6)
        {
            using var frame = capture.AcquireLatest();
            if (frame is not null)
            {
                long nonzero = 0; using MemoryStream samples = new();
                for (var y = 2; y < frame.Pixels.Height; y += 5)
                    for (var x = 2; x < frame.Pixels.Width; x += 5)
                    {
                        var a = frame.Pixels.At(x, y, 0); var b = frame.Pixels.At(x, y, 1); var c = frame.Pixels.At(x, y, 2);
                        if (a + b + c > 30) nonzero++; samples.WriteByte(a); samples.WriteByte(b); samples.WriteByte(c);
                    }
                var hash = Convert.ToHexStringLower(SHA256.HashData(samples.ToArray()));
                if (nonzero > 0 && hash != previousHash)
                {
                    if (imagePath is not null)
                    {
                        var pixels = frame.Pixels;
                        var image = BitmapSource.Create(pixels.Width, pixels.Height, 96, 96, PixelFormats.Pbgra32, null, pixels.Data.ToArray(), pixels.Stride);
                        PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(image)); using var file = File.Create(imagePath); encoder.Save(file);
                    }
                    return new(frame.Pixels.Width, frame.Pixels.Height, nonzero, hash);
                }
            }
            await Task.Delay(30);
        }
        throw new TimeoutException("No overlay WGC frame");
    }
}
