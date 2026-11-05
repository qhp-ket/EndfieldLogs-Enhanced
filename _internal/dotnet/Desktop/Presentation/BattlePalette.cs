using System.Windows;
using System.Windows.Media;
using Microsoft.Win32;

namespace EndfieldLogs.Desktop.Presentation;

internal sealed class BattlePalette(bool dark)
{
    internal Brush Background { get; } = dark ? new SolidColorBrush(Color.FromRgb(31, 34, 39)) : SystemColors.WindowBrush;
    internal Brush Ink { get; } = dark ? new SolidColorBrush(Color.FromRgb(233, 236, 240)) : SystemColors.ControlTextBrush;
    internal static bool Dark(string mode)
    {
        if (SystemParameters.HighContrast) return SystemColors.WindowColor.R < 128;
        if (mode != "system") return mode == "dark";
        try { return Registry.GetValue(@"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", 1) is int value && value == 0; }
        catch (Exception error) when (error is System.Security.SecurityException or UnauthorizedAccessException or System.IO.IOException) { return SystemColors.WindowColor.R < 128; }
    }
}
