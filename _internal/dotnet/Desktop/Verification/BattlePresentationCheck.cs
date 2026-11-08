using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using EndfieldLogs.Core.Catalog;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Verification;

/// <summary>Render and inspect real history coordinates without a window or input injection.</summary>
internal static class BattlePresentationCheck
{
    internal static int Run(string source, string root, string output)
    {
        Dictionary<string, object?> result = [];
        void Check(string name, bool passed) { result[name] = passed; if (!passed) throw new InvalidOperationException(name); }
        var folder = Path.GetDirectoryName(Path.GetFullPath(output))!; Directory.CreateDirectory(folder);
        try
        {
            Application app = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            var files = new ResourceFiles(Path.Combine(root, "_internal"));
            var report = source.EndsWith(".jsonl", StringComparison.OrdinalIgnoreCase)
                ? new HistoryAnalyzer(files).Analyze(new HistoryCatalog().Read(source, trace: true)[0])
                : (EvidenceObject)EvidenceJson.Parse(File.ReadAllText(source));
            File.WriteAllText(Path.ChangeExtension(output, ".report.json"), PythonSortedJson.Serialize(report));
            Verify(report, files, root, output, Check);
            result["windows_shown"] = 0; result["passed"] = true;
            app.Shutdown();
            return 0;
        }
        catch (Exception error) { result["passed"] = false; result["error"] = error.ToString(); return 1; }
        finally { File.WriteAllText(output, JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true })); }
    }
    internal static void Verify(EvidenceObject report, ResourceFiles files, string root, string output, Action<string, bool> Check)
    {
        var folder = Path.GetDirectoryName(Path.GetFullPath(output))!;
        var canonical = PythonSortedJson.Serialize(report);
        var avatars = new AvatarCache(root);
        foreach (var dark in new[] { false, true })
        {
            BattleTimeline timeline = new(report, resources: files);
            timeline.Configure("", false, 1, 1, false); timeline.SetViewport(0, 0, 1200, 1000);
            timeline.ApplyPresentation(avatars, 115, true, 100, dark);
            Layout(timeline); var originalHeight = timeline.DesiredSize.Height;
            Save(timeline, Path.ChangeExtension(output, dark ? ".dark.png" : ".light.png"));
            var areas = timeline.MarkAreas.Where(area => area.Bounds.X > timeline.LabelWidth + 4).ToArray();
            Check($"marks_drawn_{dark}", areas.Length > 0);
            Check($"all_marks_hover_and_select_{dark}", areas.All(area =>
            {
                var point = new Point(area.Bounds.X + area.Bounds.Width / 2, area.Bounds.Y + area.Bounds.Height / 2);
                return timeline.MarksAt(point).Contains(area.Mark) && timeline.HoverText(point).Contains(area.Mark.Name, StringComparison.Ordinal)
                    && timeline.HoverText(point).Contains("当前位置：", StringComparison.Ordinal);
            }));
            var tiny = areas.Where(area => area.Mark.Skill is not null && area.Mark.Start == area.Mark.End).ToArray();
            Check($"point_evidence_clickable_{dark}", tiny.All(area => area.Bounds.Width >= 6));
            Check($"skill_types_have_distinct_colors_{dark}", BattleTimeline.SkillFill("战技") != BattleTimeline.SkillFill("连携")
                && BattleTimeline.SkillFill("连携") != BattleTimeline.SkillFill("大招"));
            var renders = timeline.ContentRenderCount;
            timeline.SetReference(timeline.Duration / 2);
            Save(timeline, Path.ChangeExtension(output, dark ? ".dark-hover.png" : ".light-hover.png"));
            Check($"reference_does_not_redraw_report_{dark}", timeline.ContentRenderCount == renders);
            timeline.ApplyPresentation(avatars, 150, true, 100, dark); Layout(timeline);
            Save(timeline, Path.ChangeExtension(output, dark ? ".dark-large.png" : ".light-large.png"));
            Check($"large_font_sets_minimum_row_height_{dark}", timeline.FontScale == 1.5 && timeline.DesiredSize.Height > originalHeight);
            timeline.Configure("", false, 1, 1.8, false); Layout(timeline);
            Check($"graph_scale_increases_geometry_{dark}", timeline.DesiredSize.Height > originalHeight * 1.5);
            timeline.Configure("", false, 4, 1, true); timeline.SetViewport(420, 30, 1200, 700); Layout(timeline);
            Save(timeline, Path.ChangeExtension(output, dark ? ".dark-scrolled.png" : ".light-scrolled.png"));
            Check($"scrolled_frame_hover_uses_report_time_{dark}", timeline.HoverText(new(800, 8)).Contains("F", StringComparison.Ordinal));
        }
        Check("canonical_report_unchanged", canonical == PythonSortedJson.Serialize(report));
        var codec = new SettingsCodec(new(Path.Combine(folder, "profile"))); var defaults = codec.Decode(new(new Dictionary<string, EvidenceValue>()));
        BattleAnalysisWindow window = new(report, new SettingsStore(defaults, codec), resources: files);
        var sliders = Descendants<Slider>(window).ToArray(); var graph = sliders.Single(slider => slider.Maximum == 2.5);
        graph.Value = 1.8;
        Check("graph_scale_also_resizes_curve", window.Plot.Height == 155 * 1.8);
        window.Close();
    }
    private static IEnumerable<T> Descendants<T>(DependencyObject node) where T : DependencyObject
    {
        foreach (var child in LogicalTreeHelper.GetChildren(node).OfType<DependencyObject>())
        { if (child is T match) yield return match; foreach (var next in Descendants<T>(child)) yield return next; }
    }
    private static void Layout(FrameworkElement view)
    {
        view.Measure(new Size(1200, double.PositiveInfinity));
        view.Arrange(new Rect(0, 0, view.DesiredSize.Width, view.DesiredSize.Height)); view.UpdateLayout();
    }
    private static void Save(FrameworkElement view, string path)
    {
        RenderTargetBitmap bitmap = new((int)Math.Ceiling(view.ActualWidth), (int)Math.Ceiling(view.ActualHeight), 96, 96, PixelFormats.Pbgra32);
        bitmap.Render(view); PngBitmapEncoder encoder = new(); encoder.Frames.Add(BitmapFrame.Create(bitmap));
        using var file = File.Create(path); encoder.Save(file);
    }
}
