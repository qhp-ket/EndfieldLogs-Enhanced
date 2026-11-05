using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Overlays;
using EndfieldLogs.Desktop.Presentation;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    private static async Task VerifyInputViewport(EvidenceObject report, Action<string, bool> check)
    {
        var raw = Enumerable.Range(0, 2000).Select(index => (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>
        {
            ["time_ms"] = new EvidenceReal((index % 1000) * 5), ["device"] = new EvidenceText("mouse"),
            ["code"] = new EvidenceText("X"), ["value"] = new EvidenceInteger(index < 1000 ? -30000 : 30000)
        })).ToArray();
        var actions = Enumerable.Range(0, 500).Select(index => (EvidenceValue)new EvidenceObject(new Dictionary<string, EvidenceValue>
        {
            ["start_ms"] = new EvidenceReal(index * 10), ["end_ms"] = new EvidenceReal(index * 10 + (index % 7 == 0 ? 300 : 0)),
            ["action"] = new EvidenceText(index % 3 == 0 ? "combo" : "skill"), ["character_key"] = new EvidenceText("chr_0001_test"),
            ["interrupted"] = new EvidenceBoolean(index % 5 == 0), ["tooltip"] = new EvidenceText("输入 " + index)
        })).ToArray();
        var input = new EvidenceObject(new Dictionary<string, EvidenceValue> { ["raw"] = new EvidenceArray(raw), ["actions"] = new EvidenceArray(actions) });
        var canonical = PythonSortedJson.Serialize(input);
        var timeline = new BattleTimeline(report) { Width = 2400 };
        timeline.SetInputEvidence(input);
        Window host = new() { Width = 1000, Height = 700, Content = timeline, ShowInTaskbar = false, WindowStartupLocation = WindowStartupLocation.CenterScreen };
        byte[] Crop(Int32Rect area)
        {
            var bitmap = new RenderTargetBitmap(2400, (int)Math.Ceiling(timeline.ActualHeight), 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(timeline); var bytes = new byte[area.Width * area.Height * 4]; bitmap.CopyPixels(area, bytes, area.Width * 4, 0); return bytes;
        }
        try
        {
            host.Show(); await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            foreach (var dark in new[] { false, true })
            {
                timeline.ApplyPresentation(new AvatarCache(ProductApplication.ResolveRoot()), 100, false, 100, dark);
                foreach (var offset in new[] { 0d, 317.25, 1400.5 })
                {
                    timeline.SetViewport(0, 0, 0, 0); timeline.InvalidateVisual(); await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                    var area = new Int32Rect((int)Math.Ceiling(offset + timeline.LabelWidth + 8), 32, 450, (int)Math.Floor(timeline.ActualHeight) - 34);
                    var complete = Crop(area);
                    var expected = timeline.InputSpans.Where(item => item.Bounds.Right + 5 >= offset + timeline.LabelWidth && item.Bounds.Left - 5 <= offset + 700)
                        .Select(item => item.Span).ToHashSet();
                    timeline.SetViewport(offset, 0, 700, timeline.ActualHeight); await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                    check($"input_viewport_{dark}_{offset}_pixels", complete.SequenceEqual(Crop(area)));
                    check($"input_viewport_{dark}_{offset}_overlap_and_zero_width", expected.IsSubsetOf(timeline.InputSpans.Select(item => item.Span)));
                    check($"input_viewport_{dark}_{offset}_bounded_hits", timeline.InputSpans.Count < actions.Length / 2);
                }
            }
            timeline.SetViewport(317.25, 0, 700, 35); await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            check("input_vertical_culling_keeps_full_source", timeline.InputSpans.Count < 500 && timeline.InputLayout.Raw.Count == 2000
                && timeline.InputLayout.Spans.Count == 500 && canonical == PythonSortedJson.Serialize(input));
            timeline.Configure("b", true, 1, 1, false); await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            check("input_index_invalidates_for_role_filter", timeline.InputLayout.Spans.All(span => EvidenceView.Text(span.Evidence.Get("action")) == "combo"));
        }
        finally { host.Close(); }
    }
}
