using System.Collections;
using System.Collections.Specialized;
using System.ComponentModel;
using System.Globalization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Read-only history uses shared columns and recycled row presenters,
/// without creating a selectable DataGridCell for every text value.</summary>
internal sealed class HistoryList : ListView
{
    private readonly GridView columns = new() { AllowsColumnReorder = true };
    private ICollectionView? sortedView;
    private readonly Style tableRows;
    internal GridViewColumnCollection Columns => columns.Columns;
    internal HistoryTextCache TextCache { get; } = new();

    public HistoryList()
    {
        View = columns; SelectionMode = SelectionMode.Extended;
        Background = Brushes.Transparent; BorderThickness = new(0); AlternationCount = 2;
        SetBinding(ForegroundProperty, WindowBinding(nameof(Window.Foreground)));
        Resources[typeof(GridViewColumnHeader)] = HeaderStyle();
        ScrollViewer.SetCanContentScroll(this, true);
        VirtualizingPanel.SetIsVirtualizing(this, true);
        VirtualizingPanel.SetVirtualizationMode(this, VirtualizationMode.Recycling);
        VirtualizingPanel.SetCacheLength(this, new(0));
        FrameworkElementFactory presenter = new(typeof(GridViewRowPresenter));
        presenter.SetValue(GridViewRowPresenter.ContentProperty, new TemplateBindingExtension(ContentControl.ContentProperty));
        presenter.SetBinding(GridViewRowPresenter.ColumnsProperty, new Binding("View.Columns")
        { RelativeSource = new(RelativeSourceMode.FindAncestor, typeof(HistoryList), 1) });
        FrameworkElementFactory border = new(typeof(Border));
        border.SetValue(Border.BackgroundProperty, new TemplateBindingExtension(BackgroundProperty));
        border.SetValue(Border.BorderBrushProperty, new TemplateBindingExtension(BorderBrushProperty));
        border.SetValue(Border.BorderThicknessProperty, new TemplateBindingExtension(BorderThicknessProperty));
        border.AppendChild(presenter);
        Style rows = new(typeof(ListViewItem));
        rows.Setters.Add(new Setter(MinHeightProperty, 32d));
        rows.Setters.Add(new Setter(PaddingProperty, new Thickness(0)));
        rows.Setters.Add(new Setter(HorizontalContentAlignmentProperty, HorizontalAlignment.Stretch));
        rows.Setters.Add(new Setter(BackgroundProperty, Brushes.Transparent));
        rows.Setters.Add(new Setter(ForegroundProperty, new Binding(nameof(Foreground))
        { RelativeSource = new(RelativeSourceMode.FindAncestor, typeof(HistoryList), 1) }));
        rows.Setters.Add(new Setter(BorderBrushProperty, new SolidColorBrush(Color.FromArgb(28, 128, 128, 128))));
        rows.Setters.Add(new Setter(BorderThicknessProperty, new Thickness(0, 0, 0, 1)));
        rows.Setters.Add(new Setter(TemplateProperty, new ControlTemplate(typeof(ListViewItem)) { VisualTree = border }));
        rows.Triggers.Add(new Trigger { Property = ItemsControl.AlternationIndexProperty, Value = 1,
            Setters = { new Setter(BackgroundProperty, new SolidColorBrush(Color.FromArgb(12, 128, 128, 128))) } });
        rows.Triggers.Add(new Trigger { Property = IsMouseOverProperty, Value = true,
            Setters = { new Setter(BackgroundProperty, new SolidColorBrush(Color.FromArgb(28, 128, 128, 128))) } });
        rows.Triggers.Add(new Trigger { Property = ListBoxItem.IsSelectedProperty, Value = true,
            Setters = { new Setter(BackgroundProperty, new DynamicResourceExtension(SystemColors.HighlightBrushKey)),
                new Setter(ForegroundProperty, new DynamicResourceExtension(SystemColors.HighlightTextBrushKey)) } });
        tableRows = rows; ItemContainerStyle = rows;
        AddHandler(GridViewColumnHeader.ClickEvent, new RoutedEventHandler((_, args) =>
        {
            if (args.OriginalSource is GridViewColumnHeader { Role: GridViewColumnHeaderRole.Normal, Column: HistoryColumn column })
                Sort(column, Keyboard.Modifiers.HasFlag(ModifierKeys.Shift));
        }), handledEventsToo: true);
        CommandBindings.Add(new(ApplicationCommands.Copy, (_, _) => Clipboard.SetText(CopySelection()),
            (_, args) => args.CanExecute = SelectedItems.Count != 0));
    }

    internal void SetRecordLayout(bool records)
    {
        View = records ? null : columns;
        ScrollViewer.SetHorizontalScrollBarVisibility(this, records ? ScrollBarVisibility.Disabled : ScrollBarVisibility.Auto);
        if (!records) { ItemContainerStyle = tableRows; return; }
        FrameworkElementFactory lines = new(typeof(StackPanel)); lines.SetValue(MarginProperty, new Thickness(12, 9, 12, 9));
        FrameworkElementFactory name = new(typeof(TextBlock)); name.SetBinding(TextBlock.TextProperty, new Binding(nameof(HistoryRow.Name)));
        name.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis); lines.AppendChild(name);
        FrameworkElementFactory detail = new(typeof(TextBlock)); detail.SetBinding(TextBlock.TextProperty, new Binding(nameof(HistoryRow.Description)));
        detail.SetValue(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis); detail.SetValue(MarginProperty, new Thickness(0, 5, 0, 0)); detail.SetValue(OpacityProperty, .8); lines.AppendChild(detail);
        FrameworkElementFactory presenter = new(typeof(ContentPresenter)); presenter.SetValue(ContentPresenter.ContentProperty, new TemplateBindingExtension(ContentControl.ContentProperty));
        presenter.SetValue(ContentPresenter.ContentTemplateProperty, new DataTemplate { VisualTree = lines });
        FrameworkElementFactory border = new(typeof(Border)); border.SetValue(Border.BackgroundProperty, new TemplateBindingExtension(BackgroundProperty));
        border.SetValue(Border.BorderBrushProperty, new TemplateBindingExtension(BorderBrushProperty)); border.SetValue(Border.BorderThicknessProperty, new TemplateBindingExtension(BorderThicknessProperty)); border.AppendChild(presenter);
        Style cards = new(typeof(ListViewItem), tableRows); cards.Setters.Add(new Setter(TemplateProperty, new ControlTemplate(typeof(ListViewItem)) { VisualTree = border }));
        cards.Setters.Add(new Setter(ToolTipProperty, new Binding(nameof(HistoryRow.Full)))); ItemContainerStyle = cards;
    }

    private static Binding WindowBinding(string path) => new(path)
    { RelativeSource = new(RelativeSourceMode.FindAncestor, typeof(Window), 1) };

    private static Style HeaderStyle()
    {
        FrameworkElementFactory content = new(typeof(ContentPresenter));
        content.SetValue(ContentPresenter.ContentProperty, new TemplateBindingExtension(ContentControl.ContentProperty));
        content.SetValue(MarginProperty, new Thickness(7, 4, 14, 4));
        content.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
        FrameworkElementFactory border = new(typeof(Border));
        border.SetValue(Border.BackgroundProperty, new TemplateBindingExtension(BackgroundProperty));
        border.SetValue(Border.BorderBrushProperty, new TemplateBindingExtension(BorderBrushProperty));
        border.SetValue(Border.BorderThicknessProperty, new TemplateBindingExtension(BorderThicknessProperty));
        border.AppendChild(content);
        FrameworkElementFactory gripBorder = new(typeof(Border));
        gripBorder.SetValue(Border.BackgroundProperty, Brushes.Transparent);
        FrameworkElementFactory grip = new(typeof(Thumb), "PART_HeaderGripper");
        grip.SetValue(WidthProperty, 5d); grip.SetValue(HorizontalAlignmentProperty, HorizontalAlignment.Right);
        grip.SetValue(CursorProperty, Cursors.SizeWE); grip.SetValue(FocusableProperty, false);
        grip.SetValue(TemplateProperty, new ControlTemplate(typeof(Thumb)) { VisualTree = gripBorder });
        FrameworkElementFactory grid = new(typeof(Grid)); grid.AppendChild(border); grid.AppendChild(grip);
        ControlTemplate template = new(typeof(GridViewColumnHeader)) { VisualTree = grid };
        template.Triggers.Add(new Trigger { Property = GridViewColumnHeader.RoleProperty, Value = GridViewColumnHeaderRole.Padding,
            Setters = { new Setter(VisibilityProperty, Visibility.Collapsed) { TargetName = "PART_HeaderGripper" } } });
        Style style = new(typeof(GridViewColumnHeader));
        style.Setters.Add(new Setter(ForegroundProperty, WindowBinding(nameof(Window.Foreground))));
        style.Setters.Add(new Setter(BackgroundProperty, WindowBinding(nameof(Window.Background))));
        style.Setters.Add(new Setter(BorderBrushProperty, new SolidColorBrush(Color.FromArgb(28, 128, 128, 128))));
        style.Setters.Add(new Setter(BorderThicknessProperty, new Thickness(0, 0, 1, 1)));
        style.Setters.Add(new Setter(TemplateProperty, template));
        return style;
    }

    protected override void OnItemsSourceChanged(IEnumerable oldValue, IEnumerable newValue)
    {
        if (sortedView is not null)
            CollectionChangedEventManager.RemoveHandler((INotifyCollectionChanged)sortedView.SortDescriptions, SortChanged);
        base.OnItemsSourceChanged(oldValue, newValue);
        sortedView = newValue is null ? null : CollectionViewSource.GetDefaultView(newValue);
        if (sortedView is not null)
            CollectionChangedEventManager.AddHandler((INotifyCollectionChanged)sortedView.SortDescriptions, SortChanged);
        UpdateSortHeaders();
    }
    private void SortChanged(object? sender, NotifyCollectionChangedEventArgs args) => UpdateSortHeaders();

    internal void Sort(HistoryColumn column, bool extend = false)
    {
        var view = sortedView;
        if (view is null || !view.CanSort) return;
        var previous = view.SortDescriptions.FirstOrDefault(order => order.PropertyName == column.Path);
        var direction = previous.PropertyName is not null && previous.Direction == ListSortDirection.Ascending
            ? ListSortDirection.Descending : ListSortDirection.Ascending;
        using (view.DeferRefresh())
        {
            if (!extend) view.SortDescriptions.Clear();
            else if (previous.PropertyName is not null) view.SortDescriptions.Remove(previous);
            view.SortDescriptions.Add(new(column.Path, direction));
        }
    }

    private void UpdateSortHeaders()
    {
        foreach (HistoryColumn item in Columns)
        {
            var order = sortedView?.SortDescriptions.FirstOrDefault(value => value.PropertyName == item.Path) ?? default;
            ((GridViewColumnHeader)item.Header).Content = item.Title + (order.PropertyName is null ? ""
                : order.Direction == ListSortDirection.Ascending ? " ▲" : " ▼");
        }
    }

    internal string CopySelection()
    {
        var selected = SelectedItems.Cast<HistoryRow>().ToHashSet();
        return string.Join(Environment.NewLine, Items.Cast<HistoryRow>().Where(selected.Contains).Select(row =>
            string.Join('\t', Columns.Cast<HistoryColumn>().Select(column => Convert.ToString(column.Read(row), CultureInfo.CurrentCulture) ?? ""))));
    }
}
