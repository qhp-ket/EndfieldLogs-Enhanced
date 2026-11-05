using System.IO;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using EndfieldLogs.Desktop.Presentation;

namespace EndfieldLogs.Desktop.Verification;

internal static partial class ProductProbe
{
    internal static int RunNavigationChecks(string output)
    {
        Dictionary<string, bool> checks = [];
        try
        {
            Application application = new() { ShutdownMode = ShutdownMode.OnExplicitShutdown };
            VerifyNavigation((name, passed) => { checks.Add(name, passed); if (!passed) throw new InvalidOperationException(name); });
            File.WriteAllText(output, JsonSerializer.Serialize(new { passed = true, checks, windows = application.Windows.Count }, new JsonSerializerOptions { WriteIndented = true }));
            return 0;
        }
        catch (Exception error) { File.WriteAllText(output, JsonSerializer.Serialize(new { passed = false, checks, error = error.ToString() })); return 1; }
    }

    internal static void VerifyNavigation(Action<string, bool> check)
    {
        foreach (var dark in new[] { false, true })
        {
            string mode = dark ? "dark" : "light";
            BattlePalette palette = new(dark);
            MainNavigation navigation = new() { Background = palette.Background };
            navigation.SetValue(TextElement.ForegroundProperty, palette.Ink);
            Dictionary<MainPage, TextBox> pages = [];
            string[] names = ["首页", "悬浮窗", "战斗日志", "运行日志", "设置"];
            foreach (var key in Enum.GetValues<MainPage>())
            {
                pages[key] = new() { Text = key + " state" };
                navigation.AddPage(key, names[(int)key], "\uE80F", pages[key], key is MainPage.Overlays or MainPage.Logs);
            }
            void Layout(double width = 1200)
            { navigation.Measure(new(width, 700)); navigation.Arrange(new(0, 0, width, 700)); navigation.UpdateLayout(); }
            Layout();
            check(mode + "_page_order", navigation.PageNames.SequenceEqual(names));
            check(mode + "_initial_home", navigation.SelectedPage == MainPage.Home && navigation.SelectedContent == pages[MainPage.Home]);
            check(mode + "_expanded_sidebar", navigation.IsExpanded && navigation.ColumnDefinitions[0].ActualWidth == 220);
            var changes = 0; navigation.PageChanged += _ => changes++;
            foreach (var key in Enum.GetValues<MainPage>()) navigation.Select(key);
            pages[MainPage.Settings].Text = "保留的设置"; navigation.Select(MainPage.Home); navigation.Select(MainPage.Settings);
            check(mode + "_switch_preserves_page_state", navigation.SelectedContent == pages[MainPage.Settings] && pages[MainPage.Settings].Text == "保留的设置" && changes == 6);
            var toggle = Descendants<Button>(navigation).Single(); toggle.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); Layout();
            check(mode + "_collapse_button", !navigation.IsExpanded && navigation.ColumnDefinitions[0].ActualWidth == 60);
            check(mode + "_collapsed_labels_and_tooltips", Descendants<ListBoxItem>(navigation).Count() == 5
                && Descendants<ListBoxItem>(navigation).All(item => item.ToolTip is string { Length: > 0 })
                && navigation.SelectedPage == MainPage.Settings);
            toggle.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); navigation.SetValue(TextElement.FontSizeProperty, 26d); Layout(780);
            check(mode + "_expanded_large_font", navigation.IsExpanded && navigation.ColumnDefinitions[0].ActualWidth >= 364
                && pages[MainPage.Settings].ActualWidth > 300 && (double)pages[MainPage.Settings].GetValue(TextElement.FontSizeProperty) == 26);
            check(mode + "_theme_inherits_foreground", Descendants<TextBlock>(navigation)
                .Where(label => names.Contains(label.Text)).All(label => ReferenceEquals(label.Foreground, palette.Ink)));
        }
    }
}
