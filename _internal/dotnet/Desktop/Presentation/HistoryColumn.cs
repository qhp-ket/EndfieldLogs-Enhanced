using System.Globalization;
using System.Windows;
using System.Windows.Automation.Peers;
using System.Windows.Controls;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class HistoryColumn : GridViewColumn
{
    private readonly Func<HistoryRow, object?> read;
    private readonly string? format;

    internal string Path { get; }
    internal string Title { get; }
    internal bool Number { get; }
    internal HistoryTextCache Layouts { get; }

    private HistoryColumn(string title, string path, Func<HistoryRow, object?> read, bool number, string? format, double width, HistoryTextCache layouts)
    {
        Title = title; Path = path; this.read = read; Number = number; this.format = format; Width = width; Layouts = layouts;
        Header = new GridViewColumnHeader { Content = title, Padding = new Thickness(7, 4, 7, 4) };
        FrameworkElementFactory text = new(typeof(HistoryCell));
        text.SetValue(HistoryCell.ColumnProperty, this);
        CellTemplate = new DataTemplate { VisualTree = text };
    }

    internal static void Add(HistoryList table, string title, string path, Func<HistoryRow, object?> read,
        bool number = false, string? format = null, double width = 110)
        => table.Columns.Add(new HistoryColumn(title, path, read, number, format, width, table.TextCache));

    internal object? Read(HistoryRow row) => read(row);
    internal string Display(HistoryRow row) => read(row) switch
    {
        null => "未知",
        IFormattable value => value.ToString(format, CultureInfo.CurrentCulture),
        var value => value.ToString() ?? "",
    };
}

internal sealed class HistoryCell : Control
{
    internal static readonly DependencyProperty ColumnProperty = DependencyProperty.Register(nameof(Column),
        typeof(HistoryColumn), typeof(HistoryCell), new PropertyMetadata(null, (cell, _) => ((HistoryCell)cell).Update()));
    internal HistoryColumn Column => (HistoryColumn)GetValue(ColumnProperty);
    private HistoryTextCache.Layout? layout;
    internal string Text { get; private set; } = "";
    internal TextTrimming TextTrimming => layout?.Trimming ?? TextTrimming.None;

    public HistoryCell()
    {
        Margin = new(7, 4, 7, 4); ClipToBounds = true; Focusable = false; IsTabStop = false;
        VerticalAlignment = VerticalAlignment.Center;
        DataContextChanged += (_, _) => Update();
    }
    private void Update()
    {
        Text = Column is { } column && DataContext is HistoryRow row ? column.Display(row) : "";
        ToolTip = Text;
        layout = null; InvalidateMeasure(); InvalidateVisual();
    }
    protected override Size MeasureOverride(Size constraint)
    {
        if (Column is null) return new();
        layout = Column.Layouts.Get(Text, this, constraint.Width);
        return layout.Size;
    }
    protected override void OnRender(DrawingContext context)
    {
        if (Column is null || RenderSize.Width <= 0 || RenderSize.Height <= 0) return;
        layout = Column.Layouts.Get(Text, this, RenderSize.Width);
        context.DrawDrawing(layout.Drawing);
    }
    protected override void OnDpiChanged(DpiScale oldDpi, DpiScale newDpi)
    { base.OnDpiChanged(oldDpi, newDpi); InvalidateMeasure(); InvalidateVisual(); }
    protected override AutomationPeer OnCreateAutomationPeer() => new HistoryCellPeer(this);
    private sealed class HistoryCellPeer(HistoryCell owner) : FrameworkElementAutomationPeer(owner)
    {
        protected override string GetNameCore() => owner.Text;
        protected override AutomationControlType GetAutomationControlTypeCore() => AutomationControlType.Text;
    }
}
