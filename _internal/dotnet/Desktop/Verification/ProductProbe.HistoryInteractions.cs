using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using EndfieldLogs.Core.Compatibility;
using EndfieldLogs.Desktop.Presentation;
using EndfieldLogs.Runtime.Configuration;
using EndfieldLogs.Runtime.History;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    // This check needs no Window, dispatcher loop, capture or injected input.
    internal static void VerifyHistoryInteractions(Action<string, bool> check)
    {
        var temporary = Directory.CreateTempSubdirectory("endfield-history-interactions-");
        try
        {
            var codec = new SettingsCodec(new(temporary.FullName));
            using var history = new HistoryController(new(codec.Decode((EvidenceObject)EvidenceJson.Parse("{}")), codec),
                new HistoryIndex(Path.Combine(temporary.FullName, "cache")),
                (_, _) => throw new InvalidOperationException("事件路由检查不应分析报告"));
            var requests = 0;
            HistoryPage page = new(history, _ => requests++, message => throw new InvalidOperationException(message), () => { });
            var table = page.RecordsTable;
            table.SetRecordLayout(false);
            HistoryRecord record = new(Path.Combine(temporary.FullName, "trace_synthetic.log"), 0, 0, "测试记录", [],
                0, 0, 1, 1, false, true, new(0, 0));
            HistoryRow row = new(record); table.Items.Add(row); table.SelectedItem = row;
            page.Measure(new(1000, 900)); page.Arrange(new(0, 0, 1000, 900)); page.UpdateLayout();
            var container = (ListViewItem)table.ItemContainerGenerator.ContainerFromItem(row);
            var cell = Descendants<HistoryCell>(container).First();
            void DoubleClick(string name, object source, MouseButton button, int expected)
            {
                var before = requests;
                table.RaiseEvent(new MouseButtonEventArgs(Mouse.PrimaryDevice, 0, button)
                    { RoutedEvent = Control.MouseDoubleClickEvent, Source = source });
                check(name, requests - before == expected);
            }
            DoubleClick("history_header_double_click_does_not_analyze", table.Columns[0].Header, MouseButton.Left, 0);
            DoubleClick("history_blank_double_click_does_not_analyze", table, MouseButton.Left, 0);
            DoubleClick("history_right_double_click_does_not_analyze", container, MouseButton.Right, 0);
            DoubleClick("history_row_double_click_requests_analysis", container, MouseButton.Left, 1);
            DoubleClick("history_cell_double_click_requests_analysis", cell, MouseButton.Left, 1);
            table.SetRecordLayout(true);
            page.Measure(new(1000, 900)); page.Arrange(new(0, 0, 1000, 900)); page.UpdateLayout();
            var recordText = Descendants<TextBlock>((ListViewItem)table.ItemContainerGenerator.ContainerFromItem(row)).First();
            DoubleClick("history_record_card_double_click_requests_analysis", recordText, MouseButton.Left, 1);
        }
        finally { temporary.Delete(true); }
    }
}
