using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace EndfieldLogs.Desktop.Presentation;

/// <summary>Shared page sections; typography and colors follow the owning window.</summary>
internal sealed class PageCard : Border
{
    internal PageCard(string title, UIElement content)
    {
        CornerRadius = new(6); BorderThickness = new(1);
        SetResourceReference(BorderBrushProperty, "PageCardBorder"); SetResourceReference(BackgroundProperty, "PageCardBackground");
        DockPanel body = new();
        var heading = Ui.Text(title); heading.FontWeight = FontWeights.SemiBold; heading.Margin = new(20, 12, 20, 12);
        Border header = new() { Child = heading, BorderThickness = new(0, 0, 0, 1) }; header.SetResourceReference(BorderBrushProperty, "PageCardBorder");
        DockPanel.SetDock(header, Dock.Top); body.Children.Add(header);
        Border padded = new() { Padding = new(20, 18, 20, 18), Child = content }; body.Children.Add(padded); Child = body;
    }
}
