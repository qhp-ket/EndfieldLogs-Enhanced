using System.Windows;
using System.Windows.Controls;
using System.Windows.Data;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

internal static class Ui
{
    internal static bool ApplyAppearance(Window window, string mode, int fontPercent)
    {
        var dark = BattlePalette.Dark(mode); BattlePalette palette = new(dark);
        window.FontFamily = new FontFamily("Microsoft YaHei UI"); window.FontSize = 13 * fontPercent / 100d;
#pragma warning disable WPF0001
        window.ThemeMode = dark ? System.Windows.ThemeMode.Dark : System.Windows.ThemeMode.Light;
#pragma warning restore WPF0001
        window.Background = palette.Background; window.Foreground = palette.Ink;
        window.Resources["PageForeground"] = palette.Ink;
        window.Resources["PageCardBackground"] = new SolidColorBrush(dark ? Color.FromRgb(40, 40, 40) : Color.FromRgb(250, 250, 250));
        window.Resources["PageCardBorder"] = new SolidColorBrush(dark ? Color.FromRgb(55, 55, 55) : Color.FromRgb(232, 232, 232));
        window.Resources["PageButtonBackground"] = new SolidColorBrush(dark ? Color.FromRgb(51, 51, 51) : Colors.White);
        window.Resources["PageButtonBorder"] = new SolidColorBrush(dark ? Color.FromRgb(68, 68, 68) : Color.FromRgb(220, 220, 220));
        window.Resources["PageButtonForeground"] = palette.Ink;
        window.Resources["PageDisabledForeground"] = new SolidColorBrush(dark ? Color.FromRgb(135, 135, 135) : Color.FromRgb(145, 145, 145));
        return dark;
    }
    internal static bool? ShowDialog(Window dialog)
    {
        if (dialog.Owner is { } owner)
        {
#pragma warning disable WPF0001
            dialog.ThemeMode = owner.ThemeMode;
#pragma warning restore WPF0001
            dialog.FontFamily = owner.FontFamily; dialog.FontSize = owner.FontSize;
            dialog.Background = owner.Background; dialog.Foreground = owner.Foreground;
            foreach (var key in new[] { "PageForeground", "PageCardBackground", "PageCardBorder", "PageButtonBackground", "PageButtonBorder", "PageButtonForeground", "PageDisabledForeground" })
                if (owner.TryFindResource(key) is { } value) dialog.Resources[key] = value;
        }
        else ApplyAppearance(dialog, "system", 100);
        return dialog.ShowDialog();
    }
    public static Button Button(string text, Action action, bool primary = false)
    {
        Button button = new() { Content = text, Padding = new(14, 5, 14, 5), Margin = new(0, 0, 8, 6), MinHeight = 32,
            HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center };
        FrameworkElementFactory border = new(typeof(Border)); border.SetValue(Border.CornerRadiusProperty, new CornerRadius(4));
        border.SetValue(Border.BackgroundProperty, new TemplateBindingExtension(Control.BackgroundProperty));
        border.SetValue(Border.BorderBrushProperty, new TemplateBindingExtension(Control.BorderBrushProperty));
        border.SetValue(Border.BorderThicknessProperty, new Thickness(1));
        FrameworkElementFactory content = new(typeof(ContentPresenter)); content.SetValue(FrameworkElement.MarginProperty, new TemplateBindingExtension(Control.PaddingProperty));
        content.SetValue(FrameworkElement.HorizontalAlignmentProperty, HorizontalAlignment.Center); content.SetValue(FrameworkElement.VerticalAlignmentProperty, VerticalAlignment.Center);
        content.SetValue(ContentPresenter.RecognizesAccessKeyProperty, true); border.AppendChild(content);
        Style style = new(typeof(Button)); style.Setters.Add(new Setter(Control.TemplateProperty, new ControlTemplate(typeof(Button)) { VisualTree = border }));
        style.Setters.Add(new Setter(Control.BackgroundProperty, new DynamicResourceExtension("PageButtonBackground")));
        style.Setters.Add(new Setter(Control.ForegroundProperty, new DynamicResourceExtension("PageButtonForeground")));
        style.Setters.Add(new Setter(Control.BorderBrushProperty, new DynamicResourceExtension("PageButtonBorder")));
        style.Triggers.Add(new Trigger { Property = UIElement.IsKeyboardFocusedProperty, Value = true, Setters = { new Setter(Control.BorderBrushProperty, new SolidColorBrush(Color.FromRgb(0, 156, 196))) } });
        style.Triggers.Add(new Trigger { Property = UIElement.IsMouseOverProperty, Value = true, Setters = { new Setter(UIElement.OpacityProperty, .85) } });
        style.Triggers.Add(new Trigger { Property = System.Windows.Controls.Primitives.ButtonBase.IsPressedProperty, Value = true, Setters = { new Setter(UIElement.OpacityProperty, .65) } });
        style.Triggers.Add(new Trigger { Property = UIElement.IsEnabledProperty, Value = false, Setters = { new Setter(UIElement.OpacityProperty, .5) } });
        button.Style = style;
        if (primary) { button.Background = new SolidColorBrush(Color.FromRgb(0, 120, 156)); button.Foreground = Brushes.White; }
        button.Click += (_, _) => action(); return button;
    }
    public static TextBlock Text(string text, double? size = null)
    {
        TextBlock label = new() { Text = text, TextWrapping = TextWrapping.Wrap, Margin = new(0, 3, 0, 6) };
        if (size is { } value) label.SetBinding(TextBlock.FontSizeProperty, new Binding(nameof(Control.FontSize))
        { RelativeSource = new(RelativeSourceMode.FindAncestor, typeof(Window), 1), Converter = new FontSizeRatio(value / 13), FallbackValue = value });
        return label;
    }
    private sealed class FontSizeRatio(double ratio) : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => value is double size ? size * ratio : 13 * ratio;
        public object ConvertBack(object value, Type targetType, object parameter, System.Globalization.CultureInfo culture) => Binding.DoNothing;
    }
    public static DataGrid Table()
    {
        DataGrid table = new()
        {
            AutoGenerateColumns = false, IsReadOnly = true, CanUserAddRows = false, CanUserDeleteRows = false,
            GridLinesVisibility = DataGridGridLinesVisibility.Horizontal, HeadersVisibility = DataGridHeadersVisibility.Column,
            SelectionUnit = DataGridSelectionUnit.FullRow, RowHeight = double.NaN, MinRowHeight = 30,
            EnableRowVirtualization = true, EnableColumnVirtualization = true, AlternationCount = 2,
            HorizontalGridLinesBrush = new SolidColorBrush(Color.FromArgb(28, 128, 128, 128)),
            BorderThickness = new(0), Background = Brushes.Transparent, RowBackground = Brushes.Transparent,
            AlternatingRowBackground = new SolidColorBrush(Color.FromArgb(12, 128, 128, 128)),
        };
        VirtualizingPanel.SetIsVirtualizing(table, true); VirtualizingPanel.SetVirtualizationMode(table, VirtualizationMode.Recycling);
        table.SetResourceReference(Control.ForegroundProperty, "PageForeground");
        Style cell = new(typeof(DataGridCell));
        cell.Setters.Add(new Setter(Control.ForegroundProperty, new Binding(nameof(DataGrid.Foreground)) { RelativeSource = new(RelativeSourceMode.FindAncestor, typeof(DataGrid), 1) }));
        cell.Triggers.Add(new Trigger { Property = DataGridCell.IsSelectedProperty, Value = true, Setters = { new Setter(Control.ForegroundProperty, SystemColors.HighlightTextBrush) } });
        table.CellStyle = cell;
        Style header = new(typeof(System.Windows.Controls.Primitives.DataGridColumnHeader));
        header.Setters.Add(new Setter(Control.ForegroundProperty, new Binding(nameof(DataGrid.Foreground)) { RelativeSource = new(RelativeSourceMode.FindAncestor, typeof(DataGrid), 1) }));
        header.Setters.Add(new Setter(Control.BackgroundProperty, new DynamicResourceExtension("PageCardBackground")));
        header.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(7, 6, 7, 6)));
        header.Setters.Add(new Setter(Control.FontWeightProperty, FontWeights.SemiBold)); table.ColumnHeaderStyle = header;
        return table;
    }
    public static void Column(DataGrid grid, string title, string path, bool number = false, string? format = null, double width = 110)
    {
        var binding = new Binding(path) { StringFormat = format, TargetNullValue = "未知" };
        Style style = new(typeof(TextBlock)); style.Setters.Add(new Setter(FrameworkElement.MarginProperty, new Thickness(7, 4, 7, 4)));
        style.Setters.Add(new Setter(TextBlock.TextAlignmentProperty, number ? TextAlignment.Right : TextAlignment.Left));
        style.Setters.Add(new Setter(TextBlock.TextTrimmingProperty, TextTrimming.CharacterEllipsis));
        style.Setters.Add(new Setter(FrameworkElement.ToolTipProperty, new Binding(path) { StringFormat = format, TargetNullValue = "未知" }));
        grid.Columns.Add(new DataGridTextColumn { Header = title, Binding = binding, Width = width, ElementStyle = style });
    }
    public static string? Ask(Window owner, string title, string label, string initial)
    {
        Window dialog = new() { Title = title, Owner = owner, Width = 460, SizeToContent = SizeToContent.Height, ResizeMode = ResizeMode.NoResize, WindowStartupLocation = WindowStartupLocation.CenterOwner };
        StackPanel body = new() { Margin = new(18) }; TextBox entry = new() { Text = initial, Margin = new(0, 5, 0, 15), MinWidth = 360 };
        body.Children.Add(Text(label)); body.Children.Add(entry);
        var save = Button("确定", () => dialog.DialogResult = true); save.IsDefault = true; body.Children.Add(save); dialog.Content = body;
        dialog.Loaded += (_, _) => { entry.Focus(); entry.SelectAll(); };
        return ShowDialog(dialog) == true ? entry.Text : null;
    }
}
