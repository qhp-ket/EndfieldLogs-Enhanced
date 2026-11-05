using System.ComponentModel;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class InterfaceBenchmark
{
    // Opt-in checks run after all timing. Exercise the actual recycled controls,
    // including unknown values, raw numeric sorting and the normal clipboard path.
    private static async Task<int> VerifyHistoryCells(HistoryList table, HistoryController history)
    {
        var checks = 0;
        void Check(bool value, string reason)
        {
            if (!value) throw new InvalidOperationException("History cells: " + reason);
            checks++;
        }
        string Expected(HistoryRecord record, int column) => column switch
        {
            0 => DateTimeOffset.FromUnixTimeMilliseconds(record.StartedAtMs).ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss"),
            1 => record.Label,
            2 => string.Join("、", record.Players.Select(player => player.DisplayName)),
            3 => record.AnalysisLoaded || !record.IsTrace ? record.TotalDamage.ToString("N0", CultureInfo.CurrentCulture) : "未知",
            4 => record.AnalysisLoaded || !record.IsTrace ? record.Dps.ToString("N1", CultureInfo.CurrentCulture) : "未知",
            5 => record.DurationMs > 0 ? (record.DurationMs / 1000d).ToString("N1", CultureInfo.CurrentCulture) : "未知",
            _ => throw new ArgumentOutOfRangeException(nameof(column)),
        };
        void Visible()
        {
            var count = 0;
            foreach (var container in Descendants<ListViewItem>(table))
            {
                if (container.Content is not HistoryRow row) continue;
                foreach (var text in Descendants<HistoryCell>(container))
                {
                    var index = Array.IndexOf(new[] { nameof(HistoryRow.Started), nameof(HistoryRow.Name), nameof(HistoryRow.Players),
                        nameof(HistoryRow.Damage), nameof(HistoryRow.Dps), nameof(HistoryRow.Duration) }, text.Column.Path);
                    var expected = Expected(row.Record, index);
                    Check(text.Text == expected && Equals(text.ToolTip, expected), "recycled text or tooltip");
                    Check(text.TextTrimming == TextTrimming.CharacterEllipsis, "long text trimming");
                    count++;
                }
            }
            Check(count > 0, "no realized cells");
        }
        var original = table.ItemsSource;
        var view = CollectionViewSource.GetDefaultView(original);
        var sorting = view.SortDescriptions.ToArray();
        var selected = history.SelectedRecords.Select(row => row.Key).ToArray();
        try
        {
            for (var step = 0; step < 20; step++)
            {
                table.ScrollIntoView(table.Items[(table.Items.Count - 1) * step / 19]);
                await Dispatcher.Yield(DispatcherPriority.ContextIdle);
                var target = table.ItemContainerGenerator.ContainerFromItem(table.Items[(table.Items.Count - 1) * step / 19]) as ListViewItem;
                Check(target is not null, "scroll target realized");
                var bounds = target!.TransformToAncestor(table).TransformBounds(new Rect(target.RenderSize));
                Check(bounds.Bottom > 0 && bounds.Top < table.ActualHeight, "scroll target visible");
                Visible();
            }
            var seed = table.Items.OfType<HistoryRow>().First().Record;
            var samples = new[] { 1000d, 2d, 12d }.Select((damage, index) => new HistoryRow(seed with
            {
                Label = "很长的战斗名称 · " + new string('测', 100) + index,
                TotalDamage = damage, DurationMs = 1500, AnalysisLoaded = true,
            })).Append(new HistoryRow(seed with { Label = "未知", AnalysisLoaded = false, IsTrace = true, DurationMs = 0 })).ToArray();
            table.ItemsSource = samples;
            var sampleView = CollectionViewSource.GetDefaultView(samples);
            sampleView.SortDescriptions.Add(new(nameof(HistoryRow.Damage), ListSortDirection.Ascending));
            await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            Check(table.Items.OfType<HistoryRow>().Select(row => row.Damage).SequenceEqual(new double?[] { null, 2, 12, 1000 }), "raw numeric sorting");
            Visible();
            var column = table.Columns[3];
            Check(Equals(((HistoryColumn)column).Read(samples[0]), 1000d), "clipboard uses original value");
            var header = Descendants<GridViewColumnHeader>(table).Single(item => ReferenceEquals(item.Column, column)
                && item.Role == GridViewColumnHeaderRole.Normal);
            header.RaiseEvent(new RoutedEventArgs(ButtonBase.ClickEvent));
            await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            Check(table.Items.OfType<HistoryRow>().Select(row => row.Damage).SequenceEqual(new double?[] { 1000, 12, 2, null }),
                "header toggles numeric sort: " + string.Join(",", sampleView.SortDescriptions.Select(order => order.PropertyName + " " + order.Direction)));
            table.SelectedItems.Add(samples[0]);
            Check(table.CopySelection().Split('\t')[3] == "1000", "copy command uses raw numeric value");
            Check(ApplicationCommands.Copy.CanExecute(null, table), "copy command enabled");
            var width = column.Width;
            column.Width = 173;
            var grip = (Thumb)header.Template.FindName("PART_HeaderGripper", header);
            grip.RaiseEvent(new DragStartedEventArgs(0, 0) { RoutedEvent = Thumb.DragStartedEvent });
            grip.RaiseEvent(new DragDeltaEventArgs(13, 0) { RoutedEvent = Thumb.DragDeltaEvent });
            grip.RaiseEvent(new DragCompletedEventArgs(13, 0, false) { RoutedEvent = Thumb.DragCompletedEvent });
            Check(column.Width == 186, "header drag resizes column");
            table.Columns.Move(3, 0);
            table.ScrollIntoView(samples[0]);
            await Dispatcher.Yield(DispatcherPriority.ContextIdle);
            Check(column.ActualWidth == 186 && table.Columns.IndexOf(column) == 0, "resize and reorder");
            Check(table.CopySelection().Split('\t')[0] == "1000", "copy follows column order");
            Visible();
            table.Columns.Move(0, 3); column.Width = width;
        }
        finally
        {
            table.ItemsSource = original;
            view.SortDescriptions.Clear();
            foreach (var order in sorting) view.SortDescriptions.Add(order);
            await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        }
        table.SelectedItems.Clear();
        var rows = table.Items.OfType<HistoryRow>().Take(2).ToArray();
        foreach (var row in rows) table.SelectedItems.Add(row);
        Check(history.SelectedRecords.Select(row => row.Key).ToHashSet().SetEquals(rows.Select(row => row.Record.Key)), "multi-selection reaches controller");
        table.ScrollIntoView(rows[0]);
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        var focus = Descendants<ListViewItem>(table).First(cell => cell.Content is HistoryRow);
        // Validate the selection contract without moving OS keyboard focus.
        Check(focus.Focusable && table.SelectionMode == SelectionMode.Extended, "focusable rows and selection mode");
        var inkCell = Descendants<HistoryCell>(focus).First();
        byte[] Pixels()
        {
            var bitmap = new RenderTargetBitmap((int)Math.Ceiling(inkCell.ActualWidth),
                (int)Math.Ceiling(inkCell.ActualHeight), 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(inkCell);
            var pixels = new byte[bitmap.PixelWidth * bitmap.PixelHeight * 4];
            bitmap.CopyPixels(pixels, bitmap.PixelWidth * 4, 0);
            return pixels;
        }
        var originalInk = Pixels();
        inkCell.Foreground = Brushes.Red;
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        var redInk = Pixels();
        Check(!redInk.SequenceEqual(originalInk), "foreground change repaints cached glyphs");
        Check(Enumerable.Range(0, redInk.Length / 4).Any(pixel => redInk[pixel * 4 + 2] > redInk[pixel * 4 + 1]),
            "changed foreground reaches raster pixels");
        inkCell.ClearValue(Control.ForegroundProperty);
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        Check(Pixels().SequenceEqual(originalInk), "restored foreground reuses correct glyphs");
        var height = inkCell.ActualHeight;
        inkCell.FontSize = table.FontSize * 1.5;
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        Check(inkCell.ActualHeight > height && !Pixels().SequenceEqual(originalInk), "font change remeasures and repaints");
        inkCell.ClearValue(Control.FontSizeProperty);
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        Check(Pixels().SequenceEqual(originalInk), "restored font preserves drawing");
        // Stress the real bounded cache after timing, then revisit an evicted value.
        var cache = inkCell.Column.Layouts;
        for (var index = 0; index < 1500; index++) cache.Get("缓存淘汰 · " + index, inkCell, inkCell.ActualWidth);
        Check(cache.Count <= 1024, "history drawing cache stays bounded");
        inkCell.InvalidateVisual();
        await Dispatcher.Yield(DispatcherPriority.ContextIdle);
        Check(Pixels().SequenceEqual(originalInk), "evicted glyphs regenerate identically");
        table.SelectedItems.Clear();
        foreach (var row in table.Items.OfType<HistoryRow>().Where(row => selected.Contains(row.Record.Key))) table.SelectedItems.Add(row);
        return checks;
    }
}
