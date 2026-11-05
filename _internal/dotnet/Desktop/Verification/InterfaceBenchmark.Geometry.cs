using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Text.Json.Nodes;
using System.Windows.Threading;
using EndfieldLogs.Desktop.Presentation;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class InterfaceBenchmark
{
    private static async Task ConfigureHistoryDisplay(Window window, HistoryPage page, HistoryList table, JsonNode display)
    {
        var size = display["viewport_dip"]!.AsArray();
        var width = size[0]!.GetValue<int>(); var height = size[1]!.GetValue<int>();
        var rowHeight = display["row_min_height_dip"]!.GetValue<int>();
        if (width is < 400 or > 1000 || height is < 300 or > 600 || rowHeight is < 32 or > 200)
            throw new ArgumentException("历史显示控制超出允许范围");
        // Match the Qt page client size, excluding native window decorations.
        window.Width += 1200 - page.ActualWidth; window.Height += 800 - page.ActualHeight;
        table.MinHeight = 0; table.HorizontalAlignment = HorizontalAlignment.Left;
        ScrollViewer.SetVerticalScrollBarVisibility(table, ScrollBarVisibility.Visible);
        ScrollViewer.SetHorizontalScrollBarVisibility(table, ScrollBarVisibility.Disabled);
        table.Width = width + 24; table.Height = height + 8;
        Style rows = new(typeof(ListViewItem), table.ItemContainerStyle);
        rows.Setters.Add(new Setter(FrameworkElement.MinHeightProperty, (double)rowHeight));
        table.ItemContainerStyle = rows;
        for (var step = 0; step < 3; step++)
        {
            await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            var viewport = Descendants<ScrollContentPresenter>(table).First();
            table.Width += width - viewport.ActualWidth; table.Height += height - viewport.ActualHeight;
        }
        Descendants<ScrollViewer>(page).First().ScrollToBottom();
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        BenchmarkWindow.Check();
    }

    // Geometry validation runs after timing, using the actual clipped viewport
    // and realized text, rather than estimates based on window or row counts.
    private static object HistoryGeometry(HistoryList table, int target, FrameworkElement page)
    {
        var viewport = Descendants<ScrollContentPresenter>(table).First();
        var clip = new Rect(viewport.RenderSize);
        for (var parent = VisualTreeHelper.GetParent(viewport); parent is Visual; parent = VisualTreeHelper.GetParent(parent))
        {
            if (parent is not FrameworkElement element || (!element.ClipToBounds && element is not ScrollContentPresenter)) continue;
            var inverse = viewport.TransformToAncestor(element).Inverse;
            if (inverse is not null) clip.Intersect(inverse.TransformBounds(new Rect(element.RenderSize)));
        }
        if (clip.IsEmpty) throw new InvalidOperationException("历史列表视口被完全裁切");
        var dpi = VisualTreeHelper.GetDpi(viewport);
        List<object> rows = [];
        foreach (var row in Descendants<ListViewItem>(table).OrderBy(table.ItemContainerGenerator.IndexFromContainer))
        {
            var index = table.ItemContainerGenerator.IndexFromContainer(row);
            var bounds = row.TransformToAncestor(viewport).TransformBounds(new Rect(row.RenderSize));
            var visible = Rect.Intersect(bounds, clip);
            if (index < 0 || visible.IsEmpty || visible.Width <= 0 || visible.Height <= 0) continue;
            var text = Descendants<TextBlock>(row).ToArray();
            if (text.Length != 2) throw new InvalidOperationException("配对历史检查要求原生双行记录卡");
            rows.Add(new
            {
                index, height_px = row.ActualHeight * dpi.DpiScaleY,
                fully_visible = bounds.Top >= clip.Top - .01 && bounds.Bottom <= clip.Bottom + .01,
                text_lines = text.Select(item => item.Text).ToArray(),
                font_family = text[0].FontFamily.Source,
                font_size_px = text[0].FontSize * dpi.DpiScaleY,
                text_fits_row = text.All(item => item.ActualHeight + .01 >= item.DesiredSize.Height - item.Margin.Top - item.Margin.Bottom
                    && item.TransformToAncestor(row).TransformBounds(new Rect(item.RenderSize)) is var textBounds
                    && textBounds.Top >= -.01 && textBounds.Bottom <= row.ActualHeight + .01),
            });
        }
        return new
        {
            target, dpi_scale = new[] { dpi.DpiScaleX, dpi.DpiScaleY },
            page_client_px = new[] { page.ActualWidth * dpi.DpiScaleX, page.ActualHeight * dpi.DpiScaleY },
            viewport_px = new[] { clip.Width * dpi.DpiScaleX, clip.Height * dpi.DpiScaleY },
            rows,
        };
    }
}
