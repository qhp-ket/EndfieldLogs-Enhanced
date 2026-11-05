using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Data;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal enum MainPage { Home, Overlays, History, Logs, Settings }

/// <summary>Persistent page instances behind the same navigation groups as the Qt client.</summary>
internal sealed class MainNavigation : Grid
{
    private readonly ColumnDefinition sidebar = new();
    private readonly ListBox entries = new() { BorderThickness = new(0), Background = Brushes.Transparent, Padding = new(4) };
    private readonly ContentControl page = new() { HorizontalContentAlignment = HorizontalAlignment.Stretch, VerticalContentAlignment = VerticalAlignment.Stretch };
    private readonly TextBlock title = Ui.Text("", 22);
    private readonly Dictionary<MainPage, (string Name, UIElement Content)> pages = [];
    private readonly List<TextBlock> labels = [];
    private readonly Button toggle;
    internal bool IsExpanded { get; private set; } = true;
    internal MainPage SelectedPage => (MainPage)((ListBoxItem)entries.SelectedItem).Tag;
    internal UIElement SelectedContent => (UIElement)page.Content;
    internal IReadOnlyList<string> PageNames => entries.Items.Cast<ListBoxItem>().Select(item => pages[(MainPage)item.Tag].Name).ToArray();
    internal event Action<MainPage>? PageChanged;

    internal MainNavigation()
    {
        ColumnDefinitions.Add(sidebar); ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        DockPanel navigation = new() { LastChildFill = true, Margin = new(4, 8, 0, 8) };
        toggle = new() { Content = "\uE700", FontFamily = new("Segoe MDL2 Assets"), FontSize = 16,
            Width = 40, Height = 36, Margin = new(6, 0, 0, 8), HorizontalAlignment = HorizontalAlignment.Left };
        toggle.Click += (_, _) => SetExpanded(!IsExpanded);
        DockPanel.SetDock(toggle, Dock.Top); navigation.Children.Add(toggle); navigation.Children.Add(entries);
        Children.Add(navigation);
        DockPanel body = new() { Margin = new(20, 12, 16, 12) };
        DockPanel.SetDock(title, Dock.Top); body.Children.Add(title); body.Children.Add(page); SetColumn(body, 1); Children.Add(body);
        ScrollViewer.SetHorizontalScrollBarVisibility(entries, ScrollBarVisibility.Disabled);
        entries.SetBinding(Control.ForegroundProperty, new Binding { Source = this, Path = new PropertyPath(TextElement.ForegroundProperty) });
        KeyboardNavigation.SetDirectionalNavigation(entries, KeyboardNavigationMode.Contained);
        AutomationProperties.SetName(entries, "主导航");
        entries.SelectionChanged += (_, _) =>
        {
            if (entries.SelectedItem is not ListBoxItem item) return;
            var key = (MainPage)item.Tag; var selected = pages[key];
            page.Content = selected.Content; title.Text = selected.Name; PageChanged?.Invoke(key);
        };
        SetExpanded(true);
        SizeChanged += (_, _) => UpdateWidth();
    }

    internal void AddPage(MainPage key, string name, string icon, UIElement content, bool newGroup = false)
    {
        pages.Add(key, (name, content));
        Grid row = new() { MinHeight = 38, Margin = new(6, 0, 6, 0) };
        row.ColumnDefinitions.Add(new() { Width = new(30) }); row.ColumnDefinitions.Add(new() { Width = new(1, GridUnitType.Star) });
        row.Children.Add(new TextBlock { Text = icon, FontFamily = new("Segoe MDL2 Assets"), FontSize = 16, VerticalAlignment = VerticalAlignment.Center });
        TextBlock label = new() { Text = name, VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis,
            Visibility = IsExpanded ? Visibility.Visible : Visibility.Collapsed };
        SetColumn(label, 1); row.Children.Add(label); labels.Add(label);
        ListBoxItem item = new() { Content = row, Tag = key, ToolTip = name, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Margin = new(0, newGroup ? 12 : 2, 0, 2), Padding = new(4, 0, 0, 0) };
        AutomationProperties.SetName(item, name);
        item.Style = ItemStyle(); entries.Items.Add(item);
        if (entries.SelectedItem is null) entries.SelectedItem = item;
    }

    internal void Select(MainPage key) => entries.SelectedItem = entries.Items.Cast<ListBoxItem>().Single(item => (MainPage)item.Tag == key);

    internal void SetExpanded(bool expanded)
    {
        IsExpanded = expanded;
        foreach (var label in labels) label.Visibility = expanded ? Visibility.Visible : Visibility.Collapsed;
        toggle.ToolTip = expanded ? "收起导航栏" : "展开导航栏";
        AutomationProperties.SetName(toggle, (string)toggle.ToolTip);
        UpdateWidth();
    }

    private void UpdateWidth() => sidebar.Width = new(IsExpanded ? Math.Max(220, (double)GetValue(TextBlock.FontSizeProperty) * 12 + 52) : 60);

    private static Style ItemStyle()
    {
        FrameworkElementFactory content = new(typeof(ContentPresenter));
        content.SetValue(MarginProperty, new Thickness(8, 0, 4, 0));
        content.SetBinding(ContentPresenter.ContentProperty, new Binding(nameof(ListBoxItem.Content)) { RelativeSource = RelativeSource.TemplatedParent });
        FrameworkElementFactory indicator = new(typeof(Border), "indicator");
        indicator.SetValue(Border.BackgroundProperty, SystemColors.HighlightBrush);
        indicator.SetValue(WidthProperty, 3d); indicator.SetValue(HeightProperty, 20d);
        indicator.SetValue(HorizontalAlignmentProperty, HorizontalAlignment.Left); indicator.SetValue(VerticalAlignmentProperty, VerticalAlignment.Center);
        indicator.SetValue(VisibilityProperty, Visibility.Collapsed); indicator.SetValue(Border.CornerRadiusProperty, new CornerRadius(1.5));
        FrameworkElementFactory grid = new(typeof(Grid)); grid.AppendChild(content); grid.AppendChild(indicator);
        FrameworkElementFactory border = new(typeof(Border), "background"); border.SetValue(Border.CornerRadiusProperty, new CornerRadius(5));
        border.SetValue(Border.BackgroundProperty, Brushes.Transparent); border.AppendChild(grid);
        ControlTemplate template = new(typeof(ListBoxItem)) { VisualTree = border };
        Trigger hovered = new() { Property = IsMouseOverProperty, Value = true };
        hovered.Setters.Add(new Setter(Border.BackgroundProperty, new SolidColorBrush(Color.FromArgb(24, 128, 128, 128)), "background"));
        template.Triggers.Add(hovered);
        Trigger selected = new() { Property = Selector.IsSelectedProperty, Value = true };
        selected.Setters.Add(new Setter(VisibilityProperty, Visibility.Visible, "indicator"));
        selected.Setters.Add(new Setter(Border.BackgroundProperty, new SolidColorBrush(Color.FromArgb(42, 128, 128, 128)), "background"));
        template.Triggers.Add(selected);
        Style style = new(typeof(ListBoxItem)); style.Setters.Add(new Setter(Control.TemplateProperty, template)); return style;
    }
}
