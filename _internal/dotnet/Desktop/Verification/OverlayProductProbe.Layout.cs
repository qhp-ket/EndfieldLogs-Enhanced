using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.Overlays;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class OverlayProductProbe
{
    internal static int RunLayouts(string output)
    {
        output = Path.GetFullPath(output); Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        Dictionary<string, object?> checks = [];
        try
        {
            VerifyLayoutReuse(ProductApplication.ResolveRoot(), output, (name, valid) =>
            { checks[name] = valid; if (!valid) throw new InvalidOperationException(name); });
            checks["passed"] = true;
        }
        catch (Exception error) { checks["error"] = error.ToString(); checks["passed"] = false; }
        File.WriteAllText(output, JsonSerializer.Serialize(checks, new JsonSerializerOptions { WriteIndented = true }));
        return checks["passed"] is true ? 0 : 1;
    }
    private static void VerifyLayoutReuse(string root, string output, Action<string, bool> check)
    {
        AvatarCache avatars = new(root);
        var skin = NativeSkins.Parse(EvidenceJson.Parse("""
            {"schema_version":2,"name":"组合布局验证","modules":[{"type":"damage"},{"type":"combo_skill"},{"type":"uid_mask"}],"layout":{"direction":"vertical"},"theme":{"padding":4,"spacing":6}}
            """));
        var entry = new OverlaySettings();
        var damage = Summary("layout", 1); var combo = Combo("layout", 1);
        var canvas = new OverlayCanvas(avatars).Apply(entry, skin);
        canvas.Receive(damage); canvas.Receive(combo); canvas.ArrangeSurface(new(800, 650));
        var previous = canvas.Arranged.Select(item => item.Layout).ToArray();
        damage = Summary("layout", 2, 1234567); canvas.Receive(damage);
        check("summary_updates_damage_retains_vision_and_mask_layout", !ReferenceEquals(previous[0], canvas.Arranged[0].Layout)
            && ReferenceEquals(previous[1], canvas.Arranged[1].Layout) && ReferenceEquals(previous[2], canvas.Arranged[2].Layout)
            && canvas.Arranged[0].Layout.Hits[1].Text.Contains("1,234,567", StringComparison.Ordinal));
        previous = canvas.Arranged.Select(item => item.Layout).ToArray();
        combo = Object("""
            {"type":"combo_snapshot","stream_id":"layout","sequence":2,"snapshot":{"status":"重新观测","slots":[
            {"slot":0,"display_name":"更长的角色名称","status":"cooldown","progress":0.25,"estimated_remaining_ms":9000},
            {"slot":1,"status":"ready","progress":1},{"slot":2,"status":"unknown"},{"slot":3,"status":"empty"}]}}
            """);
        canvas.Receive(combo);
        check("vision_updates_slots_retains_damage_and_mask_layout", ReferenceEquals(previous[0], canvas.Arranged[0].Layout)
            && !ReferenceEquals(previous[1], canvas.Arranged[1].Layout) && ReferenceEquals(previous[2], canvas.Arranged[2].Layout)
            && canvas.Arranged[1].Layout.Hits[0].Text.Contains("25%", StringComparison.Ordinal));
        previous = canvas.Arranged.Select(item => item.Layout).ToArray();
        check("identical_snapshot_keeps_all_module_layouts", !canvas.Receive(combo)
            && previous.SequenceEqual(canvas.Arranged.Select(item => item.Layout), ReferenceEqualityComparer.Instance));
        canvas.SetConnected(false);
        check("disconnect_refreshes_visible_connection_status", !ReferenceEquals(canvas.Arranged[0].Layout, previous[0])
            && !ReferenceEquals(canvas.Arranged[1].Layout, previous[1]));
        // Compare every cached layout and hit with a newly configured canvas after each invalidation.
        void Fresh(string name, OverlaySettings settings, NativeSkin nextSkin, double dpi, Size size, bool connected = true)
        {
            var expected = new OverlayCanvas(avatars).Apply(settings, nextSkin);
            expected.SetDpi(dpi); expected.Receive(damage); expected.Receive(combo); expected.SetConnected(connected); expected.ArrangeSurface(size);
            check(name, canvas.NaturalSize == expected.NaturalSize && canvas.Arranged.Count == expected.Arranged.Count
                && canvas.Arranged.Zip(expected.Arranged).All(pair =>
                pair.First.Area == pair.Second.Area && pair.First.Layout.Size == pair.Second.Layout.Size
                && pair.First.Layout.Hits.SequenceEqual(pair.Second.Layout.Hits)) && Pixels(canvas).SequenceEqual(Pixels(expected)));
            SaveCanvas(canvas, Path.ChangeExtension(output, "." + name + ".png"));
        }
        static byte[] Pixels(OverlayCanvas content)
        {
            RenderTargetBitmap image = new((int)Math.Ceiling(content.ActualWidth), (int)Math.Ceiling(content.ActualHeight), 96, 96, PixelFormats.Pbgra32);
            OverlayCanvasReference.Render(image, content); byte[] pixels = new byte[image.PixelWidth * image.PixelHeight * 4];
            image.CopyPixels(pixels, image.PixelWidth * 4, 0); return pixels;
        }
        Fresh("disconnected_layout_matches_fresh_canvas", entry, skin, 1, new(800, 650), connected: false);
        canvas.SetConnected(true); canvas.SetDpi(2.5);
        Fresh("dpi_change_matches_fresh_canvas", entry, skin, 2.5, new(800, 650));
        entry = entry with { Theme = "dark", FontScale = 1.5 };
        skin = NativeSkins.Parse(Object("""
            {"schema_version":2,"name":"组合布局验证","modules":[
            {"type":"damage","settings":{"theme":"dark","avatar_size_percent":175}},
            {"type":"combo_skill","settings":{"theme":"dark","avatar_size_percent":175}},
            {"type":"uid_mask"}],"layout":{"direction":"vertical"},"theme":{"padding":4,"spacing":6}}
            """));
        canvas.Apply(entry, skin);
        Fresh("font_theme_avatar_change_matches_fresh_canvas", entry, skin, 2.5, new(800, 650));
        var bars = NativeSkins.Builtin("combo_skill");
        entry = new OverlaySettings { SourceValue = "combo_skill", TemplateSettings = Object("""{"display_style":"bars"}""") };
        canvas.Apply(entry, bars); canvas.Receive(combo); canvas.SetDpi(1.75);
        foreach (var width in new[] { 420d, 900, 540 })
        {
            canvas.ArrangeSurface(new(width, 380));
            Fresh("bar_width_" + width + "_matches_fresh_canvas", entry, bars, 1.75, new(width, 380));
        }
        canvas.SetDpi(1); canvas.ArrangeSurface(new(540, 380));
        Fresh("bar_dpi_change_matches_fresh_canvas", entry, bars, 1, new(540, 380));
    }
}
